//! D13/D16 authorization of prepared business records, not signature verification.
use super::*;
use crate::data::PreparedCore;

/// Stable channel key for an exact credential, never a nickname or transport address.
pub fn credential_key(credential: &CredentialRef) -> String {
    credential.iter().map(|b| format!("{b:02x}")).collect()
}
fn credential_from_key(value: &str) -> Result<CredentialRef> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        return Err(Error::new(
            Code::InvalidInput,
            "business neighbor credential reference",
        ));
    }
    let mut out = [0; 32];
    for (i, slot) in out.iter_mut().enumerate() {
        *slot = u8::from_str_radix(&value[i * 2..i * 2 + 2], 16).map_err(|e| {
            Error::source_error(Code::InvalidInput, "business credential encoding", e)
        })?;
    }
    Ok(out)
}
impl Store {
    /// A failed durable policy write cannot leave this owner producing under old authority.
    pub(super) fn policy_atomic<T>(&mut self, apply: impl FnOnce(&Self) -> Result<T>) -> Result<T> {
        let result = self.atomic(apply);
        if result.as_ref().is_err_and(|e| {
            matches!(e.code, Code::StoreUnavailable | Code::OutcomeUnknown)
                || e.operation == "business policy revision exhausted"
        }) {
            self.halted = true;
        }
        result
    }
    /// Future transport must call under the same owner as handoff, with its exact credential.
    /// This check neither writes bytes nor grants a reusable/one-shot send capability.
    pub fn validate_business_output(
        &self,
        key: &str,
        kind: &str,
        neighbor: &str,
        expected_revision: i64,
    ) -> Result<()> {
        self.writable()?;
        check_ref(key)?;
        if !["data", "evidence"].contains(&kind) {
            return Err(Error::new(Code::InvalidInput, "business output kind"));
        }
        self.data_remaining_at(key, &self.clock)?;
        let revision =
            self.authorize_business_message(key, Some(neighbor), self.clock.monotonic_ms)?;
        if revision != expected_revision {
            return Err(Error::new(
                Code::Conflict,
                "output authorization revision changed",
            ));
        }
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM queues WHERE message_key=?1 AND kind=?2 AND neighbor=?3)",
            params![key, kind, neighbor],
            |r| r.get(0),
        )?;
        if !exists {
            return Err(Error::new(
                Code::Conflict,
                "business output responsibility missing",
            ));
        }
        Ok(())
    }

    /// Capture before verified preparation; checked again at commit/conversion.
    /// This local counter is neither an MLS epoch nor a global revocation timestamp.
    pub fn business_policy_revision(&self, activity: ActivityId) -> Result<i64> {
        self.control_live(&activity, self.clock.monotonic_ms)?;
        self.reject_local_retirement()?;
        Ok(self.conn.query_row(
            "SELECT policy_revision FROM current_control_activity WHERE id=1",
            [],
            |r| r.get(0),
        )?)
    }
    pub(super) fn check_policy_revision(&self, activity: ActivityId, expected: i64) -> Result<()> {
        if expected < 0 || self.business_policy_revision(activity)? != expected {
            return Err(Error::new(
                Code::Conflict,
                "business authorization revision changed",
            ));
        }
        Ok(())
    }
    pub(super) fn active_business_neighbor(
        &self,
        key: &str,
        local: &ParticipantId,
    ) -> Result<CredentialRef> {
        let credential = credential_from_key(key)?;
        let participant: Option<Vec<u8>> = self
            .conn
            .query_row(
                "SELECT participant FROM current_control_bindings WHERE credential=?1 AND state='active'",
                [credential.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        if participant.is_none_or(|p| p == local) {
            return Err(Error::new(Code::Conflict, "business neighbor not active"));
        }
        Ok(credential)
    }
    pub(super) fn authorize_business_core(
        &self,
        core: &PreparedCore,
        role: Role,
        neighbor: Option<&str>,
        now: i64,
    ) -> Result<CredentialRef> {
        let local = self.control_live(&core.identity.activity_id, now)?;
        self.reject_local_retirement()?;
        if self.control_binding(
            &core.identity.origin_credential_ref,
            &core.identity.origin_id,
        )? != BindingState::Active
            || self.control_binding(&core.destination_credential_ref, &core.destination_id)?
                != BindingState::Active
        {
            return Err(Error::new(Code::Conflict, "business endpoint not active"));
        }
        let local_credential: Option<Vec<u8>> = self
            .conn
            .query_row(
                "SELECT credential FROM current_control_bindings WHERE participant=?1 AND state='active'",
                [local.as_slice()],
                |r| r.get(0),
            )
            .optional()?;
        let local_credential: CredentialRef = local_credential
            .ok_or_else(|| Error::new(Code::Conflict, "local business credential not active"))?
            .try_into()
            .map_err(|_| Error::new(Code::StoreCorrupt, "local credential size"))?;
        let correct_role = match role {
            Role::Origin => {
                core.identity.origin_id == local
                    && core.identity.origin_credential_ref == local_credential
            }
            Role::Destination => {
                core.destination_id == local && core.destination_credential_ref == local_credential
            }
            Role::Relay => core.identity.origin_id != local && core.destination_id != local,
        };
        if !correct_role {
            return Err(Error::new(Code::Conflict, "business local role mismatch"));
        }
        if let Some(neighbor) = neighbor {
            self.active_business_neighbor(neighbor, &local)?;
        }
        Ok(local_credential)
    }
    pub(super) fn insert_business_policy(
        &self,
        message: &Message,
        role: Role,
        source: Option<&str>,
        revision: i64,
    ) -> Result<()> {
        self.check_policy_revision(message.data.identity.activity_id, revision)?;
        let local =
            self.authorize_business_core(&message.data, role, source, self.clock.monotonic_ms)?;
        self.conn.execute("UPDATE messages SET policy_revision=?2,local_credential=?3,policy_stopped=0 WHERE key=?1",params![message.key,revision,local.as_slice()])?;
        Ok(())
    }
    /// Re-evaluate a stored responsibility. A previous policy stop is irreversible.
    pub(super) fn authorize_business_message(
        &self,
        key: &str,
        neighbor: Option<&str>,
        now: i64,
    ) -> Result<i64> {
        let core = self.message_core(key)?.ok_or_else(|| {
            Error::new(Code::UnsupportedVersion, "legacy business metadata missing")
        })?;
        let (revision,local,stopped,role,source):(Option<i64>,Option<Vec<u8>>,bool,String,Option<String>)=self.conn.query_row("SELECT policy_revision,local_credential,policy_stopped,role,source_neighbor FROM messages WHERE key=?1",[key],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?)))?;
        if revision.is_none() {
            return Err(Error::new(
                Code::UnsupportedVersion,
                "legacy business policy missing",
            ));
        }
        if stopped {
            return Err(Error::new(
                Code::Conflict,
                "business responsibility stopped by policy",
            ));
        }
        let role = match role.as_str() {
            "origin" => Role::Origin,
            "relay" => Role::Relay,
            "destination" => Role::Destination,
            _ => return Err(Error::new(Code::StoreCorrupt, "business role")),
        };
        let current = self.authorize_business_core(&core, role, source.as_deref(), now)?;
        if local.as_deref() != Some(current.as_slice()) {
            return Err(Error::new(Code::Conflict, "local credential changed"));
        }
        if let Some(neighbor) = neighbor {
            let local = self.control_live(&core.identity.activity_id, now)?;
            self.active_business_neighbor(neighbor, &local)?;
        }
        self.business_policy_revision(core.identity.activity_id)
    }
    pub(super) fn business_policy_changed(&self) -> Result<()> {
        let updated=self.conn.execute("UPDATE control_activity SET policy_revision=policy_revision+1 WHERE activity=(SELECT current_activity FROM meta WHERE id=1) AND policy_revision<9223372036854775807",[])?;
        if updated != 1 {
            return Err(Error::new(
                Code::Quota,
                "business policy revision exhausted",
            ));
        }
        self.reconcile_business_policy(self.clock.monotonic_ms)
    }
    /// Called inside the same transaction as revocation/retirement/clock changes.
    /// Keep payload and history; mark all affected output responsibilities terminal.
    pub(super) fn reconcile_business_policy(&self, now: i64) -> Result<()> {
        self.conn.execute("UPDATE messages AS m SET policy_stopped=1 WHERE m.policy_stopped=0 AND (
            NOT EXISTS(SELECT 1 FROM message_data d JOIN current_control_activity a ON a.activity=d.activity_id
                JOIN current_control_bindings o ON o.credential=d.origin_credential_ref AND o.participant=d.origin_id AND o.state='active'
                JOIN current_control_bindings t ON t.credential=d.destination_credential_ref AND t.participant=d.destination_id AND t.state='active'
                JOIN current_control_bindings l ON l.credential=m.local_credential AND l.participant=a.local_participant AND l.state='active'
                WHERE d.message_key=m.key AND a.stopped=0 AND a.exit_credential IS NULL AND a.deadline>?1)
            OR (m.source_neighbor IS NOT NULL AND NOT EXISTS(SELECT 1 FROM current_control_bindings b WHERE lower(hex(b.credential))=m.source_neighbor AND b.state='active'))
            OR EXISTS(SELECT 1 FROM queues q WHERE q.message_key=m.key AND NOT EXISTS(SELECT 1 FROM current_control_bindings b WHERE lower(hex(b.credential))=q.neighbor AND b.state='active'))
        )",[now])?;
        Ok(())
    }
    pub(super) fn check_business_invariants(&self) -> Result<()> {
        let invalid:bool=self.conn.query_row("SELECT EXISTS(SELECT 1 FROM messages m LEFT JOIN message_data d ON d.message_key=m.key WHERE
            (m.policy_revision IS NULL AND (m.local_credential IS NOT NULL OR m.policy_stopped!=1)) OR
            (m.policy_revision IS NOT NULL AND (m.local_credential IS NULL OR d.message_key IS NULL OR
                NOT EXISTS(SELECT 1 FROM control_activity a JOIN control_bindings l ON l.activity=a.activity AND l.credential=m.local_credential AND l.participant=a.local_participant WHERE a.activity=d.activity_id AND a.policy_revision>=m.policy_revision AND
                ((m.role='origin' AND l.participant=d.origin_id AND l.credential=d.origin_credential_ref) OR
                 (m.role='destination' AND l.participant=d.destination_id AND l.credential=d.destination_credential_ref) OR
                 (m.role='relay' AND l.participant!=d.origin_id AND l.participant!=d.destination_id))) OR
                (m.source_neighbor IS NOT NULL AND NOT EXISTS(SELECT 1 FROM control_bindings b WHERE b.activity=d.activity_id AND lower(hex(b.credential))=m.source_neighbor)) OR
                EXISTS(SELECT 1 FROM queues q WHERE q.message_key=m.key AND NOT EXISTS(SELECT 1 FROM control_bindings b WHERE b.activity=d.activity_id AND lower(hex(b.credential))=q.neighbor)))))",[],|r|r.get(0))?;
        if invalid {
            return Err(Error::new(
                Code::StoreCorrupt,
                "business policy association",
            ));
        }
        Ok(())
    }
}
