use super::*;

impl Store {
    fn update_security(&self, u: &SecurityUpdate) -> Result<()> {
        u.validate()?;
        let revision: Option<i64> = self
            .conn
            .query_row(
                "SELECT revision FROM security_states WHERE session=?1",
                [&u.session],
                |r| r.get(0),
            )
            .optional()?;
        if revision.unwrap_or(0) != u.expected_revision {
            return Err(Error::new(Code::Conflict, "security revision"));
        }
        self.conn.execute("INSERT INTO security_states VALUES(?1,?2,?3) ON CONFLICT(session) DO UPDATE SET revision=excluded.revision,state=excluded.state",params![u.session,u.expected_revision+1,u.state])?;
        #[cfg(test)]
        if self.fault == Some(TestFault::AfterSecurity) {
            return Err(Error::new(
                Code::StoreUnavailable,
                "test after security write",
            ));
        }
        Ok(())
    }
    fn insert_message(
        &self,
        m: &Message,
        role: Role,
        hops: u8,
        source: Option<&str>,
    ) -> Result<()> {
        let state = match role {
            Role::Origin => "queued",
            Role::Relay => "stored",
            Role::Destination => "committed",
        };
        self.conn.execute("INSERT INTO messages(key,core,role,state,payload,deadline,retain_until,hops,origin_ref,source_neighbor,data_version) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,1)",params![m.key,m.core_binding,role.as_str(),state,m.payload,m.deadline_ms,m.retain_until_ms,hops,m.data.origin_ref(),source])?;
        self.insert_data(m)
    }
    fn insert_history(&self, key: &str, body: &[u8]) -> Result<()> {
        check_text(body)?;
        let expiry = self
            .clock
            .utc_upper_ms()
            .and_then(|t| t.checked_add(HISTORY_MS))
            .ok_or_else(|| Error::new(Code::TimeUncertain, "history expiry"))?;
        self.conn.execute(
            "INSERT INTO history(message_key,body,expires) VALUES(?1,?2,?3)",
            params![key, body, expiry],
        )?;
        Ok(())
    }
    pub(super) fn insert_queue(
        &self,
        key: &str,
        kind: &str,
        neighbor: &str,
        hops: u8,
        body: &[u8],
        deadline: i64,
    ) -> Result<()> {
        check_ref(neighbor)?;
        if body.len() > MAX_CONTROL {
            return Err(Error::new(Code::InvalidInput, "control size"));
        }
        let retry = RetryState::new(self.clock.monotonic_ms, deadline, Link::Up)?;
        let encoded = serde_json::to_string(&retry)
            .map_err(|e| Error::source_error(Code::InvalidInput, "retry encoding", e))?;
        self.conn.execute(
            "INSERT INTO queues VALUES(?1,?2,?3,?4,?5,?6)",
            params![key, kind, neighbor, hops, body, encoded],
        )?;
        Ok(())
    }
    fn matching_message(&self, m: &Message, role: Role) -> Result<Option<MessageView>> {
        let saved: Option<(Vec<u8>, String, String)> = self
            .conn
            .query_row(
                "SELECT core,role,origin_ref FROM messages WHERE key=?1",
                [&m.key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .optional()?;
        if let Some((core, saved_role, origin)) = saved {
            if saved_role != role.as_str()
                || core != m.core_binding
                || origin != m.data.origin_ref()
            {
                return Err(Error::new(Code::Conflict, "message binding or role"));
            }
            self.matching_data(m)?;
            return self.message(&m.key);
        }
        Ok(None)
    }
    /// T-A persistence only. Authentication and encryption are a future caller prerequisite.
    pub fn submit(&mut self, send: Send) -> Result<MessageView> {
        self.writable()?;
        send.action.validate()?;
        self.check_generation(&send.action.scope, send.action.generation)?;
        let prior:Option<(Vec<u8>,String)>=self.conn.query_row("SELECT binding,message_key FROM actions WHERE scope=?1 AND generation=?2 AND reference=?3",params![send.action.scope,send.action.generation,send.action.reference],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
        if let Some((binding, key)) = prior {
            if binding != send.action.binding {
                return Err(Error::new(Code::Conflict, "action contents"));
            }
            return self
                .message(&key)?
                .ok_or_else(|| Error::new(Code::StoreCorrupt, "action target"));
        }
        self.validate_data_admission(&send.message, send.remaining_hops, None)?;
        check_text(&send.text)?;
        check_ref(&send.neighbor)?;
        send.security.validate()?;
        if self.message(&send.message.key)?.is_some() {
            return Err(Error::new(Code::Conflict, "message key already assigned"));
        }
        self.atomic(|s| {
            s.update_security(&send.security)?;
            s.insert_message(&send.message, Role::Origin, send.remaining_hops, None)?;
            s.insert_history(&send.message.key, &send.text)?;
            s.insert_queue(
                &send.message.key,
                "data",
                &send.neighbor,
                send.remaining_hops,
                &[],
                send.message.deadline_ms,
            )?;
            s.conn.execute(
                "INSERT INTO actions VALUES(?1,?2,?3,?4,?5)",
                params![
                    send.action.scope,
                    send.action.generation,
                    send.action.reference,
                    send.action.binding,
                    send.message.key
                ],
            )?;
            Ok(())
        })?;
        self.message(&send.message.key)?
            .ok_or_else(|| Error::new(Code::StoreCorrupt, "submitted message"))
    }
    /// T-B / T-C. Relay never accepts plaintext or security state for an endpoint.
    pub fn receive(&mut self, receive: Receive) -> Result<MessageView> {
        self.writable()?;
        self.validate_data_admission(
            &receive.message,
            receive.remaining_hops,
            Some(receive.remaining_lifetime_ms),
        )?;
        check_ref(&receive.neighbor)?;
        if receive.role == Role::Origin {
            return Err(Error::new(Code::InvalidInput, "receive role"));
        }
        if let Some(view) = self.matching_message(&receive.message, receive.role)? {
            self.data_remaining_at(&receive.message.key, &self.clock)?;
            let (deadline, hops): (i64, u8) = self.conn.query_row(
                "SELECT deadline,hops FROM messages WHERE key=?1",
                [&receive.message.key],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )?;
            if receive.message.deadline_ms < deadline || receive.remaining_hops < hops {
                self.atomic(|s| {
                    s.shorten_data(
                        &receive.message.key,
                        receive.message.deadline_ms,
                        Some(receive.remaining_hops),
                    )
                })?;
            }
            return Ok(view);
        }
        match receive.role {
            Role::Relay => {
                if receive.security.is_some()
                    || receive.text.is_some()
                    || receive.receipt_intent.is_some()
                    || receive.remaining_hops == 0
                {
                    return Err(Error::new(Code::InvalidInput, "relay admission"));
                }
            }
            Role::Destination => {
                receive
                    .security
                    .as_ref()
                    .ok_or_else(|| Error::new(Code::InvalidInput, "receive security state"))?
                    .validate()?;
                check_text(
                    receive
                        .text
                        .as_deref()
                        .ok_or_else(|| Error::new(Code::InvalidInput, "receive text"))?,
                )?;
                let intent = receive
                    .receipt_intent
                    .as_ref()
                    .ok_or_else(|| Error::new(Code::InvalidInput, "delivery intent"))?;
                if intent.is_empty() || intent.len() > MAX_CONTROL {
                    return Err(Error::new(Code::InvalidInput, "delivery intent size"));
                }
            }
            Role::Origin => unreachable!(),
        }
        self.atomic(|s| {
            if let Some(u) = &receive.security {
                s.update_security(u)?;
            }
            s.insert_message(
                &receive.message,
                receive.role,
                receive.remaining_hops,
                Some(&receive.neighbor),
            )?;
            if receive.role == Role::Relay {
                s.conn.execute(
                    "INSERT INTO control_reservations VALUES(?1,4096)",
                    [&receive.message.key],
                )?;
            }
            if let Some(body) = &receive.text {
                s.insert_history(&receive.message.key, body)?;
            }
            if let Some(intent) = &receive.receipt_intent {
                s.conn.execute(
                    "INSERT INTO receipt_intents VALUES(?1,?2)",
                    params![receive.message.key, intent],
                )?;
            }
            Ok(())
        })?;
        self.message(&receive.message.key)?
            .ok_or_else(|| Error::new(Code::StoreCorrupt, "received message"))
    }
    /// Schedules a relay's next-hop copy once. A duplicate cannot replenish hop/retry budget.
    pub fn schedule_forward(&mut self, key: &str, neighbor: &str) -> Result<()> {
        check_ref(key)?;
        check_ref(neighbor)?;
        self.atomic(|s| {
            s.data_remaining_at(key, &s.clock)?;
            let (role, state, deadline, incoming_hops): (String, String, i64, u8) =
                s.conn.query_row(
                    "SELECT role,state,deadline,hops FROM messages WHERE key=?1",
                    [key],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
                )?;
            if incoming_hops == 0
                || role != "relay"
                || state != "stored"
                || deadline <= s.clock.monotonic_ms
            {
                return Err(Error::new(Code::Conflict, "relay forwarding state"));
            }
            let exists: bool = s.conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM queues WHERE message_key=?1 AND kind='data')",
                [key],
                |r| r.get(0),
            )?;
            if exists {
                return Err(Error::new(Code::Conflict, "relay copy already scheduled"));
            }
            s.insert_queue(key, "data", neighbor, incoming_hops - 1, &[], deadline)
        })
    }
    /// Custody pauses data retries but never deletes payload or reports destination delivery.
    pub fn observe_custody(&mut self, key: &str, neighbor: &str) -> Result<()> {
        check_ref(key)?;
        check_ref(neighbor)?;
        self.atomic(|s| {
            s.advance_queue_in_transaction(
                key,
                "data",
                neighbor,
                Batch {
                    now_ms: s.clock.monotonic_ms,
                    link: crate::retry::LinkEvent::Unchanged,
                    signal: crate::retry::Signal::Pause,
                    admission: crate::retry::Admission::Allow,
                },
                &s.clock,
            )?;
            Ok(())
        })
    }
    /// T-D: verified proof is a caller prerequisite. Stores return responsibility before cleanup.
    pub fn finish_delivery(
        &mut self,
        key: &str,
        core: &[u8],
        return_evidence: Option<(&str, &[u8])>,
    ) -> Result<()> {
        check_ref(key)?;
        self.atomic(|s| {
            s.data_remaining_at(key, &s.clock)?;
            let (saved, role, state, deadline, source): (
                Vec<u8>,
                String,
                String,
                i64,
                Option<String>,
            ) = s.conn.query_row(
                "SELECT core,role,state,deadline,source_neighbor FROM messages WHERE key=?1",
                [key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
            )?;
            if saved != core {
                return Err(Error::new(Code::Conflict, "delivery core"));
            }
            if state == "expired" || deadline <= s.clock.monotonic_ms {
                return Err(Error::new(Code::Expired, "delivery deadline"));
            }
            if role == "relay" {
                let (neighbor, evidence) = return_evidence
                    .ok_or_else(|| Error::new(Code::InvalidInput, "relay return responsibility"))?;
                if evidence.is_empty() || evidence.len() > MAX_CONTROL {
                    return Err(Error::new(Code::InvalidInput, "delivery evidence size"));
                }
                if source.as_deref() != Some(neighbor) {
                    return Err(Error::new(Code::Conflict, "delivery return neighbor"));
                }
                if state == "delivered" {
                    // Caller has verified semantic equivalence; never refill a returned queue.
                    return Ok(());
                }
                let deleted = s.conn.execute(
                    "DELETE FROM control_reservations WHERE message_key=?1",
                    [key],
                )?;
                if deleted != 1 {
                    return Err(Error::new(Code::StoreCorrupt, "missing relay reservation"));
                }
                s.insert_queue(key, "evidence", neighbor, 0, evidence, deadline)?;
            } else if role != "origin" || return_evidence.is_some() {
                return Err(Error::new(Code::InvalidInput, "delivery role"));
            } else if state == "delivered" {
                return Ok(());
            }
            s.conn.execute(
                "UPDATE messages SET state='delivered',payload=NULL WHERE key=?1",
                [key],
            )?;
            s.conn.execute(
                "DELETE FROM queues WHERE message_key=?1 AND kind='data'",
                [key],
            )?;
            Ok(())
        })
    }
    pub fn expire_payload(&mut self, key: &str) -> Result<()> {
        check_ref(key)?;
        self.atomic(|s| {
            let (deadline, state): (i64, String) = s.conn.query_row(
                "SELECT deadline,state FROM messages WHERE key=?1",
                [key],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )?;
            if state == "delivered" || state == "expired" {
                return Ok(());
            }
            if deadline > s.clock.monotonic_ms {
                return Err(Error::new(Code::Conflict, "payload not expired"));
            }
            s.conn.execute(
                "UPDATE messages SET state=CASE WHEN role='destination' THEN 'delivered' ELSE 'expired' END,payload=NULL WHERE key=?1",
                [key],
            )?;
            s.conn.execute(
                "DELETE FROM queues WHERE message_key=?1 AND kind='data'",
                [key],
            )?;
            s.conn.execute(
                "DELETE FROM control_reservations WHERE message_key=?1",
                [key],
            )?;
            Ok(())
        })
    }
    /// Returns the scheduling decision only after durable budget consumption.
    /// There is no network sender in this batch.
    pub fn advance_queue(
        &mut self,
        key: &str,
        kind: &str,
        neighbor: &str,
        batch: Batch,
    ) -> Result<Decision> {
        check_ref(key)?;
        check_ref(neighbor)?;
        if !["data", "evidence"].contains(&kind) || batch.now_ms != self.clock.monotonic_ms {
            return Err(Error::new(Code::InvalidInput, "queue event coordinate"));
        }
        self.atomic(|s| s.advance_queue_in_transaction(key, kind, neighbor, batch, &s.clock))
    }
}
