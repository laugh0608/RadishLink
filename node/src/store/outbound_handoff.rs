//! Store-owned, offline output handoff. No encoding, I/O or worker dispatch occurs here.
use super::*;
use std::{
    collections::{BTreeMap, VecDeque},
    sync::Arc,
};

type Responsibility = OutboundResponsibility;
pub(super) type BindChannel<'a> = dyn FnMut(&OutboundEvent) -> Option<OutboundChannel> + 'a;

/// Facts captured by the authenticated owner. An instance changes on every reconnect,
/// even when both credentials are unchanged. This type does not authenticate a channel.
/// Caller-assigned synthetic instances use the lower half of the instance number space.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct OutboundChannel {
    pub instance: u64,
    pub local: ParticipantId,
    pub local_credential: CredentialRef,
    pub peer: ParticipantId,
    pub peer_credential: CredentialRef,
}

impl OutboundChannel {
    pub(super) const REGISTERED_INSTANCE_START: u64 = 1 << 63;

    fn is_registered(self) -> bool {
        self.instance >= Self::REGISTERED_INSTANCE_START
    }
}

/// Shape of a synthetic frame. A partial frame must keep exactly this descriptor.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OutboundFrame {
    Data {
        bytes: usize,
        remaining_ms: i64,
        hops: u8,
    },
    Control {
        bytes: usize,
    },
}

impl OutboundFrame {
    fn bytes(self) -> usize {
        match self {
            Self::Data { bytes, .. } | Self::Control { bytes } => bytes,
        }
    }
}

pub struct OutboundHandoffInput {
    pub clock: Clock,
    /// Current eligible instance, or None if it is closed/revoked.
    pub channel: Option<OutboundChannel>,
    pub frame: OutboundFrame,
}

pub struct OutboundHandoffRequest {
    owner: Arc<()>,
    revision: i64,
    position: usize,
    pub responsibility: OutboundResponsibility,
    pub channel: OutboundChannel,
    offset: usize,
}

pub enum OutboundWrite {
    Written(usize),
    NotReady,
    /// The attempt is known to have written zero additional bytes.
    Failed(Error),
    Unknown(Error),
}

#[derive(Debug, PartialEq, Eq)]
pub enum OutboundWriteProgress {
    Partial(usize),
    Complete,
    Discarded,
}

pub struct OutboundHandoffStep {
    pub result: Result<OutboundWriteProgress>,
    /// The owner must retire this instance before doing any more work on it.
    pub close: Option<OutboundChannel>,
}

struct Scope {
    domain: ClockDomainId,
    activity: ActivityId,
    policy: i64,
}

pub(super) struct PreparedHandoff {
    scope: Scope,
    bindings: BTreeMap<Responsibility, HandoffBinding>,
}

#[derive(Clone, Copy, PartialEq, Eq)]
struct HandoffBinding {
    channel: Option<OutboundChannel>,
    registered_ack: bool,
}

struct Pending {
    position: usize,
    responsibility: Responsibility,
    channel: OutboundChannel,
    registered_ack: bool,
    partial: Option<(OutboundFrame, usize)>,
}

struct CommittedBatch {
    scope: Scope,
    revision: i64,
    pending: VecDeque<Pending>,
}

#[derive(Default)]
pub(super) struct HandoffState {
    batch: Option<CommittedBatch>,
    last_clock: Option<Clock>,
}

impl HandoffState {
    pub(super) fn contains(&self, responsibility: &OutboundResponsibility) -> bool {
        self.batch.as_ref().is_some_and(|batch| {
            batch
                .pending
                .iter()
                .any(|item| &item.responsibility == responsibility)
        })
    }

    pub(super) fn observed_after(&self, clock: &Clock) -> bool {
        self.last_clock
            .as_ref()
            .is_some_and(|last| clock.precedes(last))
    }

    pub(super) fn require_drained(&self) -> Result<()> {
        if self.batch.is_some() {
            return Err(Error::new(
                Code::Busy,
                "outbound handoff batch still pending",
            ));
        }
        Ok(())
    }

    pub(super) fn publish(
        &mut self,
        prepared: PreparedHandoff,
        revision: i64,
        report: &OutboundReport,
    ) {
        let pending: VecDeque<_> = report
            .decisions
            .iter()
            .enumerate()
            .filter_map(|(position, decision)| {
                let responsibility = decision.output()?;
                let binding = prepared.bindings.get(&responsibility)?;
                Some(Pending {
                    position,
                    responsibility,
                    channel: binding.channel?,
                    registered_ack: binding.registered_ack,
                    partial: None,
                })
            })
            .collect();
        if !pending.is_empty() {
            self.batch = Some(CommittedBatch {
                scope: prepared.scope,
                revision,
                pending,
            });
        }
    }
}

