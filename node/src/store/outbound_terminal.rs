//! Owner-side handoff of an already authenticated, restrictive LinkAckV1 observation.
use super::*;
use crate::retry::{Admission, LinkEvent, Signal};

/// A strictly checked inbound ACK, supplied by the authenticated owner. The data key is
/// the owner's resolved reference, and the binding is the ACK's exact message_binding.
pub enum OutboundTerminalAck {
    Data { message: String, binding: ObjectRef },
    Control { object: ObjectRef },
}

#[derive(Debug, PartialEq, Eq)]
pub enum OutboundTerminalAdmission {
    Accepted { close: Option<OutboundChannel> },
    AlreadyTerminal,
}

pub(super) struct PendingTerminal {
    activity: ActivityId,
    domain: ClockDomainId,
    channel: OutboundChannel,
    ack: OutboundTerminalAck,
    clock: Clock,
}

impl Store {
    pub(super) fn require_outbound_ready(&self) -> Result<()> {
        if self.outbound_terminal.is_some() {
            return Err(Error::new(Code::Busy, "outbound terminal input pending"));
        }
        self.handoff.require_drained()
    }

    /// Accept one verified inbound ACK and withdraw the committed handoff batch.
    /// The caller must apply any returned close to the original channel instance.
    /// This changes only runtime state. No budget is refunded and no reply is generated.
    pub fn accept_outbound_terminal(
        &mut self,
        source: &ControlIngressChannel,
        ack: OutboundTerminalAck,
        clock: Clock,
    ) -> Result<OutboundTerminalAdmission> {
        if self.outbound_terminal.is_some() {
            return Err(Error::new(Code::Busy, "outbound terminal input pending"));
        }
        self.validate_clock_advance(&clock)?;
        let (activity, channel) = self.control_ingress_channel(source)?;
        let terminal = PendingTerminal {
            activity,
            domain: self.current_domain_id()?,
            channel,
            ack,
            clock,
        };
        let active = self.check_terminal_target(&terminal)?;
        let final_attempt_pending = match terminal.ack {
            OutboundTerminalAck::Control { object } => self
                .handoff
                .contains(&OutboundResponsibility::Control(object, channel.peer)),
            OutboundTerminalAck::Data { .. } => false,
        };
        if !active && !final_attempt_pending {
            return Ok(OutboundTerminalAdmission::AlreadyTerminal);
        }
        // With one slot and one ordered batch, cancelling the whole batch also closes any
        // unrelated partial frame instead of holding it open while waiting on the terminal write.
        let close = self.cancel_outbound_handoff();
        self.outbound_terminal = Some(terminal);
        Ok(OutboundTerminalAdmission::Accepted { close })
    }

    /// Commit just the terminal effect at a new trusted coordinate. Any failure keeps the
    /// scheduling fence. The owner can explicitly retry a known rollback with a new sample.
    pub fn commit_outbound_terminal(&mut self, clock: Clock) -> Result<()> {
        self.validate_clock_advance(&clock)?;
        let pending = self
            .outbound_terminal
            .as_ref()
            .ok_or_else(|| Error::new(Code::Conflict, "outbound terminal input missing"))?;
        if clock.precedes(&pending.clock) {
            self.time_uncertain = true;
            return Err(Error::new(
                Code::TimeUncertain,
                "outbound terminal clock regression",
            ));
        }
        if clock.monotonic_ms == pending.clock.monotonic_ms {
            return Err(Error::new(
                Code::Busy,
                "outbound terminal needs a new coordinate",
            ));
        }
        let mut pending = self
            .outbound_terminal
            .take()
            .expect("checked terminal input");
        pending.clock = clock.clone();
        let result = self.atomic(|s| {
            let active = s.check_terminal_target(&pending)?;
            s.write_clock(&clock)?;
            let batch = Batch {
                now_ms: clock.monotonic_ms,
                link: LinkEvent::Unchanged,
                signal: Signal::Pause,
                admission: Admission::Allow,
            };
            match &pending.ack {
                OutboundTerminalAck::Data { message, .. } if active => {
                    s.advance_queue_in_transaction(
                        message,
                        "data",
                        &credential_key(&pending.channel.peer_credential),
                        batch,
                        &clock,
                    )?;
                }
                OutboundTerminalAck::Data { .. } => {}
                OutboundTerminalAck::Control { object } => {
                    // A final committed send can mark the row terminal by exhaustion.
                    // Persist the authenticated Pause for this accepted input as well.
                    s.advance_control(&pending.activity, *object, pending.channel.peer, batch)?;
                }
            }
            Ok(())
        });
        if result.is_ok() {
            self.clock = clock;
        } else {
            self.outbound_terminal = Some(pending);
        }
        result
    }

