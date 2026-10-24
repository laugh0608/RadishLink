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

mod maintenance;
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
    #[cfg(test)]
    MigrateV1Fault(TestFault),
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
        let encoded = limits_json(&limits)?;
        conn.execute(
            "INSERT INTO meta VALUES(1,0,?1,?2,?3,?4)",
            params![
                clock.boot,
                clock.monotonic_ms,
                clock.trusted_unix_ms,
                encoded
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
    fn open_version(
        directory: &Path,
        limits: Limits,
        clock: Clock,
        mode: OpenMode,
    ) -> Result<Self> {
        let migrate = !matches!(mode, OpenMode::Current);
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
        if ![1, 2].contains(&version) || app != APP_ID {
            return Err(Error::new(Code::UnsupportedVersion, "store schema"));
        }
        if version == 1 && !migrate {
            return Err(Error::new(Code::MigrationRequired, "store schema v1"));
        }
        if version != 1 && migrate {
            return Err(Error::new(Code::Conflict, "migration source must be v1"));
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
        let time_uncertain = boot != clock.boot
            || clock.monotonic_ms < floor
            || wall.is_some_and(|w| clock.trusted_unix_ms.is_none_or(|n| n < w));
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
                _ => None,
            },
        };
        let mut stmt = s.conn.prepare("SELECT retry FROM queues")?;
        for row in stmt.query_map([], |r| r.get::<_, String>(0))? {
            let state: RetryState = serde_json::from_str(&row?)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "retry record", e))?;
            state.validate()?;
        }
        drop(stmt);
        if migrate {
            s.atomic(|store| {
                store.conn.execute_batch(include_str!("migration_v2.sql"))?;
                Ok(())
            })?;
        }
        s.check_quotas()?;
        s.check_reservations()?;

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
            self.check_quotas()?;
            self.check_reservations()?;
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
        if let Err(e)=self.conn.execute("UPDATE meta SET revision=revision+1,monotonic_ms=max(monotonic_ms,?1),unix_ms=CASE WHEN ?2 IS NULL THEN unix_ms ELSE max(coalesce(unix_ms,?2),?2) END WHERE id=1 AND revision<9223372036854775807",params![self.clock.monotonic_ms,self.clock.trusted_unix_ms])
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
                "SELECT (SELECT count(*) FROM queues WHERE kind='evidence')+(SELECT count(*) FROM control_reservations)",
                self.limits.control_count as i64,
            ),
            (
                "SELECT (SELECT coalesce(sum(length(body)),0) FROM queues WHERE kind='evidence')+(SELECT coalesce(sum(bytes),0) FROM control_reservations)",
                self.limits.control_bytes as i64,
            ),
            (
                "SELECT (SELECT count(*) FROM messages)+(SELECT count(*) FROM actions)+(SELECT count(*) FROM queues)+(SELECT count(*) FROM action_scopes)+(SELECT count(*) FROM security_states)+(SELECT count(*) FROM control_reservations)",
                self.limits.record_count as i64,
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
        Ok(self.conn.query_row("SELECT key,state,payload IS NOT NULL,custody,EXISTS(SELECT 1 FROM queues WHERE message_key=messages.key AND kind='evidence'),source_neighbor FROM messages WHERE key=?1",[key],|r|Ok(MessageView{key:r.get(0)?,state:r.get(1)?,payload_present:r.get(2)?,custody_observed:r.get(3)?,evidence_pending:r.get(4)?,source_neighbor:r.get(5)?})).optional()?)
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
            self.clock.trusted_unix_ms
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
            .trusted_unix_ms
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
