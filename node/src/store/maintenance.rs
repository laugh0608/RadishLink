use super::*;

/// Work per transaction, so maintenance cannot monopolize the state owner.
pub const MAINTENANCE_BATCH: i64 = 256;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MaintenanceReport {
    pub expired_payloads: usize,
    pub expired_evidence: usize,
    pub expired_receipt_intents: usize,
    pub deleted_history: usize,
    pub stopped_evidence: usize,
    pub stopped_receipt_intents: usize,
    pub more_due: bool,
    pub history_time_available: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Usage {
    pub payload_count: u64,
    pub payload_bytes: u64,
    pub history_count: u64,
    pub history_bytes: u64,
    pub evidence_count: u64,
    pub evidence_bytes: u64,
    pub reserved_control_count: u64,
    pub reserved_control_bytes: u64,
    /// Logical business plus D16 records; D15 metadata belongs to its message.
    /// Unused reserved slots are not physical records.
    pub records: u64,
    /// Fixed D16 reservation and actual usage, separate from business proof reservations.
    pub security_control: ControlUsage,
    pub archived_control_bytes: u64,
    pub archived_control_records: u64,
    /// Only the main SQLite file; excludes journal, filesystem and process memory.
    pub database_bytes: u64,
}

impl Store {
    pub(super) fn check_reservations(&self) -> Result<()> {
        let invalid: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM messages m LEFT JOIN control_reservations r ON r.message_key=m.key
             WHERE (m.role='relay' AND m.state='stored') != (r.message_key IS NOT NULL))",
            [], |r| r.get(0))?;
        if invalid {
            return Err(Error::new(
                Code::StoreCorrupt,
                "relay reservation invariant",
            ));
        }
        let invalid: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM receipt_intents i JOIN messages m ON m.key=i.message_key WHERE m.role!='destination' OR m.state NOT IN ('committed','delivered') OR EXISTS(SELECT 1 FROM queues q WHERE q.message_key=m.key AND q.kind='evidence')) OR EXISTS(SELECT 1 FROM messages m WHERE m.role='destination' AND m.policy_stopped=0 AND m.deadline>(SELECT monotonic_ms FROM meta WHERE id=1) AND NOT EXISTS(SELECT 1 FROM receipt_intents i WHERE i.message_key=m.key) AND NOT EXISTS(SELECT 1 FROM queues q WHERE q.message_key=m.key AND q.kind='evidence'))",
            [], |r| r.get(0))?;
        if invalid {
            return Err(Error::new(
                Code::StoreCorrupt,
                "destination receipt responsibility",
            ));
        }
        Ok(())
    }

    pub fn usage(&self) -> Result<Usage> {
        self.readable()?;
        let scalar = |sql: &str| -> Result<u64> {
            let value: i64 = self.conn.query_row(sql, [], |r| r.get(0))?;
            u64::try_from(value)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "negative usage", e))
        };
        let security_control = self.control_usage()?;
        Ok(Usage {
            payload_count: scalar("SELECT count(*) FROM messages WHERE payload IS NOT NULL")?,
            payload_bytes: scalar("SELECT coalesce(sum(length(payload)),0) FROM messages")?,
            history_count: scalar("SELECT count(*) FROM history")?,
            history_bytes: scalar("SELECT coalesce(sum(length(body)),0) FROM history")?,
            evidence_count: scalar("SELECT count(*) FROM queues WHERE kind='evidence'")?,
            evidence_bytes: scalar(
                "SELECT coalesce(sum(length(body)),0) FROM queues WHERE kind='evidence'",
            )?,
            reserved_control_count: scalar(
                "SELECT (SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)",
            )?,
            reserved_control_bytes: scalar(
                "SELECT (SELECT coalesce(sum(bytes),0) FROM control_reservations)+(SELECT count(*)*4096 FROM receipt_intents)",
            )?,
            records: scalar(
                "SELECT (SELECT count(*) FROM messages)+(SELECT count(*) FROM actions)+(SELECT count(*) FROM queues)+(SELECT count(*) FROM action_scopes)+(SELECT count(*) FROM security_states)+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)",
            )? + security_control.used_records
                + scalar("SELECT records FROM activity_archive_usage")?,
            archived_control_bytes: scalar("SELECT bytes FROM activity_archive_usage")?,
            archived_control_records: scalar("SELECT records FROM activity_archive_usage")?,
            security_control,
            database_bytes: scalar(
                "SELECT page_count*page_size FROM pragma_page_count(),pragma_page_size()",
            )?,
        })
    }

    pub(super) fn validate_clock_advance(&mut self, clock: &Clock) -> Result<()> {
        self.writable()?;
        if let Err(error) = clock.validate() {
            self.time_uncertain = true;
            return Err(error);
        }
        if clock.boot != self.clock.boot
            || clock.monotonic_ms < self.clock.monotonic_ms
            || self
                .clock
                .utc_lower_ms()
                .is_some_and(|w| clock.utc_lower_ms().is_none_or(|n| n < w))
            || self
                .clock
                .utc_upper_ms()
                .is_some_and(|u| clock.utc_upper_ms().is_none_or(|n| n < u))
        {
            self.time_uncertain = true;
            return Err(Error::new(Code::TimeUncertain, "clock regression"));
        }
        Ok(())
    }

    pub(super) fn write_clock(&self, clock: &Clock) -> Result<()> {
        self.conn.execute(
            "UPDATE meta SET monotonic_ms=?1,unix_ms=?2,unix_upper_ms=?3 WHERE id=1",
            params![
                clock.monotonic_ms,
                clock.utc_lower_ms(),
                clock.utc_upper_ms()
            ],
        )?;
        self.constrain_data_clock(clock)?;
        self.reconcile_business_policy(clock.monotonic_ms)
    }

    /// Caller supplies an already trusted boot/time coordinate, never a UI or peer timestamp.
    /// Clock advancement and bounded cleanup commit together, including on failure/reopen.
    pub fn maintain(&mut self, clock: Clock) -> Result<MaintenanceReport> {
        self.validate_clock_advance(&clock)?;
        let report = self.atomic(|s| {
            s.write_clock(&clock)?;
            s.cleanup_due(&clock)
        })?;
        self.clock = clock;
        Ok(report)
    }

    pub(super) fn cleanup_due(&self, clock: &Clock) -> Result<MaintenanceReport> {
        let mut statement = self.conn.prepare("SELECT key FROM messages WHERE payload IS NOT NULL AND deadline<=?1 ORDER BY deadline,key LIMIT ?2")?;
        let keys: Vec<String> = statement
            .query_map(params![clock.monotonic_ms, MAINTENANCE_BATCH], |r| r.get(0))?
            .collect::<std::result::Result<_, _>>()?;
        for key in &keys {
            self.conn.execute(
                "UPDATE messages SET state=CASE WHEN role='destination' THEN 'delivered' ELSE 'expired' END,payload=NULL WHERE key=?1",
                [key],
            )?;
            self.conn.execute(
                "DELETE FROM queues WHERE message_key=?1 AND kind='data'",
                [key],
            )?;
            self.conn.execute(
                "DELETE FROM control_reservations WHERE message_key=?1",
                [key],
            )?;
        }
        let expired_evidence = self.conn.execute(
            "DELETE FROM queues WHERE rowid IN (SELECT q.rowid FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.kind='evidence' AND m.deadline<=?1 ORDER BY m.deadline,m.key,q.neighbor LIMIT ?2)",
            params![clock.monotonic_ms, MAINTENANCE_BATCH])?;
        let expired_receipt_intents = self.conn.execute(
            "DELETE FROM receipt_intents WHERE message_key IN (SELECT i.message_key FROM receipt_intents i JOIN messages m ON m.key=i.message_key WHERE m.deadline<=?1 ORDER BY m.deadline,m.key LIMIT ?2)",
            params![clock.monotonic_ms, MAINTENANCE_BATCH])?;
        let deleted_history = match clock.utc_lower_ms() {
            Some(wall) => self.conn.execute("DELETE FROM history WHERE sequence IN (SELECT sequence FROM history WHERE expires<=?1 ORDER BY expires,sequence LIMIT ?2)", params![wall, MAINTENANCE_BATCH])?,
            None => 0,
        };
        let stopped_evidence=self.conn.execute("DELETE FROM queues WHERE rowid IN (SELECT q.rowid FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.kind='evidence' AND m.policy_stopped=1 AND m.policy_revision IS NOT NULL ORDER BY m.key,q.neighbor LIMIT ?1)",[MAINTENANCE_BATCH])?;
        let stopped_receipt_intents=self.conn.execute("DELETE FROM receipt_intents WHERE message_key IN (SELECT i.message_key FROM receipt_intents i JOIN messages m ON m.key=i.message_key WHERE m.policy_stopped=1 AND m.policy_revision IS NOT NULL ORDER BY m.key LIMIT ?1)",[MAINTENANCE_BATCH])?;
        let stopped_due:bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.kind='evidence' AND m.policy_stopped=1 AND m.policy_revision IS NOT NULL) OR EXISTS(SELECT 1 FROM receipt_intents i JOIN messages m ON m.key=i.message_key WHERE m.policy_stopped=1 AND m.policy_revision IS NOT NULL)",[],|r|r.get(0))?;
        let more_due: bool = self.conn.query_row("SELECT EXISTS(SELECT 1 FROM messages WHERE payload IS NOT NULL AND deadline<=?1) OR EXISTS(SELECT 1 FROM history WHERE expires<=?2) OR EXISTS(SELECT 1 FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.kind='evidence' AND m.deadline<=?1) OR EXISTS(SELECT 1 FROM receipt_intents i JOIN messages m ON m.key=i.message_key WHERE m.deadline<=?1)", params![clock.monotonic_ms, clock.utc_lower_ms()], |r| r.get(0))?;
        Ok(MaintenanceReport {
            expired_payloads: keys.len(),
            expired_evidence,
            expired_receipt_intents,
            deleted_history,
            stopped_evidence,
            stopped_receipt_intents,
            more_due: more_due || stopped_due,
            history_time_available: clock.utc_lower_ms().is_some(),
        })
    }
}