impl Store {
    pub(super) fn prepare_outbound_handoff(
        &self,
        activity: ActivityId,
        events: &[OutboundEvent],
        queued_acks: &[outbound_ack::QueuedAckEvent],
        bind: &mut BindChannel<'_>,
    ) -> Result<PreparedHandoff> {
        let mut bindings = BTreeMap::new();
        let mut instances = BTreeMap::new();
        for event in events
            .iter()
            .chain(queued_acks.iter().map(|ack| &ack.event))
        {
            event.validate_refs()?;
        }
        let explicit = events.iter().map(|event| {
            (
                event,
                HandoffBinding {
                    channel: bind(event),
                    registered_ack: false,
                },
            )
        });
        let registered = queued_acks.iter().map(|ack| {
            (
                &ack.event,
                HandoffBinding {
                    channel: Some(ack.channel),
                    registered_ack: true,
                },
            )
        });
        for (event, binding) in explicit.chain(registered) {
            if let Some(channel) = binding.channel {
                if channel.is_registered() {
                    self.ingress.require_channel(&channel)?;
                }
                if instances
                    .insert(channel.instance, channel)
                    .is_some_and(|old| old != channel)
                {
                    return Err(Error::new(
                        Code::Conflict,
                        "outbound channel instance has conflicting bindings",
                    ));
                }
            }
            if bindings
                .insert(event.responsibility(), binding)
                .is_some_and(|old| old != binding)
            {
                return Err(Error::new(
                    Code::Conflict,
                    "outbound input has conflicting channels",
                ));
            }
        }
        Ok(PreparedHandoff {
            scope: Scope {
                domain: self.current_domain_id()?,
                activity,
                policy: self.outbound_policy_revision()?,
            },
            bindings,
        })
    }

    fn outbound_policy_revision(&self) -> Result<i64> {
        // Scope and per-kind eligibility are checked separately, including D13's exit branch.
        Ok(self.conn.query_row(
            "SELECT policy_revision FROM current_control_activity WHERE id=1",
            [],
            |r| r.get(0),
        )?)
    }

    pub fn next_outbound_handoff(&self) -> Option<OutboundHandoffRequest> {
        let batch = self.handoff.batch.as_ref()?;
        let item = batch.pending.front()?;
        Some(OutboundHandoffRequest {
            owner: self.ingress.owner().clone(),
            revision: batch.revision,
            position: item.position,
            responsibility: item.responsibility.clone(),
            channel: item.channel,
            offset: item.partial.map_or(0, |(_, offset)| offset),
        })
    }

    /// Ends this batch before shutdown or the next round. A partially written frame
    /// requires closing its original instance. A later round never inherits any item.
    pub fn cancel_outbound_handoff(&mut self) -> Option<OutboundChannel> {
        self.handoff
            .batch
            .take()?
            .pending
            .front()
            .and_then(|item| item.partial.map(|_| item.channel))
    }

    pub(super) fn discard_handoff_on_channel(&mut self, channel: &OutboundChannel) {
        if let Some(batch) = &mut self.handoff.batch {
            batch.pending.retain(|item| &item.channel != channel);
            if batch.pending.is_empty() {
                self.handoff.batch = None;
            }
        }
    }

    /// Ordered owner-side invalidation after an authenticated terminal input, even when
    /// the last committed control attempt had already exhausted all future opportunities.
    pub fn withdraw_outbound_handoff(
        &mut self,
        responsibility: &OutboundResponsibility,
    ) -> Option<OutboundChannel> {
        let batch = self.handoff.batch.as_mut()?;
        let index = batch
            .pending
            .iter()
            .position(|item| &item.responsibility == responsibility)?;
        let item = batch.pending.remove(index)?;
        let close = item.partial.map(|_| item.channel);
        if let Some(closed) = close {
            batch.pending.retain(|pending| pending.channel != closed);
        }
        if batch.pending.is_empty() {
            self.handoff.batch = None;
        }
        close
    }

