use super::*;
use serde::{Deserialize, Serialize};

pub const MAX_QUEUE_EVENTS: usize = 128;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum QueueKind {
    Data,
    Evidence,
}
impl QueueKind {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Data => "data",
            Self::Evidence => "evidence",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
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
        let report = self.process_outbound_batch(
            clock,
            events.into_iter().map(OutboundEvent::Queue).collect(),
        )?;
        Ok(SchedulingReport {
            decisions: report
                .decisions
                .into_iter()
                .filter_map(|d| match d {
                    OutboundDecision::Queue(k, d) => Some((k, d)),
                    _ => None,
                })
                .collect(),
            maintenance: report.maintenance,
        })
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
        self.authorize_business_message(key, Some(neighbor), clock.monotonic_ms)?;
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
        let (next, mut decision) = retry.advance(batch)?;
        if kind == "evidence" && decision.send {
            let body_bytes:i64=self.conn.query_row("SELECT length(body) FROM queues WHERE message_key=?1 AND kind='evidence' AND neighbor=?2",params![key,neighbor],|r|r.get(0))?;
            // Existing prepared proof buffers may exceed the future 512-byte wire profile.
            // Charge their full conservative frame size; this does not validate a wire object.
            if !self.charge_control_output(batch.now_ms, (body_bytes + 10).max(522))? {
                decision.send = false;
                decision.reason = crate::retry::Reason::Quota;
            } else {
                self.record_receipt_cursor(key, neighbor)?;
            }
        }
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
