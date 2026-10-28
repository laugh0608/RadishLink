//! Transactional persistence. Callers must supply authenticated prepared records.
//! The public service does not expose these write primitives until security is integrated.
use crate::{
    config::Limits,
    error::{Code, Error, Result},
    model::*,
    retry::{Batch, Decision, Link, RetryState},
};
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use std::{
    fs::{self, File, OpenOptions},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt},
    path::Path,
};

mod outbound;
pub use outbound::{OutboundDecision, OutboundEvent, OutboundReport};
mod business_policy;
#[cfg(test)]
mod outbound_tests;
pub use business_policy::credential_key;
#[cfg(test)]
mod business_policy_tests;
mod control_objects;
mod control_scheduling;
mod control_state;
mod control_types;
pub use control_types::*;
#[cfg(test)]
mod control_tests;
mod data;
#[cfg(test)]
mod data_tests;
mod maintenance;
#[cfg(test)]
mod receipt_tests;
mod receipts;
#[cfg(test)]
mod reliability_tests;
mod scheduling;
#[cfg(test)]
pub(crate) mod tests;
mod transactions;
pub use maintenance::{MaintenanceReport, Usage};
pub use scheduling::{QueueEvent, QueueKey, QueueKind, SchedulingReport};

const APP_ID: i64 = 1380732491;
const DB_PAGES: i64 = 32768; // 128 MiB at the required 4096-byte page size; journal is separate.

pub struct Store {
    conn: Connection,
    _lock: File,
    limits: Limits,
    clock: Clock,
    time_uncertain: bool,
    halted: bool,
    #[cfg(test)]
    fault: Option<TestFault>,
}
#[cfg(test)]
#[derive(Clone, Copy, PartialEq, Eq)]
enum TestFault {
    BeforeCommit,
    AfterCommit,
    AfterSecurity,
    CrashBeforeCommit,
    CrashAfterCommit,
}

enum OpenMode {
    Current,
    MigrateV1,
    MigrateV2,
    MigrateV3,
    MigrateV4,
    MigrateV5,
    MigrateV6,
    #[cfg(test)]
    MigrateV1Fault(TestFault),
    #[cfg(test)]
    MigrateV2Fault(TestFault),
    #[cfg(test)]
    MigrateV3Fault(TestFault),
    #[cfg(test)]
    MigrateV4Fault(TestFault),
    #[cfg(test)]
    MigrateV5Fault(TestFault),
    #[cfg(test)]
    MigrateV6Fault(TestFault),
}