    /// Calls the synthetic writer once at the authorized offset. The callback must be
    /// bounded and have no external effects. No result or request can replay a consumed item.
    pub fn advance_outbound_handoff(
        &mut self,
        request: &OutboundHandoffRequest,
        input: OutboundHandoffInput,
        write: impl FnOnce(usize, usize) -> OutboundWrite,
    ) -> OutboundHandoffStep {
        if !Arc::ptr_eq(&request.owner, self.ingress.owner())
            || !self.handoff.batch.as_ref().is_some_and(|batch| {
                batch.revision == request.revision
                    && batch.pending.front().is_some_and(|item| {
                        item.position == request.position
                            && item.partial.map_or(0, |(_, offset)| offset) == request.offset
                    })
            })
        {
            return OutboundHandoffStep {
                result: Err(Error::new(Code::Conflict, "stale outbound handoff request")),
                close: None,
            };
        }

        let mut batch = self.handoff.batch.take().expect("checked handoff batch");
        let mut item = batch.pending.pop_front().expect("checked handoff item");
        let offset = item.partial.map_or(0, |(_, offset)| offset);
        let mut close = (input.channel != Some(item.channel)).then_some(item.channel);
        let mut keep_batch = false;

        let result = (|| {
            self.validate_clock_advance(&input.clock)?;
            self.handoff.last_clock = Some(input.clock.clone());
            if batch.scope.domain != self.current_domain_id()? {
                return Err(Error::new(Code::Conflict, "outbound handoff clock domain"));
            }
            let local = self.control_live(&batch.scope.activity, input.clock.monotonic_ms)?;
            keep_batch = batch.scope.policy == self.outbound_policy_revision()?;
            if let Err(error) = self.check_outbound_channel(local, &item, input.channel) {
                close = Some(item.channel);
                return Err(error);
            }
            if !keep_batch {
                return Err(Error::new(
                    Code::Conflict,
                    "outbound handoff policy revision changed",
                ));
            }
            self.check_outbound_local(local, &item)?;
            self.check_handoff_frame(&item, &batch.scope.activity, &input)?;
            match write(offset, input.frame.bytes() - offset) {
                OutboundWrite::Written(count) if count == input.frame.bytes() - offset => {
                    Ok(OutboundWriteProgress::Complete)
                }
                OutboundWrite::Written(count)
                    if count > 0 && count < input.frame.bytes() - offset =>
                {
                    Ok(OutboundWriteProgress::Partial(offset + count))
                }
                OutboundWrite::Written(0) | OutboundWrite::NotReady => {
                    Ok(OutboundWriteProgress::Discarded)
                }
                OutboundWrite::Failed(error) => Err(error),
                OutboundWrite::Unknown(error) => {
                    close = Some(item.channel);
                    Err(error)
                }
                OutboundWrite::Written(_) => {
                    close = Some(item.channel);
                    Err(Error::new(
                        Code::InvalidInput,
                        "outbound write exceeds frame",
                    ))
                }
            }
        })();

        if let Ok(OutboundWriteProgress::Partial(next)) = result {
            item.partial = Some((input.frame, next));
            batch.pending.push_front(item);
        } else if offset > 0 && !matches!(result, Ok(OutboundWriteProgress::Complete)) {
            close = Some(item.channel);
        }
        if let Some(closed) = close {
            batch.pending.retain(|pending| pending.channel != closed);
        }
        if keep_batch && !batch.pending.is_empty() {
            self.handoff.batch = Some(batch);
        }
        OutboundHandoffStep { result, close }
    }

    fn check_outbound_channel(
        &self,
        local: ParticipantId,
        item: &Pending,
        current: Option<OutboundChannel>,
    ) -> Result<()> {
        let channel = item.channel;
        if channel.is_registered() {
            self.ingress.require_channel(&channel)?;
        }
        if current != Some(channel) || channel.local != local || channel.peer == local {
            return Err(Error::new(
                Code::Conflict,
                "outbound handoff channel instance changed",
            ));
        }
        let neighbor_matches = match &item.responsibility {
            Responsibility::Queue(key) => key.neighbor == credential_key(&channel.peer_credential),
            Responsibility::DataAck(_, neighbor) => {
                *neighbor == credential_key(&channel.peer_credential)
            }
            Responsibility::Control(_, neighbor) | Responsibility::ControlAck(_, neighbor) => {
                *neighbor == channel.peer
            }
        };
        if !neighbor_matches
            || self.control_binding(&channel.peer_credential, &channel.peer)?
                != BindingState::Active
        {
            return Err(Error::new(
                Code::Conflict,
                "outbound handoff neighbor binding",
            ));
        }
        Ok(())
    }

