use super::control_types::*;
use super::*;
use crate::retry::{Admission, LinkEvent, Signal};

const SLOTS_MS: [i64; 8] = [0, 1000, 3000, 10000, 30000, 120000, 600000, 1800000];

struct NeighborState {
    start: i64,
    slot: u8,
    recovery: u8,
    last_recovery: Option<i64>,
    link_up: bool,
    terminal: bool,
    attempts: u8,
    acks: u8,
    last_ms: Option<i64>,
    last_event: Option<String>,
}

impl Store {
    /// All observations at one trusted coordinate are merged before durable consumption.
    /// This is the same state owner/transaction boundary as data scheduling, with D16 rules.
    pub fn process_control_batch(
        &mut self,
        activity: ActivityId,
        clock: Clock,
        events: Vec<ControlEvent>,
    ) -> Result<Vec<ControlDecision>> {
        self.control_live(&activity, clock.monotonic_ms)?;
        let report = self.process_outbound_batch(
            clock,
            events.into_iter().map(OutboundEvent::Control).collect(),
        )?;
        Ok(report
            .decisions
            .into_iter()
            .filter_map(|d| match d {
                OutboundDecision::Control(d) => Some(d),
                _ => None,
            })
            .collect())
    }
    pub(super) fn advance_control(
        &self,
        activity: &ActivityId,
        object: ObjectRef,
        neighbor: ParticipantId,
        batch: Batch,
    ) -> Result<ControlDecision> {
        let NeighborState{start,mut slot,mut recovery,last_recovery,mut link_up,mut terminal,mut attempts,acks,last_ms,last_event} = self.conn.query_row(
            "SELECT start,next_slot,recoveries,last_recovery,link_up,terminal,attempts,ack_attempts,last_ms,last_event FROM control_neighbors WHERE object=?1 AND participant=?2",
            params![object.as_slice(),neighbor.as_slice()],
            |r|Ok(NeighborState{start:r.get(0)?,slot:r.get(1)?,recovery:r.get(2)?,last_recovery:r.get(3)?,link_up:r.get(4)?,terminal:r.get(5)?,attempts:r.get(6)?,acks:r.get(7)?,last_ms:r.get(8)?,last_event:r.get(9)?})
        )?;
        let encoded = serde_json::to_string(&batch)
            .map_err(|e| Error::source_error(Code::InvalidInput, "control event encoding", e))?;
        if batch.now_ms < start || last_ms.is_some_and(|last| batch.now_ms < last) {
            return Err(Error::new(Code::TimeUncertain, "control event time"));
        }
        let allowed = self.control_output_allowed(activity, &object, &neighbor, batch.now_ms)?;
        let duplicate = last_ms == Some(batch.now_ms);
        // Current policy overrides a duplicate observation at the same clock coordinate.
        if duplicate
            && last_event.as_deref() != Some(&encoded)
            && batch.signal == Signal::Continue
            && allowed
        {
            return Err(Error::new(Code::Conflict, "control same-coordinate event"));
        }
        terminal |= !allowed || batch.signal != Signal::Continue;
        let mut send = false;
        let mut recovered_at = last_recovery;
        if !terminal && !duplicate {
            let recovered = !link_up && batch.link == LinkEvent::Up;
            match batch.link {
                LinkEvent::Up => link_up = true,
                LinkEvent::Down => link_up = false,
                LinkEvent::Unchanged => {}
            }
            let mut on_slot = false;
            while usize::from(slot) < SLOTS_MS.len() {
                let Some(due) = start.checked_add(SLOTS_MS[usize::from(slot)]) else {
                    // Unrepresentable future slots are beyond every representable deadline.
                    break;
                };
                if batch.now_ms < due {
                    break;
                }
                on_slot |= batch.now_ms == due;
                slot += 1; // Late/down/throttled slots never accumulate catch-up sends.
            }
            let recovery_due = recovered
                && recovery < 2
                && last_recovery.is_none_or(|last| batch.now_ms - last >= 60000);
            if recovery_due {
                recovery += 1;
                recovered_at = Some(batch.now_ms);
            }
            if (on_slot || recovery_due)
                && link_up
                && batch.admission == Admission::Allow
                && attempts < 10
            {
                // Charging before the caller can write is part of this same transaction.
                if self.charge_control_output(batch.now_ms, 522)? {
                    attempts += 1;
                    send = true;
                }
            }
            terminal |= slot == 8 && recovery == 2;
        }
        self.conn.execute("UPDATE control_neighbors SET next_slot=?3,recoveries=?4,last_recovery=?5,link_up=?6,terminal=?7,attempts=?8,last_ms=?9,last_event=?10 WHERE object=?1 AND participant=?2",params![object.as_slice(),neighbor.as_slice(),slot,recovery,recovered_at,link_up,terminal,attempts,batch.now_ms,encoded])?;
        Ok(ControlDecision {
            object,
            neighbor,
            send,
            progress: ControlProgress {
                slots_consumed: slot,
                recoveries_consumed: recovery,
                attempts,
                ack_attempts: acks,
                terminal,
            },
        })
    }
    pub(super) fn control_output_allowed(
        &self,
        activity: &ActivityId,
        object: &ObjectRef,
        neighbor: &ParticipantId,
        now: i64,
    ) -> Result<bool> {
        let local = self.control_live(activity, now)?;
        if !self.participant_active(neighbor)? {
            return Ok(false);
        }
        let (kind, issuer, reporter): (i64, Vec<u8>, Vec<u8>) = self.conn.query_row(
            "SELECT kind,issuer,reporter FROM control_objects WHERE reference=?1",
            [object.as_slice()],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        let local_active = self.participant_active(&local)?;
        if !local_active && !(kind == 2 && reporter == local) {
            return Ok(false);
        }
        let issuer_active: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM control_bindings WHERE credential=?1 AND state='active')",
            [issuer],
            |r| r.get(0),
        )?;
        Ok(kind == 2 || issuer_active) // Only the retained original exit survives issuer revocation.
    }
    pub fn control_progress(
        &self,
        object: ObjectRef,
        neighbor: ParticipantId,
    ) -> Result<Option<ControlProgress>> {
        self.readable()?;
        Ok(self.conn.query_row("SELECT next_slot,recoveries,attempts,ack_attempts,terminal FROM control_neighbors WHERE object=?1 AND participant=?2",params![object.as_slice(),neighbor.as_slice()],|r|Ok(ControlProgress{slots_consumed:r.get(0)?,recoveries_consumed:r.get(1)?,attempts:r.get(2)?,ack_attempts:r.get(3)?,terminal:r.get(4)?})).optional()?)
    }
    /// No unknown-object ACK state is created. Authentication and final handoff remain external.
    pub fn consume_control_ack(
        &mut self,
        activity: ActivityId,
        object: ObjectRef,
        neighbor: ParticipantId,
    ) -> Result<bool> {
        self.control_live(&activity, self.clock.monotonic_ms)?;
        let report = self.process_outbound_batch(
            self.clock.clone(),
            vec![OutboundEvent::ControlAck { object, neighbor }],
        )?;
        Ok(report
            .decisions
            .iter()
            .any(|d| matches!(d, OutboundDecision::ControlAck { send: true, .. })))
    }
    pub(super) fn consume_control_ack_in_transaction(
        &self,
        object: ObjectRef,
        neighbor: ParticipantId,
        clock: &Clock,
    ) -> Result<bool> {
        let activity: Vec<u8> = self.conn.query_row(
            "SELECT activity FROM control_activity WHERE id=1",
            [],
            |r| r.get(0),
        )?;
        let activity: ActivityId = activity
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "ACK activity"))?;
        let local = self.control_live(&activity, clock.monotonic_ms)?;
        if !self.participant_active(&local)? || !self.participant_active(&neighbor)? {
            return Ok(false);
        }
        let count: Option<u8> = self
            .conn
            .query_row(
                "SELECT ack_attempts FROM control_neighbors WHERE object=?1 AND participant=?2",
                params![object.as_slice(), neighbor.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        if count.is_none_or(|n| n >= 10) || !self.charge_control_output(clock.monotonic_ms, 127)? {
            return Ok(false);
        }
        self.conn.execute("UPDATE control_neighbors SET ack_attempts=ack_attempts+1 WHERE object=?1 AND participant=?2",params![object.as_slice(),neighbor.as_slice()])?;
        Ok(true)
    }
    pub(super) fn charge_control_output(&self, now: i64, bytes: i64) -> Result<bool> {
        if !(1..=8192).contains(&bytes) {
            return Err(Error::new(Code::InvalidInput, "control frame charge"));
        }
        let (last, frames, balance): (i64, i64, i64) = self.conn.query_row(
            "SELECT last_ms,frames,bytes FROM control_output_rate WHERE id=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )?;
        if now < last {
            return Err(Error::new(Code::TimeUncertain, "control rate clock"));
        }
        // Capping elapsed before multiplication avoids overflow; one second fills both bursts.
        let elapsed = (now - last).min(1000);
        let mut frames = (frames + elapsed * 4).min(4000);
        let mut balance = (balance + elapsed * 8192).min(8192000);
        let allowed = frames >= 1000 && balance >= bytes * 1000;
        if allowed {
            frames -= 1000;
            balance -= bytes * 1000;
        }
        self.conn.execute(
            "UPDATE control_output_rate SET last_ms=?1,frames=?2,bytes=?3 WHERE id=1",
            params![now, frames, balance],
        )?;
        Ok(allowed)
    }
    pub(super) fn reset_control_rate_on_open(&mut self) -> Result<()> {
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM control_output_rate)",
            [],
            |r| r.get(0),
        )?;
        if exists && !self.time_uncertain {
            self.atomic(|s| {
                s.write_clock(&s.clock)?;
                s.conn.execute(
                    "UPDATE control_output_rate SET last_ms=?1,frames=0,bytes=0 WHERE id=1",
                    [s.clock.monotonic_ms],
                )?;
                Ok(())
            })?;
        }
        Ok(())
    }
}
