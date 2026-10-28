use super::*;
use crate::data::{MAX_LIFETIME_MS, MessageIdentity, PreparedCore, UtcInterval};

struct StoredData {
    core: PreparedCore,
    boot: String,
    admitted_mono: i64,
    admitted_utc: UtcInterval,
    deadline_bound: i64,
}
fn fixed<const N: usize>(row: &rusqlite::Row<'_>, column: usize) -> rusqlite::Result<[u8; N]> {
    let bytes: Vec<u8> = row.get(column)?;
    bytes.try_into().map_err(|_| rusqlite::Error::InvalidQuery)
}

impl Store {
    fn stored_data(&self, key: &str) -> Result<Option<StoredData>> {
        Ok(self.conn.query_row(
            "SELECT raw_core,activity_id,origin_id,origin_credential_ref,message_id,destination_id,destination_credential_ref,mls_group_id,mls_epoch,originated_at,lifetime,initial_hops,boot,admitted_mono,admitted_lower,admitted_upper,deadline_bound FROM message_data WHERE message_key=?1", [key], |r| {
                Ok(StoredData {
                    core: PreparedCore {
                        raw: r.get(0)?,
                        identity: MessageIdentity { activity_id: fixed(r,1)?, origin_id: fixed(r,2)?, origin_credential_ref: fixed(r,3)?, message_id: fixed(r,4)? },
                        destination_id: fixed(r,5)?, destination_credential_ref: fixed(r,6)?, mls_group_id: fixed(r,7)?,
                        mls_epoch: u64::from_be_bytes(fixed(r,8)?), originated_at_ms: r.get(9)?, lifetime_ms: r.get(10)?, initial_hops: r.get(11)?,
                    },
                    boot: r.get(12)?, admitted_mono: r.get(13)?, admitted_utc: UtcInterval { lower_ms: r.get(14)?, upper_ms: r.get(15)? }, deadline_bound: r.get(16)?,
                })
            }).optional()?)
    }

    /// Exact persisted prepared fields. Legacy rows return None; never invent a core.
    pub fn message_core(&self, key: &str) -> Result<Option<PreparedCore>> {
        self.readable()?;
        check_ref(key)?;
        Ok(self.stored_data(key)?.map(|v| v.core))
    }

    pub(super) fn validate_data_admission(
        &self,
        message: &Message,
        hops: u8,
        received_ms: Option<i64>,
    ) -> Result<()> {
        message.validate(self.clock.monotonic_ms)?;
        let bound = message
            .data
            .deadline(&self.clock, received_ms, MAX_LIFETIME_MS)?;
        if message.deadline_ms > bound || hops >= message.data.initial_hops {
            return Err(Error::new(Code::InvalidInput, "D15 admission budget"));
        }
        let id = &message.data.identity;
        let existing: Option<String> = self.conn.query_row(
            "SELECT message_key FROM message_data WHERE activity_id=?1 AND origin_id=?2 AND origin_credential_ref=?3 AND message_id=?4",
            params![id.activity_id.as_slice(),id.origin_id.as_slice(),id.origin_credential_ref.as_slice(),id.message_id.as_slice()], |r| r.get(0)).optional()?;
        if existing.is_some_and(|key| key != message.key) {
            return Err(Error::new(
                Code::Conflict,
                "D15 identity assigned to another key",
            ));
        }
        Ok(())
    }

    pub(super) fn insert_data(&self, message: &Message) -> Result<()> {
        self.write_clock(&self.clock)?;
        let core = &message.data;
        let id = &core.identity;
        let utc = self
            .clock
            .trusted_utc
            .ok_or_else(|| Error::new(Code::TimeUncertain, "D15 admission clock"))?;
        self.conn.execute("INSERT INTO message_data VALUES(?1,1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18)",
            params![message.key, core.raw, id.activity_id.as_slice(), id.origin_id.as_slice(), id.origin_credential_ref.as_slice(), id.message_id.as_slice(), core.destination_id.as_slice(), core.destination_credential_ref.as_slice(), core.mls_group_id.as_slice(), core.mls_epoch.to_be_bytes().as_slice(), core.originated_at_ms, core.lifetime_ms, core.initial_hops, self.clock.boot, self.clock.monotonic_ms, utc.lower_ms, utc.upper_ms, message.deadline_ms])?;
        Ok(())
    }

    pub(super) fn matching_data(&self, message: &Message) -> Result<()> {
        let saved = self.stored_data(&message.key)?.ok_or_else(|| {
            Error::new(Code::UnsupportedVersion, "legacy message has no D15 core")
        })?;
        if saved.core != message.data {
            return Err(Error::new(Code::Conflict, "D15 immutable core"));
        }
        let payload: Option<Vec<u8>> = self.conn.query_row(
            "SELECT payload FROM messages WHERE key=?1",
            [&message.key],
            |r| r.get(0),
        )?;
        if payload.is_some_and(|bytes| bytes != message.payload) {
            return Err(Error::new(Code::Conflict, "D15 immutable MLS message"));
        }
        Ok(())
    }