    fn check_outbound_local(&self, local: ParticipantId, item: &Pending) -> Result<()> {
        let channel = item.channel;
        if self.control_binding(&channel.local_credential, &local)? == BindingState::Active {
            return Ok(());
        }
        if let Responsibility::Control(object, _) = &item.responsibility {
            let original_exit: bool = self.conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM current_control_objects WHERE reference=?1 AND kind=2 AND reporter=?2 AND issuer=?3)",
                params![object.as_slice(), local.as_slice(), channel.local_credential.as_slice()], |r| r.get(0),
            )?;
            if original_exit {
                return Ok(());
            }
        }
        Err(Error::new(Code::Conflict, "outbound handoff local binding"))
    }

    fn check_handoff_frame(
        &self,
        item: &Pending,
        activity: &ActivityId,
        input: &OutboundHandoffInput,
    ) -> Result<()> {
        if !(5..=crate::framing::MAX_FRAME_BYTES).contains(&input.frame.bytes())
            || item.partial.is_some_and(|(frame, _)| frame != input.frame)
        {
            return Err(Error::new(
                Code::InvalidInput,
                "outbound handoff frame shape changed",
            ));
        }
        match &item.responsibility {
            Responsibility::Queue(key) => self.check_handoff_queue(key, input),
            Responsibility::Control(object, neighbor) => {
                if !self.control_output_allowed(
                    activity,
                    object,
                    neighbor,
                    input.clock.monotonic_ms,
                )? || self.control_progress(*object, *neighbor)?.is_none()
                {
                    return Err(Error::new(
                        Code::Conflict,
                        "outbound control responsibility changed",
                    ));
                }
                check_control_frame(input.frame, 522)
            }
            Responsibility::DataAck(key, neighbor) => {
                if !self.data_ack_eligible(key, neighbor, &input.clock, item.registered_ack)? {
                    return Err(Error::new(
                        Code::Conflict,
                        "outbound data ACK responsibility changed",
                    ));
                }
                check_control_frame(input.frame, 127)
            }
            Responsibility::ControlAck(object, neighbor) => {
                let progress = if item.registered_ack {
                    self.registered_control_ack_progress(
                        *activity,
                        &item.channel,
                        *object,
                        input.clock.monotonic_ms,
                    )?
                } else {
                    self.control_progress(*object, *neighbor)?
                };
                if progress.is_none() {
                    return Err(Error::new(
                        Code::Conflict,
                        "outbound control ACK responsibility changed",
                    ));
                }
                check_control_frame(input.frame, 127)
            }
        }
    }

    fn check_handoff_queue(&self, key: &QueueKey, input: &OutboundHandoffInput) -> Result<()> {
        let remaining = self.data_remaining_at(&key.message, &input.clock)?;
        self.authorize_business_message(
            &key.message,
            Some(&key.neighbor),
            input.clock.monotonic_ms,
        )?;
        let row: Option<(String, u8, bool)> = self.conn.query_row(
            "SELECT q.retry,q.hops,m.payload IS NOT NULL FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.message_key=?1 AND q.kind=?2 AND q.neighbor=?3",
            params![key.message, key.kind.as_str(), key.neighbor], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        ).optional()?;
        let (encoded, hops, payload) =
            row.ok_or_else(|| Error::new(Code::Conflict, "outbound queue missing"))?;
        let retry: RetryState = serde_json::from_str(&encoded)
            .map_err(|e| Error::source_error(Code::StoreCorrupt, "outbound queue retry", e))?;
        let now = input.clock.monotonic_ms;
        if now >= retry.deadline_ms() {
            return Err(Error::new(Code::Expired, "outbound queue deadline"));
        }
        if !retry.may_handoff(now) {
            return Err(Error::new(Code::Conflict, "outbound queue is not active"));
        }
        match (key.kind, input.frame) {
            (
                QueueKind::Data,
                OutboundFrame::Data {
                    remaining_ms,
                    hops: frame_hops,
                    ..
                },
            ) if payload && frame_hops <= hops && remaining_ms > 0 => {
                if remaining_ms > remaining.min(retry.deadline_ms() - now) {
                    return Err(Error::new(Code::Expired, "outbound frame encoded lifetime"));
                }
                Ok(())
            }
            (QueueKind::Evidence, frame) => check_control_frame(frame, 522),
            _ => Err(Error::new(Code::Conflict, "outbound data frame or payload")),
        }
    }
}

fn check_control_frame(frame: OutboundFrame, limit: usize) -> Result<()> {
    if !matches!(frame, OutboundFrame::Control { bytes } if bytes <= limit && (limit != 127 || bytes == limit))
    {
        return Err(Error::new(
            Code::InvalidInput,
            "outbound control frame size or kind",
        ));
    }
    Ok(())
}
