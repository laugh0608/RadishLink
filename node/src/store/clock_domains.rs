//! Explicit trusted-owner maintenance. No clock trust, pairing or cryptography is inferred.
use super::*;
use serde::{Deserialize, Serialize};

pub type ClockDomainId = [u8; 32];
pub const INITIAL_CLOCK_DOMAIN: ClockDomainId = [0; 32];

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct IsolateClockDomain {
    pub domain: ClockDomainId,
    pub activity: Option<ActivityId>,
    pub expected_revision: i64,
    pub reference: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NewClockDomainActivity {
    pub source: ClockDomainId,
    pub isolated_revision: i64,
    pub reference: String,
    pub domain: ClockDomainId,
    pub sequence: i64,
    pub boot: String,
    pub activity: ActivityId,
    pub local_participant: ParticipantId,
    pub started_ms: i64,
    pub deadline_ms: i64,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClockDomainStatus {
    pub domain: ClockDomainId,
    pub sequence: i64,
    pub boot: String,
    pub monotonic_ms: i64,
    pub utc_lower_ms: Option<i64>,
    pub utc_upper_ms: Option<i64>,
    pub frozen: bool,
    pub isolation_reference: Option<String>,
    pub isolated_revision: Option<i64>,
    pub successor: Option<ClockDomainId>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClockDomainPreflight {
    pub source: ClockDomainStatus,
    pub activity: Option<ActivityId>,
    pub archive_bytes: u64,
    pub archive_records: u64,
    pub free_control_bytes: u64,
    pub free_control_records: u64,
    pub free_records: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Isolation {
    pub request: IsolateClockDomain,
    pub observed_boot: String,
    pub isolated_revision: i64,
}

pub(super) fn reference(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-:.".contains(&b))
    {
        return Err(Error::new(Code::InvalidInput, "domain request reference"));
    }
    Ok(())
}
pub(super) fn encoded<T: Serialize>(value: &T, max: usize) -> Result<String> {
    let value = serde_json::to_string(value)
        .map_err(|e| Error::source_error(Code::InvalidInput, "domain request encoding", e))?;
    if value.len() > max {
        return Err(Error::new(Code::InvalidInput, "domain request size"));
    }
    Ok(value)
}
pub(super) fn decoded<T: for<'a> Deserialize<'a>>(value: &str) -> Result<T> {
    serde_json::from_str(value)
        .map_err(|e| Error::source_error(Code::StoreCorrupt, "domain request record", e))
}
impl NewClockDomainActivity {
    pub(super) fn validate(&self) -> Result<()> {
        reference(&self.reference)?;
        check_ref(&self.boot)?;
        if self.isolated_revision <= 0
            || self.sequence <= 1
            || self.started_ms < 0
            || self.deadline_ms <= self.started_ms
            || self
                .deadline_ms
                .checked_sub(self.started_ms)
                .is_none_or(|n| n > MAX_ACTIVITY_MS)
        {
            return Err(Error::new(Code::InvalidInput, "new domain activity bounds"));
        }
        Ok(())
    }
}

impl Store {
    pub(super) fn current_domain_id(&self) -> Result<ClockDomainId> {
        let id: Vec<u8> =
            self.conn
                .query_row("SELECT current_domain FROM meta WHERE id=1", [], |r| {
                    r.get(0)
                })?;
        id.try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "current domain size"))
    }
    pub(super) fn optional_current_activity(&self) -> Result<Option<ActivityId>> {
        let id: Option<Vec<u8>> =
            self.conn
                .query_row("SELECT current_activity FROM meta WHERE id=1", [], |r| {
                    r.get(0)
                })?;
        id.map(|id| {
            id.try_into()
                .map_err(|_| Error::new(Code::StoreCorrupt, "current activity size"))
        })
        .transpose()
    }
    pub(super) fn domain_records(
        &self,
        domain: ClockDomainId,
    ) -> Result<(Option<Isolation>, Option<NewClockDomainActivity>)> {
        let (a, b): (Option<String>, Option<String>) = self
            .conn
            .query_row(
                "SELECT isolation,transition FROM clock_domains WHERE domain_id=?1",
                [domain.as_slice()],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?
            .ok_or_else(|| Error::new(Code::Conflict, "clock domain missing"))?;
        Ok((
            a.as_deref().map(decoded).transpose()?,
            b.as_deref().map(decoded).transpose()?,
        ))
    }
    /// Read-only facts, including historical outcomes; never an output or recovery permit.
    pub fn clock_domain_status(&self, domain: ClockDomainId) -> Result<Option<ClockDomainStatus>> {
        self.readable()?;
        let row = self.conn.query_row("SELECT sequence,boot,monotonic_ms,unix_ms,unix_upper_ms,frozen,isolation,successor FROM clock_domains WHERE domain_id=?1",[domain.as_slice()],|r|Ok((r.get::<_,i64>(0)?,r.get::<_,String>(1)?,r.get::<_,i64>(2)?,r.get::<_,Option<i64>>(3)?,r.get::<_,Option<i64>>(4)?,r.get::<_,bool>(5)?,r.get::<_,Option<String>>(6)?,r.get::<_,Option<Vec<u8>>>(7)?))).optional()?;
        row.map(
            |(
                sequence,
                boot,
                monotonic_ms,
                utc_lower_ms,
                utc_upper_ms,
                frozen,
                isolation,
                successor,
            )| {
                let isolation: Option<Isolation> = isolation.as_deref().map(decoded).transpose()?;
                Ok(ClockDomainStatus {
                    domain,
                    sequence,
                    boot,
                    monotonic_ms,
                    utc_lower_ms,
                    utc_upper_ms,
                    frozen,
                    isolation_reference: isolation.as_ref().map(|v| v.request.reference.clone()),
                    isolated_revision: isolation.map(|v| v.isolated_revision),
                    successor: successor
                        .map(|v| {
                            v.try_into().map_err(|_| {
                                Error::new(Code::StoreCorrupt, "domain successor size")
                            })
                        })
                        .transpose()?,
                })
            },
        )
        .transpose()
    }
    pub fn current_clock_domain(&self) -> Result<ClockDomainStatus> {
        self.clock_domain_status(self.current_domain_id()?)?
            .ok_or_else(|| Error::new(Code::StoreCorrupt, "current domain missing"))
    }
    pub(super) fn archive_capacity(&self) -> Result<(u64, u64, u64)> {
        let (bytes,records,all):(i64,i64,i64)=self.conn.query_row("SELECT
            (SELECT count(*)*4096 FROM queues WHERE kind='evidence')+(SELECT coalesce(sum(bytes),0) FROM control_reservations)+(SELECT count(*)*4096 FROM receipt_intents)+(SELECT bytes FROM activity_archive_usage),
            (SELECT count(*) FROM queues WHERE kind='evidence')+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)+(SELECT records FROM activity_archive_usage),
            (SELECT count(*) FROM messages)+(SELECT count(*) FROM actions)+(SELECT count(*) FROM queues)+(SELECT count(*) FROM action_scopes)+(SELECT count(*) FROM security_states)+(SELECT count(*) FROM control_reservations)+(SELECT count(*) FROM receipt_intents)+(SELECT records FROM activity_archive_usage)",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?)))?;
        let free = |limit: u64, used: i64| -> Result<u64> {
            let used = u64::try_from(used)
                .map_err(|_| Error::new(Code::StoreCorrupt, "negative archive usage"))?;
            limit
                .checked_sub(used)
                .ok_or_else(|| Error::new(Code::Quota, "archive capacity"))
        };
        Ok((
            free(self.limits.control_bytes - CONTROL_RESERVED_BYTES, bytes)?,
            free(
                u64::from(self.limits.control_count - CONTROL_RESERVED_RECORDS),
                records,
            )?,
            free(
                u64::from(self.limits.record_count - CONTROL_RESERVED_RECORDS),
                all,
            )?,
        ))
    }
    pub fn preflight_clock_domain(&self) -> Result<ClockDomainPreflight> {
        self.readable()?;
        let source = self.current_clock_domain()?;
        let activity = self.optional_current_activity()?;
        let u = self.control_usage()?;
        let (free_control_bytes, free_control_records, free_records) = self.archive_capacity()?;
        Ok(ClockDomainPreflight {
            source,
            activity,
            archive_bytes: 4096
                + if activity.is_some() {
                    4096 + u.bindings * 1024 + u.objects * 4096 + u.neighbors * 512
                } else {
                    0
                },
            archive_records: 1 + if activity.is_some() {
                1 + u.bindings + u.objects + u.neighbors
            } else {
                0
            },
            free_control_bytes,
            free_control_records,
            free_records,
        })
    }
    fn apply_domain_isolation(&self, request: &IsolateClockDomain) -> Result<()> {
        reference(&request.reference)?;
        let source = self.current_clock_domain()?;
        if source.domain != request.domain
            || self.optional_current_activity()? != request.activity
            || self.revision()? != request.expected_revision
            || source.frozen
        {
            return Err(Error::new(Code::Conflict, "domain isolation precondition"));
        }
        if self.clock.boot == source.boot
            || self.conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM clock_domains WHERE boot=?1)",
                [&self.clock.boot],
                |r| r.get::<_, bool>(0),
            )?
        {
            return Err(Error::new(
                Code::TimeUncertain,
                "new boot required for isolation",
            ));
        }
        let isolated_revision = request
            .expected_revision
            .checked_add(1)
            .ok_or_else(|| Error::new(Code::Quota, "domain revision exhausted"))?;
        let record = encoded(
            &Isolation {
                request: request.clone(),
                observed_boot: self.clock.boot.clone(),
                isolated_revision,
            },
            1024,
        )?;
        self.conn.execute("UPDATE control_activity SET stopped=1 WHERE activity=(SELECT current_activity FROM meta WHERE id=1)",[])?;
        self.conn.execute("UPDATE action_scopes SET retired=1 WHERE activity IN (SELECT activity FROM control_activity WHERE domain_id=?1)",[source.domain.as_slice()])?;
        self.conn.execute(
            "UPDATE messages SET policy_stopped=1 WHERE domain_id=?1 AND policy_stopped=0",
            [source.domain.as_slice()],
        )?;
        self.conn.execute(
            "UPDATE clock_domains SET frozen=1,isolation=?2 WHERE domain_id=?1",
            params![source.domain.as_slice(), record],
        )?;
        Ok(())
    }
    /// Explicitly freezes the old coordinate without advancing it or claiming a signed exit.
    pub fn isolate_clock_domain(
        &mut self,
        request: IsolateClockDomain,
    ) -> Result<ClockDomainStatus> {
        self.readable()?;
        reference(&request.reference)?;
        let assigned:Option<Vec<u8>>=self.conn.query_row("SELECT domain_id FROM clock_domains WHERE json_extract(isolation,'$.request.reference')=?1",[&request.reference],|r|r.get(0)).optional()?;
        if assigned.as_deref().is_some_and(|id| id != request.domain) {
            return Err(Error::new(
                Code::Conflict,
                "isolation reference belongs to another source",
            ));
        }
        let (prior, _) = self.domain_records(request.domain)?;
        if let Some(prior) = prior {
            if prior.request.reference == request.reference && prior.request != request {
                return Err(Error::new(Code::Conflict, "isolation reference rebound"));
            }
            if prior.request == request
                || (self.current_domain_id()? == request.domain
                    && self.optional_current_activity()? == request.activity)
            {
                return self
                    .clock_domain_status(request.domain)?
                    .ok_or_else(|| Error::new(Code::StoreCorrupt, "isolation domain missing"));
            }
            return Err(Error::new(Code::Conflict, "historical isolation request"));
        }
        self.transact(|s| s.apply_domain_isolation(&request), false)?;
        self.time_uncertain = true;
        self.clock_domain_status(request.domain)?
            .ok_or_else(|| Error::new(Code::StoreCorrupt, "isolated domain missing"))
    }
    pub(super) fn migrate_cold_v8(&mut self, request: &IsolateClockDomain) -> Result<()> {
        if self.schema_version()? != 8 {
            return Err(Error::new(Code::Conflict, "cold migration source"));
        }
        self.transact(
            |s| {
                s.conn.execute_batch(include_str!("migration_v9.sql"))?;
                s.conn.execute_batch(include_str!("migration_v10.sql"))?;
                // Check the source snapshot in its own coordinate, never by impersonating its Clock.
                s.check_invariants()?;
                s.apply_domain_isolation(request)
            },
            false,
        )?;
        self.time_uncertain = true;
        Ok(())
    }
    /// Creates only internal empty context. The caller still owes real worker shutdown and pairing.
    pub fn establish_clock_domain(
        &mut self,
        request: NewClockDomainActivity,
    ) -> Result<ActivityStatus> {
        self.require_owner_running()?;
        self.readable()?;
        request.validate()?;
        let assigned:Option<Vec<u8>>=self.conn.query_row("SELECT domain_id FROM clock_domains WHERE json_extract(transition,'$.reference')=?1",[&request.reference],|r|r.get(0)).optional()?;
        if assigned.as_deref().is_some_and(|id| id != request.source) {
            return Err(Error::new(
                Code::Conflict,
                "transition reference belongs to another source",
            ));
        }
        let (isolation, prior) = self.domain_records(request.source)?;
        if let Some(prior) = prior {
            if prior != request {
                return Err(Error::new(
                    Code::Conflict,
                    "domain transition already assigned",
                ));
            }
            return self
                .activity_status(request.activity)?
                .ok_or_else(|| Error::new(Code::StoreCorrupt, "transition activity missing"));
        }
        let isolation =
            isolation.ok_or_else(|| Error::new(Code::Conflict, "isolate source domain first"))?;
        let p = self.preflight_clock_domain()?;
        if p.source.domain != request.source
            || !p.source.frozen
            || isolation.isolated_revision != request.isolated_revision
            || self.revision()? != request.isolated_revision
            || p.activity != isolation.request.activity
        {
            return Err(Error::new(Code::Conflict, "domain establishment source"));
        }
        if p.source.sequence.checked_add(1) != Some(request.sequence) {
            return Err(Error::new(
                Code::Quota,
                "domain sequence exhausted or changed",
            ));
        }
        if self.clock.boot != request.boot || self.clock.monotonic_ms != request.started_ms {
            return Err(Error::new(
                Code::TimeUncertain,
                "domain prepared clock changed",
            ));
        }
        let utc = self
            .clock
            .trusted_utc
            .ok_or_else(|| Error::new(Code::TimeUncertain, "new domain UTC required"))?;
        let (lower, upper): (Option<i64>, Option<i64>) = self.conn.query_row(
            "SELECT max(unix_ms),max(unix_upper_ms) FROM clock_domains",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        if lower.is_some_and(|v| utc.lower_ms < v) || upper.is_some_and(|v| utc.upper_ms < v) {
            return Err(Error::new(Code::TimeUncertain, "new domain UTC regressed"));
        }
        let jobs = self.control_ingress_usage();
        if jobs.waiting != 0 || jobs.verifying != 0 {
            return Err(Error::new(Code::Busy, "domain verification tasks remain"));
        }
        if p.archive_bytes > p.free_control_bytes
            || p.archive_records > p.free_control_records
            || p.archive_records > p.free_records
        {
            return Err(Error::new(Code::Quota, "clock domain archive admission"));
        }
        let record = encoded(&request, 2048)?;
        self.transact(|s| {
            let reused:bool=s.conn.query_row("SELECT EXISTS(SELECT 1 FROM clock_domains WHERE domain_id=?1 OR boot=?2) OR EXISTS(SELECT 1 FROM control_activity WHERE activity=?3 OR local_participant=?4) OR EXISTS(SELECT 1 FROM control_bindings WHERE participant=?4)",params![request.domain.as_slice(),request.boot,request.activity.as_slice(),request.local_participant.as_slice()],|r|r.get(0))?;
            if reused {return Err(Error::new(Code::Conflict,"domain or activity identity reused"));}
            if let Some(previous)=p.activity {
                let rate:String=s.conn.query_row("SELECT json_object('last_ms',last_ms,'frames',frames,'bytes',bytes,'exit_cursor',exit_cursor,'ordinary_cursor',ordinary_cursor) FROM control_output_rate WHERE id=1",[],|r|r.get(0))?;
                s.conn.execute("UPDATE control_activity SET archived=1,closed_kind='cross_boot',successor=?2,final_rate=?3 WHERE activity=?1 AND stopped=1",params![previous.as_slice(),request.activity.as_slice(),rate])?;
            }
            s.conn.execute("INSERT INTO clock_domains(domain_id,sequence,boot,monotonic_ms,unix_ms,unix_upper_ms) VALUES(?1,?2,?3,?4,?5,?6)",params![request.domain.as_slice(),request.sequence,request.boot,request.started_ms,utc.lower_ms,utc.upper_ms])?;
            s.conn.execute("UPDATE clock_domains SET successor=?2,transition=?3 WHERE domain_id=?1",params![request.source.as_slice(),request.domain.as_slice(),record])?;
            s.conn.execute("INSERT INTO control_activity(activity,local_participant,boot,started,deadline,domain_id) VALUES(?1,?2,?3,?4,?5,?6)",params![request.activity.as_slice(),request.local_participant.as_slice(),request.boot,request.started_ms,request.deadline_ms,request.domain.as_slice()])?;
            s.conn.execute("UPDATE meta SET current_domain=?1,current_activity=?2 WHERE id=1",params![request.domain.as_slice(),request.activity.as_slice()])?;
            s.conn.execute("INSERT INTO control_output_rate(id,last_ms,frames,bytes,exit_cursor,ordinary_cursor) VALUES(1,?1,0,0,NULL,NULL) ON CONFLICT(id) DO UPDATE SET last_ms=excluded.last_ms,frames=0,bytes=0,exit_cursor=NULL,ordinary_cursor=NULL",[request.started_ms])?;
            s.activity_status(request.activity)?.ok_or_else(||Error::new(Code::StoreCorrupt,"new domain activity missing"))
        },false).inspect(|_| {
            self.time_uncertain=false;
            self.ingress=control_ingress::ControlIngress::new(request.started_ms);
        })
    }
}
