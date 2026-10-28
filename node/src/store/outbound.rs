//! One durable control budget and bounded, caller-supplied scheduling round.
use super::*;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub enum OutboundEvent {
    Queue(QueueEvent),
    Control(ControlEvent),
    DataAck {
        message: String,
        neighbor: String,
    },
    ControlAck {
        object: ObjectRef,
        neighbor: ParticipantId,
    },
}
pub enum OutboundDecision {
    Queue(QueueKey, Decision),
    Control(ControlDecision),
    DataAck {
        message: String,
        neighbor: String,
        send: bool,
    },
    ControlAck {
        object: ObjectRef,
        neighbor: ParticipantId,
        send: bool,
    },
}
pub struct OutboundReport {
    /// Returned only after one successful COMMIT, never a reusable transport permit.
    pub decisions: Vec<OutboundDecision>,
    pub maintenance: MaintenanceReport,
}
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
enum Responsibility {
    Queue(QueueKey),
    Control(ObjectRef, ParticipantId),
    DataAck(String, String),
    ControlAck(ObjectRef, ParticipantId),
}
impl Responsibility {
    fn validate(&self) -> Result<()> {
        match self {
            Self::Queue(k) => {
                check_ref(&k.message)?;
                check_ref(&k.neighbor)?;
            }
            Self::DataAck(m, n) => {
                check_ref(m)?;
                check_ref(n)?;
            }
            _ => {}
        }
        Ok(())
    }
    fn data(&self) -> bool {
        matches!(
            self,
            Self::Queue(QueueKey {
                kind: QueueKind::Data,
                ..
            })
        )
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AckSlot {
    participant: ParticipantId,
    attempts: u8,
}

impl Store {
    /// Supply the complete ready set for this bounded round, merging same-coordinate inputs.
    /// Exits run first; all other control responsibilities share one persisted round-robin.
    /// Data runs separately and never consumes the control bucket. More than 128 events is
    /// rejected; the future owner must also fairly enumerate ready sets larger than one batch.
    pub fn process_outbound_batch(
        &mut self,
        clock: Clock,
        events: Vec<OutboundEvent>,
    ) -> Result<OutboundReport> {
        self.validate_clock_advance(&clock)?;
        if events.is_empty() || events.len() > scheduling::MAX_QUEUE_EVENTS {
            return Err(Error::new(Code::InvalidInput, "outbound batch size"));
        }
        let mut merged: BTreeMap<Responsibility, Option<Batch>> = BTreeMap::new();
        for e in events {
            let (key, batch) = match e {
                OutboundEvent::Queue(e) => (Responsibility::Queue(e.queue), Some(e.batch)),
                OutboundEvent::Control(e) => (
                    Responsibility::Control(e.object, e.neighbor),
                    Some(Batch {
                        now_ms: clock.monotonic_ms,
                        link: e.link,
                        signal: e.signal,
                        admission: e.admission,
                    }),
                ),
                OutboundEvent::DataAck { message, neighbor } => {
                    (Responsibility::DataAck(message, neighbor), None)
                }
                OutboundEvent::ControlAck { object, neighbor } => {
                    (Responsibility::ControlAck(object, neighbor), None)
                }
            };
            key.validate()?;
            if batch.is_some_and(|b| b.now_ms != clock.monotonic_ms) {
                return Err(Error::new(Code::InvalidInput, "outbound batch coordinate"));
            }
            if let Some(saved) = merged.get_mut(&key) {
                if let (Some(a), Some(b)) = (*saved, batch) {
                    *saved = Some(a.merge(b)?);
                }
            } else {
                merged.insert(key, batch);
            }
        }
        let report = self.atomic(|s| {
            s.write_clock(&clock)?;
            let mut exits = Vec::new();
            let mut ordinary = Vec::new();
            let mut data = Vec::new();
            for (key, batch) in merged {
                if key.data() {
                    data.push((key, batch));
                    continue;
                }
                let is_exit = if let Responsibility::Control(object, _) = &key {
                    s.conn.query_row(
                        "SELECT kind=2 FROM current_control_objects WHERE reference=?1",
                        [object.as_slice()],
                        |r| r.get::<_, bool>(0),
                    )?
                } else {
                    false
                };
                if is_exit {
                    exits.push((key, batch));
                } else {
                    ordinary.push((key, batch));
                }
            }
            let mut decisions = Vec::new();
            for (column, mut candidates) in [
                ("exit_cursor", exits),
                ("ordinary_cursor", ordinary),
                ("", data),
            ] {
                if !column.is_empty()
                    && !candidates.is_empty()
                    && let Some(cursor) = s.outbound_cursor(column)?
                {
                    let split = candidates.partition_point(|(key, _)| key <= &cursor);
                    candidates.rotate_left(split);
                }
                for (key, batch) in candidates {
                    let decision = match &key {
                        Responsibility::Queue(k) => OutboundDecision::Queue(
                            k.clone(),
                            s.advance_queue_in_transaction(
                                &k.message,
                                k.kind.as_str(),
                                &k.neighbor,
                                batch.expect("queue batch"),
                                &clock,
                            )?,
                        ),
                        Responsibility::Control(o, n) => {
                            let activity = s.outbound_activity()?;
                            OutboundDecision::Control(s.advance_control(
                                &activity,
                                *o,
                                *n,
                                batch.expect("control batch"),
                            )?)
                        }
                        Responsibility::DataAck(m, n) => OutboundDecision::DataAck {
                            message: m.clone(),
                            neighbor: n.clone(),
                            send: s.consume_data_ack_in_transaction(m, n, &clock)?,
                        },
                        Responsibility::ControlAck(o, n) => OutboundDecision::ControlAck {
                            object: *o,
                            neighbor: *n,
                            send: s.consume_control_ack_in_transaction(*o, *n, &clock)?,
                        },
                    };
                    let sent = match &decision {
                        OutboundDecision::Queue(_, d) => d.send,
                        OutboundDecision::Control(d) => d.send,
                        OutboundDecision::DataAck { send, .. }
                        | OutboundDecision::ControlAck { send, .. } => *send,
                    };
                    if sent && !column.is_empty() && !matches!(key, Responsibility::Queue(_)) {
                        let encoded = serde_json::to_string(&key).map_err(|e| {
                            Error::source_error(Code::InvalidInput, "outbound cursor encode", e)
                        })?;
                        // column is one of the two private literals above, never caller input.
                        s.conn.execute(
                            &format!("UPDATE control_output_rate SET {column}=?1 WHERE id=1"),
                            [encoded],
                        )?;
                    }
                    decisions.push(decision);
                }
            }
            let maintenance = s.cleanup_due(&clock)?;
            Ok(OutboundReport {
                decisions,
                maintenance,
            })
        })?;
        self.clock = clock;
        Ok(report)
    }
    pub(super) fn record_receipt_cursor(&self, key: &str, neighbor: &str) -> Result<()> {
        let cursor = Responsibility::Queue(QueueKey {
            message: key.into(),
            kind: QueueKind::Evidence,
            neighbor: neighbor.into(),
        });
        let encoded = serde_json::to_string(&cursor)
            .map_err(|e| Error::source_error(Code::InvalidInput, "receipt cursor encode", e))?;
        self.conn.execute(
            "UPDATE control_output_rate SET ordinary_cursor=?1 WHERE id=1",
            [encoded],
        )?;
        Ok(())
    }
    fn outbound_activity(&self) -> Result<ActivityId> {
        let raw: Vec<u8> = self.conn.query_row(
            "SELECT activity FROM current_control_activity WHERE id=1",
            [],
            |r| r.get(0),
        )?;
        raw.try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "outbound activity"))
    }
    fn outbound_cursor(&self, column: &str) -> Result<Option<Responsibility>> {
        let encoded: Option<String> = self
            .conn
            .query_row(
                &format!("SELECT {column} FROM control_output_rate WHERE id=1"),
                [],
                |r| r.get(0),
            )
            .optional()?
            .flatten();
        encoded
            .map(|v| {
                let key: Responsibility = serde_json::from_str(&v)
                    .map_err(|e| Error::source_error(Code::StoreCorrupt, "outbound cursor", e))?;
                key.validate().map_err(|e| {
                    Error::source_error(Code::StoreCorrupt, "outbound cursor fields", e)
                })?;
                if key.data() {
                    return Err(Error::new(Code::StoreCorrupt, "data in control cursor"));
                }
                Ok(key)
            })
            .transpose()
    }
    fn ack_slots(&self, key: &str) -> Result<Option<Vec<AckSlot>>> {
        let encoded: Option<String> = self.conn.query_row(
            "SELECT data_ack_budget FROM messages WHERE key=?1",
            [key],
            |r| r.get(0),
        )?;
        encoded
            .map(|v| {
                let slots: Vec<AckSlot> = serde_json::from_str(&v)
                    .map_err(|e| Error::source_error(Code::StoreCorrupt, "data ACK budget", e))?;
                let mut seen = BTreeSet::new();
                if slots.len() > 4
                    || slots
                        .iter()
                        .any(|s| s.attempts == 0 || s.attempts > 10 || !seen.insert(s.participant))
                {
                    return Err(Error::new(Code::StoreCorrupt, "data ACK slots"));
                }
                Ok(slots)
            })
            .transpose()
    }
    fn consume_data_ack_in_transaction(
        &self,
        key: &str,
        neighbor: &str,
        clock: &Clock,
    ) -> Result<bool> {
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM messages WHERE key=?1)",
            [key],
            |r| r.get(0),
        )?;
        if !exists {
            return Ok(false);
        }
        self.authorize_business_message(key, Some(neighbor), clock.monotonic_ms)?;
        self.data_remaining_at(key, clock)?;
        let stored:bool=self.conn.query_row("SELECT role!='origin' AND (payload IS NOT NULL OR role='destination') FROM messages WHERE key=?1",[key],|r|r.get(0))?;
        if !stored {
            return Ok(false);
        }
        let Some(mut slots) = self.ack_slots(key)? else {
            return Err(Error::new(
                Code::UnsupportedVersion,
                "legacy data ACK budget missing",
            ));
        };
        let local = self.control_live(&self.outbound_activity()?, clock.monotonic_ms)?;
        let credential = self.active_business_neighbor(neighbor, &local)?;
        let raw: Vec<u8> = self.conn.query_row(
            "SELECT participant FROM current_control_bindings WHERE credential=?1",
            [credential.as_slice()],
            |r| r.get(0),
        )?;
        let participant: ParticipantId = raw
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "ACK participant"))?;
        let index = slots.iter().position(|s| s.participant == participant);
        if index.is_some_and(|i| slots[i].attempts >= 10) || (index.is_none() && slots.len() == 4) {
            return Ok(false);
        }
        if !self.charge_control_output(clock.monotonic_ms, 127)? {
            return Ok(false);
        }
        match index {
            Some(i) => slots[i].attempts += 1,
            None => slots.push(AckSlot {
                participant,
                attempts: 1,
            }),
        };
        let encoded = serde_json::to_string(&slots)
            .map_err(|e| Error::source_error(Code::InvalidInput, "data ACK encode", e))?;
        self.conn.execute(
            "UPDATE messages SET data_ack_budget=?2 WHERE key=?1",
            params![key, encoded],
        )?;
        Ok(true)
    }
    pub(super) fn check_outbound_invariants(&self) -> Result<()> {
        self.outbound_cursor("exit_cursor")?;
        self.outbound_cursor("ordinary_cursor")?;
        let mut stmt = self
            .conn
            .prepare("SELECT key FROM messages WHERE data_ack_budget IS NOT NULL")?;
        let keys = stmt
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        for key in keys {
            for slot in self.ack_slots(&key)?.expect("selected non-null") {
                let known:bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM control_bindings b JOIN control_activity a ON b.activity=a.activity JOIN message_data d ON d.activity_id=a.activity WHERE d.message_key=?2 AND b.participant!=a.local_participant AND b.participant=?1 AND b.state!='pending')",params![slot.participant.as_slice(),key],|r|r.get(0))?;
                if !known {
                    return Err(Error::new(
                        Code::StoreCorrupt,
                        "data ACK neighbor association",
                    ));
                }
            }
        }
        Ok(())
    }
}
