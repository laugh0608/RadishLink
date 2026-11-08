//! Bounded replies backed by an unambiguous receive commit and its original ingress instance.
use super::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OutboundAckAdmission {
    Queued,
    Full,
    NotEligible,
}

#[derive(PartialEq, Eq)]
pub(super) enum AckTarget {
    Data(String),
    Control(ObjectRef),
}

#[derive(PartialEq, Eq)]
pub(super) struct PendingAck {
    activity: ActivityId,
    channel: OutboundChannel,
    target: AckTarget,
}

pub(super) struct QueuedAckEvent {
    pub(super) event: OutboundEvent,
    pub(super) channel: OutboundChannel,
}

impl Store {
    /// Called after a successful receive COMMIT or a fresh retransmission
    /// matched against its committed responsibility.
    pub(super) fn queue_committed_ack(
        &mut self,
        activity: ActivityId,
        channel: OutboundChannel,
        target: AckTarget,
    ) -> OutboundAckAdmission {
        let pending = PendingAck {
            activity,
            channel,
            target,
        };
        if self.outbound_acks.contains(&pending) {
            return OutboundAckAdmission::Queued;
        }
        if self.outbound_acks.len() == MAX_CYCLE_ACKS {
            return OutboundAckAdmission::Full;
        }
        self.outbound_acks.push(pending);
        OutboundAckAdmission::Queued
    }

    pub(super) fn discard_acks_on_channel(&mut self, channel: &OutboundChannel) {
        self.outbound_acks
            .retain(|pending| &pending.channel != channel);
    }

    pub(super) fn registered_control_ack_progress(
        &self,
        activity: ActivityId,
        channel: &OutboundChannel,
        object: ObjectRef,
        now: i64,
    ) -> Result<Option<ControlProgress>> {
        self.check_registered_channel(activity, channel, now)?;
        let source_matches: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM current_control_objects
             WHERE reference=?1 AND ack_source_credential=?2)",
            params![object.as_slice(), channel.peer_credential.as_slice()],
            |row| row.get(0),
        )?;
        if !source_matches
            || !self.control_output_allowed(&activity, &object, &channel.peer, now)?
        {
            return Ok(None);
        }
        self.control_progress(object, channel.peer)
    }

    /// Freeze this step's views of the same slots. The original descriptors remain until
    /// a known successful dispatch transaction. A rollback does not synthesize a retry.
    pub(super) fn stage_queued_acks(
        &mut self,
        activity: ActivityId,
        clock: &Clock,
    ) -> Result<(Vec<QueuedAckEvent>, Vec<Error>)> {
        let mut staged = Vec::new();
        let mut discarded = Vec::new();
        let mut keep = [false; MAX_CYCLE_ACKS];
        for (pending, keep) in self.outbound_acks.iter().zip(&mut keep) {
            if pending.activity != activity {
                discarded.push(Error::new(Code::Conflict, "queued ACK activity changed"));
                continue;
            }
            match self.stage_ack(pending, clock) {
                Ok(event) => {
                    *keep = true;
                    staged.push(QueuedAckEvent {
                        event,
                        channel: pending.channel,
                    });
                }
                Err(error) if matches!(error.code, Code::Conflict | Code::Expired) => {
                    discarded.push(error)
                }
                Err(error) => return Err(error),
            }
        }
        let mut keep = keep.into_iter();
        self.outbound_acks
            .retain(|_| keep.next().expect("bounded ACK queue"));
        Ok((staged, discarded))
    }

    fn stage_ack(&self, pending: &PendingAck, clock: &Clock) -> Result<OutboundEvent> {
        let PendingAck {
            activity,
            channel,
            target,
        } = pending;
        match target {
            AckTarget::Data(message) => {
                self.check_registered_channel(*activity, channel, clock.monotonic_ms)?;
                let neighbor = credential_key(&channel.peer_credential);
                if !self.data_ack_eligible(message, &neighbor, clock, true)? {
                    return Err(Error::new(
                        Code::Conflict,
                        "queued data ACK responsibility changed",
                    ));
                }
                Ok(OutboundEvent::DataAck {
                    message: message.clone(),
                    neighbor,
                })
            }
            AckTarget::Control(object) => {
                if self
                    .registered_control_ack_progress(
                        *activity,
                        channel,
                        *object,
                        clock.monotonic_ms,
                    )?
                    .is_none()
                {
                    return Err(Error::new(
                        Code::Conflict,
                        "queued control ACK responsibility changed",
                    ));
                }
                Ok(OutboundEvent::ControlAck {
                    object: *object,
                    neighbor: channel.peer,
                })
            }
        }
    }
}
