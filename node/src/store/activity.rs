//! Explicit same-boot activity replacement. Archived facts never confer current authority.
use super::*;

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ArchivedRate {
    last_ms: i64,
    frames: i64,
    bytes: i64,
    exit_cursor: Option<String>,
    ordinary_cursor: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActivityStatus {
    pub activity: ActivityId,
    pub stopped: bool,
    pub archived: bool,
    pub policy_revision: i64,
    pub successor: Option<ActivityId>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ActivityPreflight {
    pub previous: ActivityStatus,
    pub archive_bytes: u64,
    pub archive_records: u64,
    pub free_control_bytes: u64,
    pub free_control_records: u64,
    pub free_records: u64,
    pub waiting: usize,
    pub verifying: usize,
}
#[derive(Clone, Debug)]
pub struct ActivitySwitch {
    pub previous_activity: ActivityId,
    pub expected_policy_revision: i64,
    pub activity: ActivityId,
    pub local_participant: ParticipantId,
    pub deadline_ms: i64,
}
impl Store {
    pub(super) fn current_activity_id(&self) -> Result<ActivityId> {
        self.readable()?;
        let value: Option<Vec<u8>> =
            self.conn
                .query_row("SELECT current_activity FROM meta WHERE id=1", [], |r| {
                    r.get(0)
                })?;
        value
            .ok_or_else(|| Error::new(Code::Conflict, "current activity missing"))?
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "current activity size"))
    }
    /// History/status only: this does not authorize signing, output or session reuse.
    pub fn activity_status(&self, activity: ActivityId) -> Result<Option<ActivityStatus>> {
        self.readable()?;
        let row: Option<(bool,bool,i64,Option<Vec<u8>>)> = self.conn.query_row("SELECT stopped,archived,policy_revision,successor FROM control_activity WHERE activity=?1",[activity.as_slice()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?;
        row.map(|(stopped, archived, policy_revision, successor)| {
            Ok(ActivityStatus {
                activity,
                stopped,
                archived,
                policy_revision,
                successor: successor
                    .map(|v| {
                        v.try_into()
                            .map_err(|_| Error::new(Code::StoreCorrupt, "successor size"))
                    })
                    .transpose()?,
            })
        })
        .transpose()
    }
    /// No writes or implicit stop. In-flight leases must be returned/cancelled by their workers.
    pub fn preflight_activity_switch(&self) -> Result<ActivityPreflight> {
        self.writable()?;
        let activity = self.current_activity_id()?;
        let previous = self
            .activity_status(activity)?
            .ok_or_else(|| Error::new(Code::StoreCorrupt, "current activity association"))?;
        let current = self.control_usage()?;
        let (bytes,records,all_records):(i64,i64,i64)=self.conn.query_row("SELECT
            (SELECT count(*)*4096 FROM queues WHERE kind='evidence')+(SELECT coalesce(sum(bytes),0) FROM control_reservations)+(SELECT count(*)*4096 FROM receipt_intents)+(SELECT bytes FROM activity_archive_usage),
            (SELECT count(*) FROM queues WHERE kind='evidence')+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)+(SELECT records FROM activity_archive_usage),
            (SELECT count(*) FROM messages)+(SELECT count(*) FROM actions)+(SELECT count(*) FROM queues)+(SELECT count(*) FROM action_scopes)+(SELECT count(*) FROM security_states)+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)+(SELECT records FROM activity_archive_usage)",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
        let [bytes, records, all_records] = [bytes, records, all_records].map(|value| {
            u64::try_from(value)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "negative activity usage", e))
        });
        let (bytes, records, all_records) = (bytes?, records?, all_records?);
        let usage = self.control_ingress_usage();
        Ok(ActivityPreflight {
            previous,
            archive_bytes: 4096
                + current.bindings * 1024
                + current.objects * 4096
                + current.neighbors * 512,
            archive_records: 1 + current.bindings + current.objects + current.neighbors,
            free_control_bytes: (self.limits.control_bytes - CONTROL_RESERVED_BYTES)
                .checked_sub(bytes)
                .ok_or_else(|| Error::new(Code::Quota, "control archive bytes"))?,
            free_control_records: u64::from(self.limits.control_count - CONTROL_RESERVED_RECORDS)
                .checked_sub(records)
                .ok_or_else(|| Error::new(Code::Quota, "control archive records"))?,
            free_records: u64::from(self.limits.record_count - CONTROL_RESERVED_RECORDS)
                .checked_sub(all_records)
                .ok_or_else(|| Error::new(Code::Quota, "archive records"))?,
            waiting: usage.waiting,
            verifying: usage.verifying,
        })
    }
    /// Old activity must already be durably stopped. Failure never restores its authority.
    /// Trusted caller supplies freshly prepared IDs; no cryptography or pairing is performed.
    pub fn switch_control_activity(&mut self, request: ActivitySwitch) -> Result<ActivityStatus> {
        self.writable()?;
        let now = self.clock.monotonic_ms;
        if request.deadline_ms <= now
            || request
                .deadline_ms
                .checked_sub(now)
                .is_none_or(|d| d > MAX_ACTIVITY_MS)
        {
            return Err(Error::new(Code::InvalidInput, "new activity lifetime"));
        }
        let plan = self.preflight_activity_switch()?;
        if plan.previous.activity != request.previous_activity
            || plan.previous.policy_revision != request.expected_policy_revision
            || !plan.previous.stopped
            || plan.previous.archived
        {
            return Err(Error::new(Code::Conflict, "activity switch precondition"));
        }
        if plan.waiting != 0 || plan.verifying != 0 {
            return Err(Error::new(Code::Busy, "activity verification tasks remain"));
        }
        if plan.archive_bytes > plan.free_control_bytes
            || plan.archive_records > plan.free_control_records
            || plan.archive_records > plan.free_records
        {
            return Err(Error::new(Code::Quota, "activity archive admission"));
        }
        self.atomic(|s| {
            let reused:bool=s.conn.query_row("SELECT EXISTS(SELECT 1 FROM control_activity WHERE activity=?1 OR local_participant=?2) OR EXISTS(SELECT 1 FROM control_bindings WHERE participant=?2)",params![request.activity.as_slice(),request.local_participant.as_slice()],|r|r.get(0))?;
            if reused {return Err(Error::new(Code::Conflict,"new activity identity reused"));}
            let final_rate: String=s.conn.query_row("SELECT json_object('last_ms',last_ms,'frames',frames,'bytes',bytes,'exit_cursor',exit_cursor,'ordinary_cursor',ordinary_cursor) FROM control_output_rate WHERE id=1",[],|r|r.get(0))?;
            let changed = s.conn.execute("UPDATE control_activity SET archived=1,closed_ms=?1,successor=?2,final_rate=?3 WHERE activity=?4 AND stopped=1 AND policy_revision=?5",params![now,request.activity.as_slice(),final_rate,request.previous_activity.as_slice(),request.expected_policy_revision])?;
            if changed != 1 { return Err(Error::new(Code::Conflict, "activity switch context changed")); }
            s.conn.execute("UPDATE action_scopes SET retired=1 WHERE activity=?1",[request.previous_activity.as_slice()])?;
            s.conn.execute("INSERT INTO control_activity(activity,local_participant,boot,started,deadline) VALUES(?1,?2,?3,?4,?5)",params![request.activity.as_slice(),request.local_participant.as_slice(),s.clock.boot,now,request.deadline_ms])?;
            s.conn.execute("UPDATE meta SET current_activity=?1 WHERE id=1",[request.activity.as_slice()])?;
            s.conn.execute("UPDATE control_output_rate SET last_ms=?1,frames=0,bytes=0,exit_cursor=NULL,ordinary_cursor=NULL WHERE id=1",[now])?;
            s.write_clock(&s.clock)?;
            s.activity_status(request.activity)?.ok_or_else(||Error::new(Code::StoreCorrupt,"new activity missing"))
        }).inspect(|_| {
            self.ingress=control_ingress::ControlIngress::new(now);
        })
    }
    /// Trusted owner explicitly renews a retired UI scope for the current activity.
    /// Old (scope,generation,reference) facts remain queryable internally, never replayable.
    pub fn renew_action_scope(&mut self, scope: &str, previous_generation: i64) -> Result<i64> {
        check_ref(scope)?;
        if previous_generation <= 0 || previous_generation == i64::MAX {
            return Err(Error::new(Code::InvalidInput, "action renewal generation"));
        }
        self.atomic(|s| {
            let activity = s.current_activity_id()?;
            s.control_live(&activity, s.clock.monotonic_ms)?;
            let next = previous_generation + 1;
            let changed = s.conn.execute("UPDATE action_scopes SET generation=?1,activity=?2,retired=0 WHERE scope=?3 AND generation=?4 AND retired=1",params![next,activity.as_slice(),scope,previous_generation])?;
            if changed != 1 { return Err(Error::new(Code::Conflict, "action scope not retired at expected generation")); }
            Ok(next)
        })
    }
    pub(super) fn check_activity_invariants(&self) -> Result<()> {
        let invalid:bool=self.conn.query_row("SELECT
            (SELECT count(*) FROM control_activity WHERE archived=0)!=(SELECT count(*) FROM current_control_activity) OR
            EXISTS(SELECT 1 FROM meta m WHERE m.current_activity IS NOT NULL AND NOT EXISTS(SELECT 1 FROM control_activity a WHERE a.activity=m.current_activity AND a.archived=0)) OR
            EXISTS(SELECT 1 FROM control_activity a WHERE a.archived=1 AND (a.stopped!=1 OR a.closed_ms>(SELECT monotonic_ms FROM meta WHERE id=1) OR NOT EXISTS(SELECT 1 FROM control_activity n WHERE n.activity=a.successor AND n.started=a.closed_ms AND n.id>a.id))) OR
            EXISTS(SELECT 1 FROM control_activity a WHERE a.boot!=(SELECT boot FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM control_objects o JOIN control_bindings i ON i.credential=o.issuer JOIN control_bindings t ON t.credential=o.target WHERE o.activity!=i.activity OR o.activity!=t.activity) OR
            EXISTS(SELECT 1 FROM control_neighbors n JOIN control_objects o ON o.reference=n.object WHERE n.activity!=o.activity OR NOT EXISTS(SELECT 1 FROM control_bindings b WHERE b.activity=n.activity AND b.participant=n.participant AND b.state!='pending')) OR
            EXISTS(SELECT 1 FROM control_activity a WHERE a.started>(SELECT monotonic_ms FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM control_activity a JOIN control_bindings b ON b.credential=a.exit_credential WHERE b.activity!=a.activity OR b.participant!=a.local_participant OR b.state NOT IN ('retiring','blocked')) OR
            EXISTS(SELECT 1 FROM control_activity a WHERE a.exit_credential IS NOT NULL AND NOT EXISTS(SELECT 1 FROM control_bindings b WHERE b.credential=a.exit_credential)) OR
            EXISTS(SELECT 1 FROM control_bindings b WHERE b.state='retiring' AND NOT EXISTS(SELECT 1 FROM control_activity a WHERE a.activity=b.activity AND a.exit_credential=b.credential)) OR
            EXISTS(SELECT 1 FROM control_bindings b WHERE b.generation!=(SELECT count(*) FROM control_bindings p WHERE p.activity=b.activity AND p.participant=b.participant AND p.generation<=b.generation)) OR
            EXISTS(SELECT 1 FROM control_objects o JOIN control_activity a ON a.activity=o.activity JOIN control_bindings i ON i.credential=o.issuer JOIN control_bindings t ON t.credential=o.target WHERE o.accepted<a.started OR o.accepted>coalesce(a.closed_ms,(SELECT monotonic_ms FROM meta WHERE id=1)) OR (o.kind=2 AND i.state!='blocked') OR i.state='pending' OR t.state='pending' OR o.reporter!=i.participant OR (o.kind=3 AND i.participant=t.participant)) OR
            EXISTS(SELECT 1 FROM control_neighbors n JOIN control_objects o ON o.reference=n.object JOIN control_activity a ON a.activity=n.activity WHERE n.start<o.accepted OR n.start>coalesce(a.closed_ms,(SELECT monotonic_ms FROM meta WHERE id=1)) OR n.last_ms>coalesce(a.closed_ms,(SELECT monotonic_ms FROM meta WHERE id=1)) OR n.participant=a.local_participant) OR
            EXISTS(SELECT 1 FROM control_activity a WHERE (SELECT count(DISTINCT participant) FROM control_bindings b WHERE b.activity=a.activity)>5 OR (SELECT count(*) FROM control_bindings b WHERE b.activity=a.activity AND b.state='pending')>5 OR (SELECT count(*) FROM control_bindings b WHERE b.activity=a.activity AND b.state!='pending')>20 OR (SELECT count(*) FROM control_objects o WHERE o.activity=a.activity AND o.kind=2)>20 OR (SELECT count(*) FROM control_objects o WHERE o.activity=a.activity AND o.kind=3)>80) OR
            EXISTS(SELECT 1 FROM control_neighbors GROUP BY object HAVING count(*)>4) OR
            EXISTS(SELECT 1 FROM actions j JOIN action_scopes s ON s.scope=j.scope LEFT JOIN message_data d ON d.message_key=j.message_key WHERE j.generation>s.generation OR (j.generation=s.generation AND s.retired=0 AND (d.activity_id IS NULL OR d.activity_id IS NOT s.activity))) OR
            EXISTS(SELECT 1 FROM security_states s WHERE length(s.activity)>0 AND NOT EXISTS(SELECT 1 FROM control_activity a WHERE a.activity=s.activity)) OR
            EXISTS(SELECT 1 FROM action_scopes s WHERE s.retired=0 AND (s.activity IS NULL OR s.activity IS NOT (SELECT current_activity FROM meta WHERE id=1))) OR
            EXISTS(SELECT 1 FROM control_activity a WHERE (SELECT count(*) FROM control_bindings b WHERE b.activity=a.activity)>25 OR (SELECT count(*) FROM control_objects o WHERE o.activity=a.activity)>100 OR (SELECT count(*) FROM control_neighbors n WHERE n.activity=a.activity)>400)",[],|r|r.get(0))?;
        if invalid {
            return Err(Error::new(Code::StoreCorrupt, "activity association"));
        }
        let mut stmt = self
            .conn
            .prepare("SELECT closed_ms,final_rate FROM control_activity WHERE archived=1")?;
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let closed: i64 = row.get(0)?;
            let encoded: String = row.get(1)?;
            let rate: ArchivedRate = serde_json::from_str(&encoded)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "archived rate summary", e))?;
            if !(0..=closed).contains(&rate.last_ms)
                || !(0..=4000).contains(&rate.frames)
                || !(0..=8192000).contains(&rate.bytes)
                || [rate.exit_cursor, rate.ordinary_cursor]
                    .iter()
                    .flatten()
                    .any(|v| v.len() > 512)
            {
                return Err(Error::new(Code::StoreCorrupt, "archived rate bounds"));
            }
        }
        Ok(())
    }
}