    /// Same-boot conservative remaining budget. It is not a network send permit.
    pub fn message_remaining_ms(&self, key: &str) -> Result<i64> {
        self.writable()?;
        check_ref(key)?;
        self.data_remaining_at(key, &self.clock)
    }
    pub(super) fn data_remaining_at(&self, key: &str, clock: &Clock) -> Result<i64> {
        let saved = self.stored_data(key)?.ok_or_else(|| {
            Error::new(Code::UnsupportedVersion, "legacy message output disabled")
        })?;
        clock.validate()?;
        if clock.boot != saved.boot {
            return Err(Error::new(Code::TimeUncertain, "D15 message boot"));
        }
        let upper = clock
            .utc_upper_ms()
            .ok_or_else(|| Error::new(Code::TimeUncertain, "D15 output clock"))?;
        let deadline: i64 =
            self.conn
                .query_row("SELECT deadline FROM messages WHERE key=?1", [key], |r| {
                    r.get(0)
                })?;
        let remaining = (deadline - clock.monotonic_ms).min(saved.core.not_after_ms()? - upper);
        if remaining <= 0 {
            return Err(Error::new(Code::Expired, "D15 message deadline"));
        }
        Ok(remaining)
    }

    pub(super) fn shorten_data(&self, key: &str, deadline: i64, hops: Option<u8>) -> Result<()> {
        self.conn.execute("UPDATE messages SET deadline=min(deadline,?2),hops=min(hops,coalesce(?3,hops)) WHERE key=?1",params![key,deadline,hops])?;
        let bound: i64 =
            self.conn
                .query_row("SELECT deadline FROM messages WHERE key=?1", [key], |r| {
                    r.get(0)
                })?;
        let mut stmt = self
            .conn
            .prepare("SELECT rowid,retry,kind FROM queues WHERE message_key=?1")?;
        let rows = stmt
            .query_map([key], |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        for (row, encoded, kind) in rows {
            let mut retry: RetryState = serde_json::from_str(&encoded)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "D15 retry record", e))?;
            retry.constrain_deadline(bound)?;
            let encoded = serde_json::to_string(&retry)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "D15 retry encoding", e))?;
            // Already prepared relay copies used one hop; origin copies have already done so.
            let queue_hops = hops.map(|v| {
                if kind == "data" {
                    v.saturating_sub(1)
                } else {
                    0
                }
            });
            self.conn.execute(
                "UPDATE queues SET retry=?2,hops=min(hops,coalesce(?3,hops)) WHERE rowid=?1",
                params![row, encoded, queue_hops],
            )?;
        }
        Ok(())
    }

    pub(super) fn constrain_data_clock(&self, clock: &Clock) -> Result<()> {
        let mut stmt = self
            .conn
            .prepare("SELECT message_key,originated_at,lifetime FROM message_data")?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, i64>(1)?,
                    r.get::<_, i64>(2)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        if rows.is_empty() {
            return Ok(());
        }
        let upper = clock
            .utc_upper_ms()
            .ok_or_else(|| Error::new(Code::TimeUncertain, "D15 clock source lost"))?;
        for (key, start, life) in rows {
            let end = start
                .checked_add(life)
                .ok_or_else(|| Error::new(Code::StoreCorrupt, "D15 saved expiry overflow"))?;
            let remaining = (end - upper).max(0);
            // Saturating an upper bound is safe: the persisted deadline can only shrink.
            let bound = clock.monotonic_ms.saturating_add(remaining);
            self.shorten_data(&key, bound, None)?;
        }
        Ok(())
    }

    pub(super) fn check_data_invariants(&self) -> Result<()> {
        let invalid: bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM messages m LEFT JOIN message_data d ON d.message_key=m.key WHERE (m.data_version=1)!=(d.message_key IS NOT NULL))",[],|r|r.get(0))?;
        if invalid {
            return Err(Error::new(Code::StoreCorrupt, "D15 metadata presence"));
        }
        let mut stmt=self.conn.prepare("SELECT m.key,m.deadline,m.hops,length(m.core),length(m.payload),m.origin_ref FROM messages m JOIN message_data d ON d.message_key=m.key")?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let key: String = row.get(0)?;
            let saved = self
                .stored_data(&key)?
                .ok_or_else(|| Error::new(Code::StoreCorrupt, "D15 metadata missing"))?;
            let sample = Clock {
                boot: saved.boot.clone(),
                monotonic_ms: saved.admitted_mono,
                trusted_utc: Some(saved.admitted_utc),
            };
            let bound = saved
                .core
                .deadline(&sample, None, MAX_LIFETIME_MS)
                .map_err(|e| {
                    Error::source_error(Code::StoreCorrupt, "D15 stored core bounds", e)
                })?;
            let deadline: i64 = row.get(1)?;
            let hops: u8 = row.get(2)?;
            let binding_len: u32 = row.get(3)?;
            let payload_len: Option<u32> = row.get(4)?;
            let origin: String = row.get(5)?;
            let (boot, mono, lower, upper): (String, i64, Option<i64>, Option<i64>) =
                self.conn.query_row(
                    "SELECT boot,monotonic_ms,unix_ms,unix_upper_ms FROM meta WHERE id=1",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
                )?;
            if saved.admitted_mono > mono
                || lower.is_none_or(|v| v < saved.admitted_utc.lower_ms)
                || upper.is_none_or(|v| v < saved.admitted_utc.upper_ms)
                || origin != saved.core.origin_ref()
                || saved.boot != boot
                || deadline > saved.deadline_bound
                || saved.deadline_bound > bound
                || hops > saved.core.initial_hops
                || binding_len != 32
                || payload_len.is_some_and(|v| v > crate::data::MAX_MLS_MESSAGE as u32)
            {
                return Err(Error::new(Code::StoreCorrupt, "D15 stored budget"));
            }
        }
        self.check_queue_deadlines(false)
    }
}
