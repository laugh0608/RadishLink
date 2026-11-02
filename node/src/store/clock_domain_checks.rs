use super::clock_domains::{Isolation, NewClockDomainActivity, reference};
use super::*;

impl Store {
    pub(super) fn check_clock_domains(&self) -> Result<()> {
        let invalid:bool=self.conn.query_row("SELECT
            (SELECT count(*) FROM meta)!=1 OR (SELECT count(*) FROM current_clock)!=1 OR
            (SELECT count(*) FROM clock_domains WHERE frozen=0)!=(SELECT 1-frozen FROM current_clock) OR
            EXISTS(SELECT 1 FROM clock_domains WHERE frozen=0 AND domain_id IS NOT (SELECT current_domain FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM clock_domains WHERE successor IS NULL AND domain_id IS NOT (SELECT current_domain FROM meta WHERE id=1)) OR
            EXISTS(SELECT 1 FROM clock_domains d WHERE d.sequence>1 AND NOT EXISTS(SELECT 1 FROM clock_domains p WHERE p.sequence=d.sequence-1 AND p.successor=d.domain_id)) OR
            EXISTS(SELECT 1 FROM clock_domains WHERE sequence>1 AND unix_ms IS NULL) OR
            EXISTS(SELECT 1 FROM clock_domains p JOIN clock_domains n ON n.domain_id=p.successor WHERE n.unix_ms<p.unix_ms OR n.unix_upper_ms<p.unix_upper_ms) OR
            NOT EXISTS(SELECT 1 FROM clock_domains WHERE sequence=1 AND domain_id=zeroblob(32)) OR
            (SELECT count(*) FROM clock_domains)>(SELECT count(*)+1 FROM control_activity) OR
            EXISTS(SELECT 1 FROM control_activity a JOIN clock_domains d ON d.domain_id=a.domain_id WHERE a.boot!=d.boot OR a.started>d.monotonic_ms OR (a.archived=0 AND a.domain_id IS NOT (SELECT current_domain FROM meta WHERE id=1)) OR (d.frozen=1 AND a.stopped=0)) OR
            EXISTS(SELECT 1 FROM messages WHERE domain_id IS NULL) OR EXISTS(SELECT 1 FROM message_data d JOIN messages m ON m.key=d.message_key WHERE d.domain_id IS NULL OR d.domain_id!=m.domain_id) OR
            EXISTS(SELECT 1 FROM messages WHERE domain_id IS NOT (SELECT current_domain FROM meta WHERE id=1) AND policy_stopped=0)",[],|r|r.get(0))?;
        if invalid {
            return Err(Error::new(Code::StoreCorrupt, "clock domain association"));
        }
        let mut statement = self
            .conn
            .prepare("SELECT domain_id FROM clock_domains ORDER BY sequence")?;
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            let id: Vec<u8> = row.get(0)?;
            let id: ClockDomainId = id
                .try_into()
                .map_err(|_| Error::new(Code::StoreCorrupt, "clock domain size"))?;
            let d = self
                .clock_domain_status(id)?
                .ok_or_else(|| Error::new(Code::StoreCorrupt, "clock domain missing"))?;
            let bad = |op| Error::new(Code::StoreCorrupt, op);
            check_ref(&d.boot)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "domain boot", e))?;
            if let (Some(lower_ms), Some(upper_ms)) = (d.utc_lower_ms, d.utc_upper_ms) {
                crate::data::UtcInterval { lower_ms, upper_ms }
                    .validate()
                    .map_err(|e| Error::source_error(Code::StoreCorrupt, "domain UTC", e))?;
            }
            let (isolation, transition) = self.domain_records(id)?;
            if d.frozen != isolation.is_some() {
                return Err(bad("domain frozen marker"));
            }
            if let Some(Isolation {
                request,
                observed_boot,
                isolated_revision,
            }) = isolation
            {
                reference(&request.reference).map_err(|e| {
                    Error::source_error(Code::StoreCorrupt, "domain isolation reference", e)
                })?;
                check_ref(&observed_boot).map_err(|e| {
                    Error::source_error(Code::StoreCorrupt, "domain observed boot", e)
                })?;
                if request.domain != id
                    || request.expected_revision < 0
                    || request.expected_revision.checked_add(1) != Some(isolated_revision)
                    || observed_boot == d.boot
                {
                    return Err(bad("domain isolation binding"));
                }
                let activity_ok:bool=match request.activity {
                    Some(activity)=>self.conn.query_row("SELECT EXISTS(SELECT 1 FROM control_activity WHERE activity=?1 AND domain_id=?2 AND stopped=1)",params![activity.as_slice(),id.as_slice()],|r|r.get(0))?,
                    None=>self.conn.query_row("SELECT NOT EXISTS(SELECT 1 FROM control_activity WHERE domain_id=?1)",[id.as_slice()],|r|r.get(0))?,
                };
                if !activity_ok {
                    return Err(bad("domain isolated activity"));
                }
                if let Some(request) = transition {
                    self.check_domain_transition(&d, isolated_revision, &request)?;
                } else if d.successor.is_some() {
                    return Err(bad("domain transition missing"));
                }
            } else if transition.is_some() || d.successor.is_some() {
                return Err(bad("unfrozen domain successor"));
            }
        }
        Ok(())
    }

    fn check_domain_transition(
        &self,
        source: &ClockDomainStatus,
        isolated_revision: i64,
        request: &NewClockDomainActivity,
    ) -> Result<()> {
        request
            .validate()
            .map_err(|e| Error::source_error(Code::StoreCorrupt, "domain transition record", e))?;
        let target = self
            .clock_domain_status(request.domain)?
            .ok_or_else(|| Error::new(Code::StoreCorrupt, "domain transition target missing"))?;
        let (domain,local,start,deadline):(Vec<u8>,Vec<u8>,i64,i64)=self.conn.query_row("SELECT domain_id,local_participant,started,deadline FROM control_activity WHERE activity=?1",[request.activity.as_slice()],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?)))?;
        if request.source != source.domain
            || source.successor != Some(request.domain)
            || request.isolated_revision != isolated_revision
            || source.sequence.checked_add(1) != Some(request.sequence)
            || target.sequence != request.sequence
            || target.boot != request.boot
            || domain != request.domain
            || local != request.local_participant
            || start != request.started_ms
            || deadline > request.deadline_ms
        {
            return Err(Error::new(Code::StoreCorrupt, "domain transition binding"));
        }
        Ok(())
    }
}
