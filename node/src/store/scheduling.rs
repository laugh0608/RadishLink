use super::*;
use std::collections::BTreeMap;

pub const MAX_QUEUE_EVENTS: usize = 128;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum QueueKind {
    Data,
    Evidence,
}
impl QueueKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Data => "data",
            Self::Evidence => "evidence",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct QueueKey {
    pub message: String,
    pub kind: QueueKind,
    pub neighbor: String,
}
pub struct QueueEvent {
    pub queue: QueueKey,
    pub batch: Batch,
}
pub struct SchedulingReport {
    /// All decisions are durable. No caller may send after an Err or missing response.
    pub decisions: Vec<(QueueKey, Decision)>,
    pub maintenance: MaintenanceReport,
}

impl Store {
    /// Internal verified-event boundary. Not exposed by Service while security is unavailable.
    /// All same-coordinate observations must be supplied together, at most 128 input events.
    pub fn process_queue_batch(
        &mut self,
        clock: Clock,
        events: Vec<QueueEvent>,
    ) -> Result<SchedulingReport> {
        self.validate_clock_advance(&clock)?;
        if events.is_empty() || events.len() > MAX_QUEUE_EVENTS {
            return Err(Error::new(Code::InvalidInput, "queue batch size"));
        }
        let mut merged: BTreeMap<QueueKey, Batch> = BTreeMap::new();
        for event in events {
            check_ref(&event.queue.message)?;
            check_ref(&event.queue.neighbor)?;
            if event.batch.now_ms != clock.monotonic_ms {
                return Err(Error::new(Code::InvalidInput, "queue batch coordinate"));
            }
            if let Some(saved) = merged.get_mut(&event.queue) {
                *saved = saved.merge(event.batch)?;
            } else {
                merged.insert(event.queue, event.batch);
            }
        }
        let report = self.atomic(|s| {
            s.write_clock(&clock)?;
            let mut decisions = Vec::with_capacity(merged.len());
            for (queue, batch) in &merged {
                let decision = s.advance_queue_in_transaction(
                    &queue.message,
                    queue.kind.as_str(),
                    &queue.neighbor,
                    *batch,
                    &clock,
                )?;
                decisions.push((queue.clone(), decision));
            }
            let maintenance = s.cleanup_due(&clock)?;
            Ok(SchedulingReport {
                decisions,
                maintenance,
            })
        })?;
        self.clock = clock;
        Ok(report)
    }

    pub(super) fn advance_queue_in_transaction(
        &self,
        key: &str,
        kind: &str,
        neighbor: &str,
        batch: Batch,
        clock: &Clock,
    ) -> Result<Decision> {
        let record: Option<(String, i64)> = self
            .conn
            .query_row(
                "SELECT q.retry,m.deadline FROM queues q JOIN messages m ON m.key=q.message_key WHERE message_key=?1 AND kind=?2 AND neighbor=?3",
                params![key, kind, neighbor],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let (encoded, deadline) =
            record.ok_or_else(|| Error::new(Code::Conflict, "queue target missing"))?;
        let expired = match self.data_remaining_at(key, clock) {
            Ok(_) => false,
            Err(error) if error.code == Code::Expired => true,
            Err(error) => return Err(error),
        };
        let mut retry: RetryState = serde_json::from_str(&encoded)
            .map_err(|e| Error::source_error(Code::StoreCorrupt, "retry record", e))?;
        if retry.deadline_ms() > deadline {
            return Err(Error::new(
                Code::StoreCorrupt,
                "queue exceeds message deadline",
            ));
        }
        if expired {
            retry.constrain_deadline(batch.now_ms)?;
        }
        let (next, decision) = retry.advance(batch)?;
        self.conn.execute(
            "UPDATE queues SET retry=?4 WHERE message_key=?1 AND kind=?2 AND neighbor=?3",
            params![
                key,
                kind,
                neighbor,
                serde_json::to_string(&next).map_err(|e| Error::source_error(
                    Code::InvalidInput,
                    "retry encoding",
                    e
                ))?
            ],
        )?;
        // A pause signal for a data queue represents caller-verified downstream custody.
        if kind == "data" && batch.signal == crate::retry::Signal::Pause {
            self.conn
                .execute("UPDATE messages SET custody=1 WHERE key=?1", [key])?;
        }
        Ok(decision)
    }
}