    fn check_terminal_target(&self, terminal: &PendingTerminal) -> Result<bool> {
        let PendingTerminal {
            activity,
            domain,
            channel,
            ack,
            clock,
        } = terminal;
        if *domain != self.current_domain_id()? {
            return Err(Error::new(
                Code::Conflict,
                "outbound terminal domain changed",
            ));
        }
        let local = self.control_live(activity, clock.monotonic_ms)?;
        self.reject_local_retirement()?;
        // The source instance was checked at admission. A later close cannot erase that
        // restrictive fact, and the captured credential still has to be active now.
        if local != channel.local
            || self.control_binding(&channel.local_credential, &local)? != BindingState::Active
            || self.control_binding(&channel.peer_credential, &channel.peer)?
                != BindingState::Active
        {
            return Err(Error::new(
                Code::Conflict,
                "outbound terminal credential changed",
            ));
        }
        match ack {
            OutboundTerminalAck::Data { message, binding } => {
                self.check_data_terminal(message, binding, channel, clock)
            }
            OutboundTerminalAck::Control { object } => {
                let progress = self
                    .control_progress(*object, channel.peer)?
                    .ok_or_else(|| {
                        Error::new(
                            Code::Conflict,
                            "outbound control terminal responsibility missing",
                        )
                    })?;
                if !self.control_output_allowed(
                    activity,
                    object,
                    &channel.peer,
                    clock.monotonic_ms,
                )? {
                    return Err(Error::new(
                        Code::Conflict,
                        "outbound control terminal policy",
                    ));
                }
                Ok(!progress.terminal)
            }
        }
    }

    fn check_data_terminal(
        &self,
        message: &str,
        binding: &ObjectRef,
        channel: &OutboundChannel,
        clock: &Clock,
    ) -> Result<bool> {
        check_ref(message)?;
        let neighbor = credential_key(&channel.peer_credential);
        let record: Option<(Vec<u8>, String)> = self.conn.query_row(
            "SELECT m.core,q.retry FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.message_key=?1 AND q.kind='data' AND q.neighbor=?2",
            params![message, neighbor], |r| Ok((r.get(0)?, r.get(1)?)),
        ).optional()?;
        let (core, retry) = record.ok_or_else(|| {
            Error::new(
                Code::Conflict,
                "outbound data terminal responsibility missing",
            )
        })?;
        if core.as_slice() != binding {
            return Err(Error::new(
                Code::Conflict,
                "outbound data terminal message binding",
            ));
        }
        self.data_remaining_at(message, clock)?;
        self.authorize_business_message(message, Some(&neighbor), clock.monotonic_ms)?;
        let state: RetryState = serde_json::from_str(&retry).map_err(|e| {
            Error::source_error(Code::StoreCorrupt, "outbound data terminal retry", e)
        })?;
        state.validate()?;
        if clock.monotonic_ms >= state.deadline_ms() {
            return Err(Error::new(
                Code::Expired,
                "outbound data terminal queue deadline",
            ));
        }
        Ok(state.is_active())
    }
}
