use super::*;

impl Store {
    /// Only committed intent is visible. No signer exists in this foundation.
    /// Future callers must additionally check current identity/revocation policy.
    pub fn receipt_intent(&self, key: &str) -> Result<Option<ReceiptIntent>> {
        self.writable()?;
        check_ref(key)?;
        let mut intent = self.conn.query_row(
            "SELECT m.key,m.core,i.body,m.source_neighbor,m.deadline FROM receipt_intents i JOIN messages m ON m.key=i.message_key WHERE m.key=?1",
            [key],
            |r| Ok(ReceiptIntent { policy_revision:0,key: r.get(0)?, core_binding: r.get(1)?, body: r.get(2)?, neighbor: r.get(3)?, deadline_ms: r.get(4)? }),
        ).optional()?;
        if let Some(intent) = intent.as_mut() {
            self.data_remaining_at(key, &self.clock)?;
            intent.policy_revision = self.authorize_business_message(
                key,
                Some(&intent.neighbor),
                self.clock.monotonic_ms,
            )?;
        }
        if intent
            .as_ref()
            .is_some_and(|i| i.deadline_ms <= self.clock.monotonic_ms)
        {
            return Err(Error::new(Code::Expired, "receipt intent deadline"));
        }
        Ok(intent)
    }

    /// Converts an already committed intent to a proof queue, without creating history.
    /// Signing, semantic binding and current authorization are future caller prerequisites.
    /// Opaque test bytes are never treated as an authentic proof by the public Service.
    pub fn finalize_receipt(
        &mut self,
        key: &str,
        intent_body: &[u8],
        evidence: &[u8],
        expected_policy_revision: i64,
    ) -> Result<()> {
        check_ref(key)?;
        if intent_body.is_empty()
            || intent_body.len() > MAX_CONTROL
            || evidence.is_empty()
            || evidence.len() > MAX_CONTROL
        {
            return Err(Error::new(Code::InvalidInput, "receipt conversion size"));
        }
        self.atomic(|s| {
            s.data_remaining_at(key, &s.clock)?;
            let revision=s.authorize_business_message(key,None,s.clock.monotonic_ms)?;
            if revision!=expected_policy_revision {return Err(Error::new(Code::Conflict,"receipt authorization revision changed"));}
            let (role, deadline, neighbor): (String, i64, Option<String>) = s.conn.query_row(
                "SELECT role,deadline,source_neighbor FROM messages WHERE key=?1", [key],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
            if role != "destination" {
                return Err(Error::new(Code::InvalidInput, "receipt destination"));
            }
            if deadline <= s.clock.monotonic_ms {
                return Err(Error::new(Code::Expired, "receipt conversion deadline"));
            }
            let neighbor = neighbor.ok_or_else(|| Error::new(Code::StoreCorrupt, "receipt return path"))?;
            let saved: Option<Vec<u8>> = s.conn.query_row(
                "SELECT body FROM receipt_intents WHERE message_key=?1", [key], |r| r.get(0)).optional()?;
            match saved {
                Some(body) if body == intent_body => {
                    s.conn.execute("DELETE FROM receipt_intents WHERE message_key=?1", [key])?;
                    s.insert_queue(key, "evidence", &neighbor, 0, evidence, deadline)
                }
                Some(_) => Err(Error::new(Code::Conflict, "receipt intent changed")),
                None => {
                    let queued: Option<Vec<u8>> = s.conn.query_row(
                        "SELECT body FROM queues WHERE message_key=?1 AND kind='evidence' AND neighbor=?2",
                        params![key, neighbor], |r| r.get(0)).optional()?;
                    if queued.as_deref() == Some(evidence) {
                        // A lost conversion response cannot reset the queue's timing or budget.
                        Ok(())
                    } else {
                        Err(Error::new(Code::Conflict, "receipt already converted or missing"))
                    }
                }
            }
        })
    }

    pub(super) fn check_queue_deadlines(&self, legacy: bool) -> Result<()> {
        let mut stmt = self.conn.prepare(
            "SELECT q.retry,q.kind,m.deadline,m.retain_until FROM queues q JOIN messages m ON m.key=q.message_key")?;
        for row in stmt.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
            ))
        })? {
            let (encoded, kind, deadline, retain) = row?;
            let retry: RetryState = serde_json::from_str(&encoded)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "retry record", e))?;
            retry
                .validate()
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "retry state", e))?;
            let bound = if legacy && kind == "evidence" {
                retain
            } else {
                deadline
            };
            if retry.deadline_ms() > bound {
                return Err(Error::new(
                    Code::StoreCorrupt,
                    "queue exceeds message deadline",
                ));
            }
        }
        Ok(())
    }

    pub(super) fn migrate_receipt_deadlines(&self) -> Result<()> {
        let mut stmt = self.conn.prepare(
            "SELECT q.message_key,q.neighbor,q.retry,m.deadline FROM queues q JOIN messages m ON m.key=q.message_key WHERE q.kind='evidence'")?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, i64>(3)?,
                ))
            })?
            .collect::<std::result::Result<Vec<_>, _>>()?;
        drop(stmt);
        for (key, neighbor, encoded, deadline) in rows {
            let mut retry: RetryState = serde_json::from_str(&encoded)
                .map_err(|e| Error::source_error(Code::StoreCorrupt, "migration retry", e))?;
            retry.constrain_deadline(deadline)?;
            let encoded = serde_json::to_string(&retry).map_err(|e| {
                Error::source_error(Code::StoreCorrupt, "migration retry encoding", e)
            })?;
            self.conn.execute("UPDATE queues SET retry=?3 WHERE message_key=?1 AND kind='evidence' AND neighbor=?2", params![key, neighbor, encoded])?;
        }
        // Explicit migration may terminate all already expired proof queues; it is not a timer tick.
        self.conn.execute("DELETE FROM queues WHERE kind='evidence' AND message_key IN (SELECT key FROM messages WHERE deadline<=?1)", [self.clock.monotonic_ms])?;
        Ok(())
    }
}
