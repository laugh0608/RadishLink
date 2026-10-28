use super::control_types::*;
use super::*;

struct ActivityRecord {
    activity: Vec<u8>,
    local: Vec<u8>,
    boot: String,
    deadline: i64,
    stopped: bool,
}

impl Store {
    /// Owner-confirmed local activity creation. This does not generate IDs or establish trust.
    /// A store retains its activity marker; restarting/stopping cannot reset this activity.
    pub fn start_control_activity(
        &mut self,
        activity: ActivityId,
        local: ParticipantId,
        deadline: i64,
    ) -> Result<()> {
        let now = self.clock.monotonic_ms;
        if deadline <= now
            || deadline
                .checked_sub(now)
                .is_none_or(|d| d > MAX_ACTIVITY_MS)
        {
            return Err(Error::new(Code::InvalidInput, "control activity lifetime"));
        }
        self.atomic(|s| {
            let exists: bool = s.conn.query_row("SELECT EXISTS(SELECT 1 FROM current_control_activity)", [], |r|r.get(0))?;
            if exists { return Err(Error::new(Code::Conflict,"activity already assigned; no restart")); }
            s.write_clock(&s.clock)?;
            s.conn.execute("INSERT INTO control_activity(id,activity,local_participant,boot,started,deadline) VALUES(1,?1,?2,?3,?4,?5)",params![activity.as_slice(),local.as_slice(),s.clock.boot,now,deadline])?;
            s.conn.execute("UPDATE meta SET current_activity=?1 WHERE id=1",[activity.as_slice()])?;
            s.conn.execute("INSERT INTO control_output_rate(id,last_ms,frames,bytes) VALUES(1,?1,0,0)",[now])?;
            Ok(())
        })
    }
    pub(super) fn control_live(&self, activity: &ActivityId, now: i64) -> Result<ParticipantId> {
        self.writable()?;
        let row = self.conn.query_row(
            "SELECT activity,local_participant,boot,deadline,stopped FROM current_control_activity WHERE id=1",
            [], |r| Ok(ActivityRecord {activity:r.get(0)?,local:r.get(1)?,boot:r.get(2)?,deadline:r.get(3)?,stopped:r.get(4)?})
        ).optional()?;
        let ActivityRecord {
            activity: saved,
            local,
            boot,
            deadline,
            stopped,
        } = row.ok_or_else(|| Error::new(Code::Conflict, "control activity missing"))?;
        if saved != activity || stopped {
            return Err(Error::new(Code::Conflict, "control activity unavailable"));
        }
        if boot != self.clock.boot {
            return Err(Error::new(Code::TimeUncertain, "control activity boot"));
        }
        if now >= deadline {
            return Err(Error::new(Code::Expired, "control activity deadline"));
        }
        local
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "local participant size"))
    }
    /// Deadline can only decrease; stopping retains all markers and business history.
    pub fn shorten_control_activity(&mut self, activity: ActivityId, deadline: i64) -> Result<()> {
        self.policy_atomic(|s| {
            s.control_live(&activity, s.clock.monotonic_ms)?;
            let (start, old): (i64, i64) = s.conn.query_row(
                "SELECT started,deadline FROM current_control_activity WHERE id=1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )?;
            if deadline <= start || deadline > old {
                return Err(Error::new(
                    Code::InvalidInput,
                    "activity deadline extension",
                ));
            }
            s.conn.execute(
                "UPDATE control_activity SET deadline=?1 WHERE activity=(SELECT current_activity FROM meta WHERE id=1)",
                [deadline],
            )?;
            s.business_policy_changed()
        })
    }
    pub fn stop_control_activity(&mut self, activity: ActivityId) -> Result<()> {
        self.policy_atomic(|s| {
            let count = s.conn.execute(
                "UPDATE control_activity SET stopped=1 WHERE activity=(SELECT current_activity FROM meta WHERE id=1) AND activity=?1",
                [activity.as_slice()],
            )?;
            if count != 1 {
                return Err(Error::new(Code::Conflict, "control activity missing"));
            }
            s.business_policy_changed()
        })
    }
    /// Trusted local pairing preparation only; never allocate a record for network strangers.
    pub fn stage_control_binding(
        &mut self,
        activity: ActivityId,
        binding: ControlBinding,
    ) -> Result<()> {
        if !(1..=4).contains(&binding.generation)
            || binding.body.is_empty()
            || binding.body.len() > 160
        {
            return Err(Error::new(Code::InvalidInput, "control binding bounds"));
        }
        self.atomic(|s| {
            s.control_live(&activity,s.clock.monotonic_ms)?;
            s.reject_local_retirement()?;
            let prior:Option<(Vec<u8>,u32,Vec<u8>)>=s.conn.query_row("SELECT participant,generation,body FROM current_control_bindings WHERE credential=?1",[binding.credential.as_slice()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
            if let Some((p,g,b))=prior {
                if p==binding.participant && g==binding.generation && b==binding.body { return Ok(()); }
                return Err(Error::new(Code::Conflict,"credential binding mismatch"));
            }
            let reused:bool=s.conn.query_row("SELECT EXISTS(SELECT 1 FROM control_bindings WHERE activity!=?1 AND (participant=?2 OR credential=?3)) OR EXISTS(SELECT 1 FROM control_activity WHERE activity!=?1 AND local_participant=?2)", params![activity.as_slice(),binding.participant.as_slice(),binding.credential.as_slice()],|r|r.get(0))?;
            if reused { return Err(Error::new(Code::Conflict,"identity belongs to an earlier activity")); }
            let latest:i64=s.conn.query_row("SELECT coalesce(max(generation),0) FROM current_control_bindings WHERE participant=?1 AND state!='pending'",[binding.participant.as_slice()],|r|r.get(0))?;
            if i64::from(binding.generation)!=latest+1 {
                return Err(Error::new(Code::Conflict,"nonconsecutive credential generation"));
            }
            let pending:bool=s.conn.query_row("SELECT EXISTS(SELECT 1 FROM current_control_bindings WHERE participant=?1 AND state='pending')",[binding.participant.as_slice()],|r|r.get(0))?;
            if pending { return Err(Error::new(Code::Conflict,"pending binding already assigned")); }
            s.conn.execute("INSERT INTO control_bindings(activity,credential,participant,generation,body,state) VALUES((SELECT current_activity FROM meta WHERE id=1),?1,?2,?3,?4,'pending')",params![binding.credential.as_slice(),binding.participant.as_slice(),binding.generation,binding.body])?;
            Ok(())
        })
    }
    /// Caller supplies independently obtained owner confirmation and verified BindingV1.
    pub fn activate_control_binding(
        &mut self,
        activity: ActivityId,
        credential: CredentialRef,
        expected_body: &[u8],
    ) -> Result<()> {
        self.policy_atomic(|s| {
            s.control_live(&activity,s.clock.monotonic_ms)?;
            s.reject_local_retirement()?;
            let (p,g,b,state):(Vec<u8>,i64,Vec<u8>,String)=s.conn.query_row("SELECT participant,generation,body,state FROM current_control_bindings WHERE credential=?1",[credential.as_slice()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?))).optional()?.ok_or_else(||Error::new(Code::Conflict,"current binding missing"))?;
            if b!=expected_body { return Err(Error::new(Code::Conflict,"pairing confirmation binding")); }
            if state=="active" { return Ok(()); }
            if state!="pending" { return Err(Error::new(Code::Conflict,"binding cannot be reactivated")); }
            let latest:i64=s.conn.query_row("SELECT coalesce(max(generation),0) FROM current_control_bindings WHERE participant=?1 AND state!='pending'",[p.as_slice()],|r|r.get(0))?;
            if g!=latest+1 { return Err(Error::new(Code::Conflict,"credential activation order")); }
            s.conn.execute("UPDATE control_bindings SET state='blocked' WHERE activity=(SELECT current_activity FROM meta WHERE id=1) AND participant=?1 AND state='active'",[p.as_slice()])?;
            s.conn.execute("UPDATE control_bindings SET state='active' WHERE activity=(SELECT current_activity FROM meta WHERE id=1) AND credential=?1",[credential.as_slice()])?;
            s.business_policy_changed()
        })
    }
    /// Owner policy does not require a free report/object slot or an output budget.
    pub fn block_control_binding(
        &mut self,
        activity: ActivityId,
        credential: CredentialRef,
    ) -> Result<()> {
        self.policy_atomic(|s| {
            s.control_live(&activity,s.clock.monotonic_ms)?;
            let changed=s.conn.execute("UPDATE control_bindings SET state='blocked' WHERE activity=(SELECT current_activity FROM meta WHERE id=1) AND credential=?1 AND state!='pending'",[credential.as_slice()])?;
            if changed!=1 { return Err(Error::new(Code::Conflict,"unknown verified credential")); }
            s.business_policy_changed()
        })
    }
    pub fn control_binding_state(&self, credential: CredentialRef) -> Result<Option<BindingState>> {
        self.readable()?;
        let state: Option<String> = self
            .conn
            .query_row(
                "SELECT state FROM current_control_bindings WHERE credential=?1",
                [credential.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        state.map(|s| BindingState::parse(&s)).transpose()
    }
    pub(super) fn reject_local_retirement(&self) -> Result<()> {
        let stopped:bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM current_control_bindings b JOIN current_control_activity a ON b.participant=a.local_participant WHERE b.state='retiring') OR EXISTS(SELECT 1 FROM current_control_activity WHERE exit_credential IS NOT NULL)",[],|r|r.get(0))?;
        if stopped {
            return Err(Error::new(Code::Conflict, "local exit is irreversible"));
        }
        Ok(())
    }
    pub(super) fn control_binding(
        &self,
        credential: &CredentialRef,
        participant: &ParticipantId,
    ) -> Result<BindingState> {
        let state: Option<String> = self
            .conn
            .query_row(
                "SELECT state FROM current_control_bindings WHERE credential=?1 AND participant=?2",
                params![credential.as_slice(), participant.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        BindingState::parse(
            &state.ok_or_else(|| Error::new(Code::Conflict, "control identity not bound"))?,
        )
    }
    pub(super) fn participant_active(&self, participant: &ParticipantId) -> Result<bool> {
        Ok(self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM current_control_bindings WHERE participant=?1 AND state='active')",
            [participant.as_slice()],
            |r| r.get(0),
        )?)
    }
    pub fn control_usage(&self) -> Result<ControlUsage> {
        self.readable()?;
        let (bindings,objects,neighbors,aux):(u32,u32,u32,u32)=self.conn.query_row("SELECT (SELECT count(*) FROM current_control_bindings),(SELECT count(*) FROM current_control_objects),(SELECT count(*) FROM current_control_neighbors),(SELECT count(*) FROM current_control_activity)+(SELECT count(*) FROM control_output_rate)",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?)))?;
        let (bindings, objects, neighbors, aux) = (
            u64::from(bindings),
            u64::from(objects),
            u64::from(neighbors),
            u64::from(aux),
        );
        Ok(ControlUsage {
            reserved_bytes: CONTROL_RESERVED_BYTES,
            reserved_records: CONTROL_RESERVED_RECORDS,
            used_bytes: bindings * 1024 + objects * 4096 + neighbors * 512 + aux * 4096,
            used_records: bindings + objects + neighbors + aux,
            bindings,
            objects,
            neighbors,
        })
    }
    pub(super) fn check_control_invariants(&self) -> Result<()> {
        let u = self.control_usage()?;
        if u.bindings > 25
            || u.objects > 100
            || u.neighbors > 400
            || u.used_records > u64::from(CONTROL_RESERVED_RECORDS)
            || u.used_bytes > CONTROL_RESERVED_BYTES
        {
            return Err(Error::new(Code::Quota, "D16 reserved region"));
        }
        let exceeded: bool = self.conn.query_row(
            "SELECT
            (SELECT count(DISTINCT participant) FROM current_control_bindings)>5 OR
            (SELECT count(*) FROM current_control_bindings WHERE state='pending')>5 OR
            (SELECT count(*) FROM current_control_bindings WHERE state!='pending')>20 OR
            (SELECT count(*) FROM current_control_objects WHERE kind=2)>20 OR
            (SELECT count(*) FROM current_control_objects WHERE kind=3)>80 OR
            EXISTS(SELECT 1 FROM current_control_neighbors GROUP BY object HAVING count(*)>4)",
            [],
            |r| r.get(0),
        )?;
        if exceeded {
            return Err(Error::new(Code::Quota, "D16 slot limit"));
        }
        let invalid:bool=self.conn.query_row("SELECT
            ((SELECT count(*) FROM current_control_activity)!=(SELECT count(*) FROM control_output_rate)) OR
            (EXISTS(SELECT 1 FROM current_control_bindings) AND NOT EXISTS(SELECT 1 FROM current_control_activity)) OR
            EXISTS(SELECT 1 FROM current_control_activity a JOIN meta m ON m.id=1 WHERE a.boot!=m.boot OR a.started>m.monotonic_ms) OR
            EXISTS(SELECT 1 FROM control_output_rate WHERE last_ms>(SELECT monotonic_ms FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM current_control_activity a LEFT JOIN current_control_bindings b ON b.credential=a.exit_credential WHERE a.exit_credential IS NOT NULL AND (b.credential IS NULL OR b.participant!=a.local_participant OR b.state NOT IN ('retiring','blocked'))) OR
            EXISTS(SELECT 1 FROM current_control_bindings b WHERE b.state='retiring' AND NOT EXISTS(SELECT 1 FROM current_control_activity a WHERE a.exit_credential=b.credential)) OR
            EXISTS(SELECT 1 FROM current_control_objects o WHERE o.accepted>(SELECT monotonic_ms FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM current_control_objects o JOIN current_control_bindings b ON b.credential=o.issuer WHERE o.kind=2 AND b.state!='blocked') OR
            EXISTS(SELECT 1 FROM current_control_neighbors n JOIN current_control_objects o ON o.reference=n.object WHERE n.start<o.accepted OR n.start>(SELECT monotonic_ms FROM meta WHERE id=1) OR n.last_ms>(SELECT monotonic_ms FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM current_control_bindings b WHERE b.generation!=(SELECT count(*) FROM current_control_bindings p WHERE p.participant=b.participant AND p.generation<=b.generation)) OR
            EXISTS(SELECT 1 FROM current_control_objects o JOIN current_control_bindings i ON o.issuer=i.credential JOIN current_control_bindings t ON o.target=t.credential WHERE i.state='pending' OR t.state='pending' OR o.reporter!=i.participant OR (o.kind=3 AND i.participant=t.participant)) OR
            EXISTS(SELECT 1 FROM current_control_neighbors n WHERE NOT EXISTS(SELECT 1 FROM current_control_bindings b WHERE b.participant=n.participant AND b.state!='pending') OR n.participant=(SELECT local_participant FROM current_control_activity))",
            [],|r|r.get(0))?;
        if invalid {
            return Err(Error::new(Code::StoreCorrupt, "D16 persistent invariants"));
        }
        Ok(())
    }
}