fn private_file(path: &Path) -> Result<()> {
    let m = fs::symlink_metadata(path)?;
    if !m.is_file() || m.nlink() != 1 || m.permissions().mode() & 0o777 != 0o600 {
        return Err(Error::new(
            Code::StoreUnavailable,
            "private regular file required",
        ));
    }
    Ok(())
}
fn private_directory(path: &Path) -> Result<()> {
    let m = fs::symlink_metadata(path)?;
    if !m.is_dir() || m.permissions().mode() & 0o777 != 0o700 || fs::canonicalize(path)? != path {
        return Err(Error::new(
            Code::StoreUnavailable,
            "private canonical directory required",
        ));
    }
    Ok(())
}
fn lock(directory: &Path, create: bool) -> Result<File> {
    let path = directory.join("owner.lock");
    if !create {
        private_file(&path)?;
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(create)
        .mode(0o600)
        .open(&path)?;
    file.try_lock()
        .map_err(|e| Error::source_error(Code::Busy, "store owner lock", e))?;
    Ok(file)
}
fn configure(conn: &Connection) -> Result<()> {
    conn.execute_batch("PRAGMA foreign_keys=ON; PRAGMA trusted_schema=OFF; PRAGMA temp_store=MEMORY; PRAGMA mmap_size=0; PRAGMA cache_size=-2048;")?;
    // No journal-mode conversion on reopen: changing it could modify an unsupported database.
    conn.pragma_update(None, "synchronous", "EXTRA")?;
    #[cfg(target_os = "macos")]
    conn.pragma_update(None, "fullfsync", true)?;
    conn.busy_timeout(std::time::Duration::ZERO)?;
    let mode: String = conn.pragma_query_value(None, "journal_mode", |r| r.get(0))?;
    let sync: i64 = conn.pragma_query_value(None, "synchronous", |r| r.get(0))?;
    let page_size: i64 = conn.pragma_query_value(None, "page_size", |r| r.get(0))?;
    if mode != "delete" || sync != 3 || page_size != 4096 {
        return Err(Error::new(Code::UnsupportedVersion, "sqlite configuration"));
    }
    let pages: i64 = conn.pragma_query_value(None, "page_count", |r| r.get(0))?;
    if pages > DB_PAGES {
        return Err(Error::new(Code::Quota, "database pages"));
    }
    conn.pragma_update(None, "max_page_count", DB_PAGES)?;
    Ok(())
}

impl Store {
    /// Explicitly creates a new directory. Never replaces or initializes an existing store.
    pub fn create(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        limits.validate()?;
        clock.validate()?;
        check_control_reserve(&limits)?;
        if !directory.is_absolute() {
            return Err(Error::new(Code::InvalidInput, "store directory"));
        }
        fs::DirBuilder::new().mode(0o700).create(directory)?;
        private_directory(directory)?;
        let owner = lock(directory, true)?;
        let db = directory.join("node.sqlite3");
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&db)?
            .sync_all()?;
        let conn = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_WRITE)?;
        configure(&conn)?;
        conn.execute_batch("BEGIN IMMEDIATE;")?;
        conn.execute_batch(include_str!("schema.sql"))?;
        conn.execute_batch(include_str!("migration_v2.sql"))?;
        conn.execute_batch(include_str!("migration_v3.sql"))?;
        conn.execute_batch(include_str!("migration_v4.sql"))?;
        conn.execute_batch(include_str!("migration_v5.sql"))?;
        conn.execute_batch(include_str!("migration_v6.sql"))?;
        conn.execute_batch(include_str!("migration_v7.sql"))?;
        let encoded = limits_json(&limits)?;
        conn.execute(
            "INSERT INTO meta(id,revision,boot,monotonic_ms,unix_ms,limits,unix_upper_ms) VALUES(1,0,?1,?2,?3,?4,?5)",
            params![
                clock.boot,
                clock.monotonic_ms,
                clock.utc_lower_ms(),
                encoded, clock.utc_upper_ms()
            ],
        )?;
        conn.execute_batch("COMMIT;")?;
        File::open(directory)?.sync_all()?;
        if let Some(parent) = directory.parent() {
            File::open(parent)?.sync_all()?;
        }
        Ok(Self {
            conn,
            _lock: owner,
            limits,
            clock,
            time_uncertain: false,
            halted: false,
            #[cfg(test)]
            fault: None,
        })
    }
    pub fn open(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::Current)
    }
    /// Explicit maintenance operation; ordinary open never silently migrates a store.
    pub fn migrate_v1(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::MigrateV1)
    }
    /// Explicit v2 -> current migration; never accepted for a different source version.
    pub fn migrate_v2(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::MigrateV2)
    }
    /// Explicit v3 -> current; capacity shortage leaves the entire old store intact.
    pub fn migrate_v3(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::MigrateV3)
    }
    /// Explicit v4 -> v5. Legacy message records remain non-output-capable.
    pub fn migrate_v4(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::MigrateV4)
    }
    /// Explicit v5 -> v6; existing messages acquire no inferred channel authority.
    pub fn migrate_v5(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::MigrateV5)
    }
    /// Explicit v6 -> v7; migrated messages cannot issue new data ACKs.
    pub fn migrate_v6(directory: &Path, limits: Limits, clock: Clock) -> Result<Self> {
        Self::open_version(directory, limits, clock, OpenMode::MigrateV6)
    }
    fn open_version(
        directory: &Path,
        limits: Limits,
        clock: Clock,
        mode: OpenMode,
    ) -> Result<Self> {
        let source_version = match mode {
            OpenMode::Current => None,
            OpenMode::MigrateV1 => Some(1),
            OpenMode::MigrateV2 => Some(2),
            OpenMode::MigrateV3 => Some(3),
            OpenMode::MigrateV4 => Some(4),
            OpenMode::MigrateV5 => Some(5),
            OpenMode::MigrateV6 => Some(6),
            #[cfg(test)]
            OpenMode::MigrateV1Fault(_) => Some(1),
            #[cfg(test)]
            OpenMode::MigrateV2Fault(_) => Some(2),
            #[cfg(test)]
            OpenMode::MigrateV3Fault(_) => Some(3),
            #[cfg(test)]
            OpenMode::MigrateV4Fault(_) => Some(4),
            #[cfg(test)]
            OpenMode::MigrateV5Fault(_) => Some(5),
            #[cfg(test)]
            OpenMode::MigrateV6Fault(_) => Some(6),
        };
        limits.validate()?;
        clock.validate()?;
        private_directory(directory)?;
        let owner = lock(directory, false)?;
        let db = directory.join("node.sqlite3");
        private_file(&db)?;
        for name in [
            "node.sqlite3-journal",
            "node.sqlite3-wal",
            "node.sqlite3-shm",
        ] {
            let p = directory.join(name);
            match fs::symlink_metadata(&p) {
                Ok(_) => private_file(&p)?,
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(e) => return Err(e.into()),
            }
        }
        let conn = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_WRITE)?;
        let version: i64 = conn.pragma_query_value(None, "user_version", |r| r.get(0))?;
        let app: i64 = conn.pragma_query_value(None, "application_id", |r| r.get(0))?;
        if ![1, 2, 3, 4, 5, 6, 7].contains(&version) || app != APP_ID {
            return Err(Error::new(Code::UnsupportedVersion, "store schema"));
        }
        if version < 7 && source_version.is_none() {
            return Err(Error::new(Code::MigrationRequired, "legacy store schema"));
        }
        if source_version.is_some_and(|source| version != source) {
            return Err(Error::new(Code::Conflict, "migration source version"));
        }
        configure(&conn)?;
        let check: String = conn.query_row("PRAGMA integrity_check(1)", [], |r| r.get(0))?;
        if check != "ok"
            || conn
                .prepare("PRAGMA foreign_key_check")?
                .query([])?
                .next()?
                .is_some()
        {
            return Err(Error::new(Code::StoreCorrupt, "store integrity"));
        }
        let (boot, floor, wall, stored): (String, i64, Option<i64>, String) = conn.query_row(
            "SELECT boot,monotonic_ms,unix_ms,limits FROM meta WHERE id=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )?;
        let stored_limits: Limits = serde_json::from_str(&stored)
            .map_err(|e| Error::source_error(Code::StoreCorrupt, "stored limits", e))?;
        if stored_limits != limits {
            return Err(Error::new(Code::Conflict, "store limit migration required"));
        }
        let upper: Option<i64> = if version >= 5 {
            conn.query_row("SELECT unix_upper_ms FROM meta WHERE id=1", [], |r| {
                r.get(0)
            })?
        } else {
            None
        };
        if version >= 5 {
            match (wall, upper) {
                (Some(lower_ms), Some(upper_ms)) => crate::data::UtcInterval { lower_ms, upper_ms }
                    .validate()
                    .map_err(|e| {
                        Error::source_error(Code::StoreCorrupt, "stored UTC interval", e)
                    })?,
                (None, None) => (),
                _ => {
                    return Err(Error::new(
                        Code::StoreCorrupt,
                        "stored UTC interval missing endpoint",
                    ));
                }
            }
        }
        let time_uncertain = boot != clock.boot
            || clock.monotonic_ms < floor
            || wall.is_some_and(|w| clock.utc_lower_ms().is_none_or(|n| n < w))
            || upper.is_some_and(|u| clock.utc_upper_ms().is_none_or(|n| n < u));
        let mut s = Self {
            conn,
            _lock: owner,
            limits,
            clock,
            time_uncertain,
            halted: false,
            #[cfg(test)]
            fault: match mode {
                OpenMode::MigrateV1Fault(fault) => Some(fault),
                OpenMode::MigrateV2Fault(fault) => Some(fault),
                OpenMode::MigrateV3Fault(fault) => Some(fault),
                OpenMode::MigrateV4Fault(fault) => Some(fault),
                OpenMode::MigrateV5Fault(fault) => Some(fault),
                OpenMode::MigrateV6Fault(fault) => Some(fault),
                _ => None,
            },
        };
        s.check_queue_deadlines(version < 3)?;
        if source_version.is_some() {
            s.atomic(|store| {
                // Migration expiry and responsibility checks use the same committed coordinate.
                if version == 1 {
                    store.conn.execute_batch(include_str!("migration_v2.sql"))?;
                }
                if version < 3 {
                    store.conn.execute_batch(include_str!("migration_v3.sql"))?;
                    store.migrate_receipt_deadlines()?;
                }
                if version < 4 {
                    store.conn.execute_batch(include_str!("migration_v4.sql"))?;
                }
                if version < 5 {
                    store.conn.execute_batch(include_str!("migration_v5.sql"))?;
                }
                if version < 6 {
                    store.conn.execute_batch(include_str!("migration_v6.sql"))?;
                }
                store.conn.execute_batch(include_str!("migration_v7.sql"))?;
                store.write_clock(&store.clock)?;
                store.check_queue_deadlines(false)?;
                Ok(())
            })?;
        }
        s.check_quotas()?;
        s.check_reservations()?;
        s.check_control_invariants()?;
        s.check_data_invariants()?;
        s.check_business_invariants()?;
        s.check_outbound_invariants()?;
        s.reset_control_rate_on_open()?;

        Ok(s)
    }
    pub fn is_time_uncertain(&self) -> bool {
        self.time_uncertain
    }
    pub(crate) fn current_clock(&self) -> Clock {
        self.clock.clone()
    }
    pub fn is_quarantined(&self) -> bool {
        self.halted
    }
    fn readable(&self) -> Result<()> {
        if self.halted {
            Err(Error::new(Code::OutcomeUnknown, "store requires reopen"))
        } else {
            Ok(())
        }
    }
    fn writable(&self) -> Result<()> {
        self.readable()?;
        if self.time_uncertain {
            return Err(Error::new(Code::TimeUncertain, "store clock"));
        }
        Ok(())
    }
    /// Advances only within the verified boot coordinate; never infers downtime.
    pub fn advance_clock(&mut self, clock: Clock) -> Result<()> {
        self.validate_clock_advance(&clock)?;
        self.atomic(|s| s.write_clock(&clock))?;
        self.clock = clock;
        Ok(())
    }
    fn atomic<T>(&mut self, apply: impl FnOnce(&Self) -> Result<T>) -> Result<T> {
        self.writable()?;
        self.conn.execute_batch("BEGIN IMMEDIATE;")?;
        let result = apply(self).and_then(|v| {
            let now: i64 = self.conn.query_row(
                "SELECT max(monotonic_ms,?1) FROM meta WHERE id=1",
                [self.clock.monotonic_ms],
                |r| r.get(0),
            )?;
            self.reconcile_business_policy(now)?;
            self.check_business_invariants()?;
            self.check_outbound_invariants()?;
            self.check_quotas()?;
            self.check_reservations()?;
            self.check_control_invariants()?;
            self.check_data_invariants()?;
            Ok(v)
        });
        #[cfg(test)]
        let result = result.and_then(|v| {
            if self.fault == Some(TestFault::CrashBeforeCommit) {
                std::process::exit(71);
            }
            if self.fault == Some(TestFault::BeforeCommit) {
                Err(Error::new(Code::StoreUnavailable, "test before commit"))
            } else {
                Ok(v)
            }
        });
        let value = match result {
            Ok(v) => v,
            Err(e) => {
                if let Err(rollback) = self.conn.execute_batch("ROLLBACK;") {
                    self.halted = true;
                    return Err(Error::source_error(
                        Code::OutcomeUnknown,
                        "rollback failed",
                        rollback,
                    ));
                }
                return Err(e);
            }
        };
        // Revision overflow is a failed transaction, never a wrapping generation.
        if let Err(e)=self.conn.execute("UPDATE meta SET revision=revision+1,monotonic_ms=max(monotonic_ms,?1),unix_ms=CASE WHEN ?2 IS NULL THEN unix_ms ELSE max(coalesce(unix_ms,?2),?2) END,unix_upper_ms=CASE WHEN ?3 IS NULL THEN unix_upper_ms ELSE max(coalesce(unix_upper_ms,?3),?3) END WHERE id=1 AND revision<9223372036854775807",params![self.clock.monotonic_ms,self.clock.utc_lower_ms(),self.clock.utc_upper_ms()])
            .and_then(|count|if count==1 {Ok(count)} else {Err(rusqlite::Error::InvalidQuery)}) {
            self.halted=true; return Err(Error::source_error(Code::OutcomeUnknown,"commit revision",e));
        }
        if let Err(e) = self.conn.execute_batch("COMMIT;") {
            self.halted = true;
            return Err(Error::source_error(
                Code::OutcomeUnknown,
                "commit result",
                e,
            ));
        }
        #[cfg(test)]
        {
            if self.fault == Some(TestFault::CrashAfterCommit) {
                std::process::exit(72);
            }
            if self.fault == Some(TestFault::AfterCommit) {
                self.halted = true;
                return Err(Error::new(
                    Code::OutcomeUnknown,
                    "test lost commit response",
                ));
            }
        }
        Ok(value)
    }
    fn check_quotas(&self) -> Result<()> {
        check_control_reserve(&self.limits)?;
        let checks = [
            (
                "SELECT count(*) FROM messages WHERE payload IS NOT NULL",
                self.limits.payload_count as i64,
            ),
            (
                "SELECT coalesce(sum(length(payload)),0) FROM messages",
                self.limits.payload_bytes as i64,
            ),
            (
                "SELECT count(*) FROM history",
                self.limits.history_count as i64,
            ),
            (
                "SELECT coalesce(sum(length(body)),0) FROM history",
                self.limits.history_bytes as i64,
            ),
            (
                "SELECT (SELECT count(*) FROM queues WHERE kind='evidence')+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)",
                i64::from(self.limits.control_count - CONTROL_RESERVED_RECORDS),
            ),
            (
                "SELECT (SELECT count(*)*4096 FROM queues WHERE kind='evidence')+(SELECT coalesce(sum(bytes),0) FROM control_reservations)+(SELECT count(*)*4096 FROM receipt_intents)",
                (self.limits.control_bytes - CONTROL_RESERVED_BYTES) as i64,
            ),
            (
                "SELECT (SELECT count(*) FROM messages)+(SELECT count(*) FROM actions)+(SELECT count(*) FROM queues)+(SELECT count(*) FROM action_scopes)+(SELECT count(*) FROM security_states)+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)",
                i64::from(self.limits.record_count - CONTROL_RESERVED_RECORDS),
            ),
            (
                "SELECT coalesce(sum(length(state)),0) FROM security_states",
                8 * 1024 * 1024,
            ),
        ];
        for (sql, max) in checks {
            let n: i64 = self.conn.query_row(sql, [], |r| r.get(0))?;
            if n > max {
                return Err(Error::new(Code::Quota, "store admission"));
            }
        }
        // Origin scopes must be authenticated by the future protocol layer, not self-reported peers.
        let origin_overflow:bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM messages WHERE payload IS NOT NULL GROUP BY origin_ref HAVING count(*)>512 OR sum(length(payload))>4194304)",[],|r|r.get(0))?;
        let neighbor_overflow:bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM queues JOIN messages ON messages.key=queues.message_key WHERE kind='data' GROUP BY neighbor HAVING count(*)>256 OR sum(length(payload))>2097152)",[],|r|r.get(0))?;
        if origin_overflow || neighbor_overflow {
            return Err(Error::new(Code::Quota, "origin or neighbor admission"));
        }
        Ok(())
    }
    pub fn revision(&self) -> Result<i64> {
        self.readable()?;
        Ok(self
            .conn
            .query_row("SELECT revision FROM meta WHERE id=1", [], |r| r.get(0))?)
    }
    pub fn message(&self, key: &str) -> Result<Option<MessageView>> {
        self.readable()?;
        check_ref(key)?;
        Ok(self.conn.query_row("SELECT key,state,payload IS NOT NULL,custody,EXISTS(SELECT 1 FROM queues WHERE message_key=messages.key AND kind='evidence'),source_neighbor,EXISTS(SELECT 1 FROM receipt_intents WHERE message_key=messages.key),policy_stopped FROM messages WHERE key=?1",[key],|r|Ok(MessageView{policy_stopped:r.get(7)?,key:r.get(0)?,state:r.get(1)?,payload_present:r.get(2)?,custody_observed:r.get(3)?,evidence_pending:r.get(4)?,source_neighbor:r.get(5)?,receipt_intent_pending:r.get(6)?})).optional()?)
    }
    pub fn action(
        &self,
        scope: &str,
        generation: i64,
        reference: &str,
    ) -> Result<Option<MessageView>> {
        self.readable()?;
        check_ref(scope)?;
        check_ref(reference)?;
        self.check_generation(scope, generation)?;
        let key: Option<String> = self
            .conn
            .query_row(
                "SELECT message_key FROM actions WHERE scope=?1 AND generation=?2 AND reference=?3",
                params![scope, generation, reference],
                |r| r.get(0),
            )
            .optional()?;
        key.map(|k| self.message(&k))
            .transpose()
            .map(Option::flatten)
    }
    pub fn history(&self, after: i64, limit: u32) -> Result<Vec<HistoryItem>> {
        self.readable()?;
        if after < 0 || !(1..=100).contains(&limit) {
            return Err(Error::new(Code::InvalidInput, "history page"));
        }
        let mut stmt=self.conn.prepare("SELECT sequence,message_key,body FROM history WHERE sequence>?1 AND (?3 IS NULL OR expires>?3) ORDER BY sequence LIMIT ?2")?;
        // Expired history is immediately hidden even if bounded cleanup still has a backlog.
        // Uncertain time retains the existing read-only history instead of guessing expiry.
        let wall = if self.time_uncertain {
            None
        } else {
            self.clock.utc_lower_ms()
        };
        let rows = stmt.query_map(params![after, limit, wall], |r| {
            Ok(HistoryItem {
                sequence: r.get(0)?,
                key: r.get(1)?,
                text: r.get(2)?,
            })
        })?;
        rows.collect::<std::result::Result<Vec<_>, _>>()
            .map_err(Into::into)
    }
    pub fn purge_expired_history(&mut self) -> Result<usize> {
        let wall = self
            .clock
            .utc_lower_ms()
            .ok_or_else(|| Error::new(Code::TimeUncertain, "history retention clock"))?;
        self.atomic(|s| {
            Ok(s.conn
                .execute("DELETE FROM history WHERE expires<=?1", [wall])?)
        })
    }
    fn check_generation(&self, scope: &str, generation: i64) -> Result<()> {
        let current: Option<i64> = self
            .conn
            .query_row(
                "SELECT generation FROM action_scopes WHERE scope=?1",
                [scope],
                |r| r.get(0),
            )
            .optional()?;
        if current != Some(generation) {
            return Err(Error::new(Code::Expired, "action generation"));
        }
        Ok(())
    }
    pub fn create_action_scope(&mut self, scope: &str) -> Result<()> {
        check_ref(scope)?;
        self.atomic(|s| {
            s.conn
                .execute("INSERT INTO action_scopes VALUES(?1,1)", [scope])?;
            Ok(())
        })
    }
    pub fn retire_action_generation(&mut self, scope: &str, generation: i64) -> Result<()> {
        check_ref(scope)?;
        if generation == i64::MAX {
            return Err(Error::new(Code::Quota, "action generation exhausted"));
        }
        self.atomic(|s| {
            s.check_generation(scope, generation)?;
            s.conn.execute(
                "UPDATE action_scopes SET generation=generation+1 WHERE scope=?1",
                [scope],
            )?;
            s.conn
                .execute("DELETE FROM actions WHERE scope=?1", [scope])?;
            Ok(())
        })
    }
}
fn limits_json(l: &Limits) -> Result<String> {
    // Config fields are fixed here rather than serializing secret-bearing runtime state.
    Ok(serde_json::json!({"payload_count":l.payload_count,"payload_bytes":l.payload_bytes,"history_count":l.history_count,
        "history_bytes":l.history_bytes,"control_count":l.control_count,"control_bytes":l.control_bytes,"record_count":l.record_count}).to_string())
}

fn check_control_reserve(limits: &Limits) -> Result<()> {
    if limits.control_bytes < CONTROL_RESERVED_BYTES
        || limits.control_count < CONTROL_RESERVED_RECORDS
        || limits.record_count < CONTROL_RESERVED_RECORDS
    {
        return Err(Error::new(Code::Quota, "D16 full control reservation"));
    }
    Ok(())
}
