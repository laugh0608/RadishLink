use super::control_types::*;
use super::*;

struct StoredControl {
    reference: Vec<u8>,
    payload: Vec<u8>,
    kind: i64,
    target: Vec<u8>,
    reason: u8,
}

impl Store {
    /// Commits one fixed unsigned local exit intent and Retiring before any future signer runs.
    pub fn begin_control_exit(&mut self, fields: ControlPayload) -> Result<()> {
        fields.validate()?;
        self.atomic(|s| {
            let local=s.control_live(&fields.activity,s.clock.monotonic_ms)?;
            if fields.kind!=ControlKind::Exit || fields.issuer_id!=local {
                return Err(Error::new(Code::InvalidInput,"local exit identity"));
            }
            if let Some(saved)=s.control_exit_intent(fields.activity)? {
                if Self::same_control_payload(&saved,&fields) { return Ok(()); }
                return Err(Error::new(Code::Conflict,"local exit intent already fixed"));
            }
            if s.control_binding(&fields.issuer,&local)?!=BindingState::Active {
                return Err(Error::new(Code::Conflict,"local exit not active"));
            }
            s.conn.execute("UPDATE control_activity SET exit_credential=?1,exit_operation=?2,exit_ref=?3,exit_payload=?4,exit_reason=?5 WHERE id=1",params![fields.issuer.as_slice(),fields.operation.as_slice(),fields.reference.as_slice(),fields.payload,fields.reason])?;
            s.conn.execute("UPDATE control_bindings SET state='retiring' WHERE credential=?1",[fields.issuer.as_slice()])?;
            Ok(())
        })
    }
    /// Only a still-Retiring intent is eligible for a future signer; retained completed or
    /// owner-blocked intent bytes never reopen signing authorization.
    pub fn control_exit_intent(&self, activity: ActivityId) -> Result<Option<ControlPayload>> {
        let local = self.control_live(&activity, self.clock.monotonic_ms)?;
        let row=self.conn.query_row("SELECT exit_credential,exit_operation,exit_ref,exit_payload,exit_reason FROM control_activity WHERE id=1 AND exit_credential IS NOT NULL AND EXISTS(SELECT 1 FROM control_bindings b WHERE b.credential=exit_credential AND b.state='retiring')",[],|r| {
            Ok((r.get::<_,Vec<u8>>(0)?,r.get::<_,Vec<u8>>(1)?,r.get::<_,Vec<u8>>(2)?,r.get::<_,Vec<u8>>(3)?,r.get::<_,u8>(4)?))
        }).optional()?;
        row.map(|(c, o, r, p, reason)| {
            let invalid = || Error::new(Code::StoreCorrupt, "exit intent encoding");
            let issuer = c.try_into().map_err(|_| invalid())?;
            Ok(ControlPayload {
                activity,
                kind: ControlKind::Exit,
                issuer,
                issuer_id: local,
                target: issuer,
                target_id: local,
                operation: o.try_into().map_err(|_| invalid())?,
                reference: r.try_into().map_err(|_| invalid())?,
                payload: p,
                reason,
            })
        })
        .transpose()
    }
    fn same_control_payload(a: &ControlPayload, b: &ControlPayload) -> bool {
        a.activity == b.activity
            && a.kind == b.kind
            && a.issuer == b.issuer
            && a.issuer_id == b.issuer_id
            && a.target == b.target
            && a.target_id == b.target_id
            && a.operation == b.operation
            && a.reason == b.reason
            && a.reference == b.reference
            && a.payload == b.payload
    }
    /// Caller-verified objects only. No signature or payload digest is computed or trusted here.
    /// Persists policy, original object and all forwarding responsibilities in one transaction.
    pub fn accept_control(
        &mut self,
        object: PreparedControl,
        neighbors: &[ControlNeighbor],
    ) -> Result<ControlAdmission> {
        object.fields.validate()?;
        if object.cose.is_empty() || object.cose.len() > 512 || neighbors.len() > 4 {
            return Err(Error::new(
                Code::InvalidInput,
                "control object or neighbor bounds",
            ));
        }
        self.atomic(|s| {
            let f=&object.fields;
            let local=s.control_live(&f.activity,s.clock.monotonic_ms)?;
            let issuer=s.control_binding(&f.issuer,&f.issuer_id)?;
            let target=s.control_binding(&f.target,&f.target_id)?;
            if issuer==BindingState::Pending || target==BindingState::Pending {
                return Err(Error::new(Code::Conflict,"control requires verified binding"));
            }
            let existing=s.conn.query_row(
                "SELECT reference,payload,kind,target,reason FROM control_objects WHERE issuer=?1 AND operation=?2",
                params![f.issuer.as_slice(),f.operation.as_slice()],
                |r|Ok(StoredControl {reference:r.get(0)?,payload:r.get(1)?,kind:r.get(2)?,target:r.get(3)?,reason:r.get(4)?})
            ).optional()?;
            if let Some(StoredControl{reference,payload,kind,target,reason})=existing {
                if reference!=f.reference || payload!=f.payload || kind!=f.kind.number() || target!=f.target || reason!=f.reason {
                    return Err(Error::new(Code::Conflict,"control operation payload conflict"));
                }
                // Semantic duplicate: retain first original bytes, slots and attempts.
                return Ok(ControlAdmission::Merged(f.reference));
            }
            let prior:Option<Vec<u8>>=s.conn.query_row("SELECT reference FROM control_objects WHERE kind=?1 AND target=?2 AND (?1=2 OR reporter=?3)",params![f.kind.number(),f.target.as_slice(),f.issuer_id.as_slice()],|r|r.get(0)).optional()?;
            if let Some(reference)=prior {
                // A blocked issuer cannot submit a new report; the existing exit stays merged.
                if f.kind==ControlKind::Report && issuer!=BindingState::Active {
                    return Err(Error::new(Code::Conflict,"report issuer no longer active"));
                }
                return Ok(ControlAdmission::Merged(reference.try_into().map_err(|_|Error::new(Code::StoreCorrupt,"object reference size"))?));
            }
            if f.kind==ControlKind::Exit && f.issuer_id==local {
                let intent=s.control_exit_intent(f.activity)?.ok_or_else(||Error::new(Code::Conflict,"local exit intent required"))?;
                if issuer!=BindingState::Retiring || !Self::same_control_payload(&intent,f) {
                    return Err(Error::new(Code::Conflict,"signed exit differs from fixed intent"));
                }
            } else if issuer!=BindingState::Active || !s.participant_active(&local)? {
                return Err(Error::new(Code::Conflict,"control authorization changed"));
            }
            let collision:bool=s.conn.query_row("SELECT EXISTS(SELECT 1 FROM control_objects WHERE reference=?1)",[f.reference.as_slice()],|r|r.get(0))?;
            if collision { return Err(Error::new(Code::Conflict,"control reference already assigned")); }
            s.conn.execute("INSERT INTO control_objects VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",params![f.reference.as_slice(),f.kind.number(),f.issuer.as_slice(),f.issuer_id.as_slice(),f.target.as_slice(),f.operation.as_slice(),f.reason,f.payload,object.cose,s.clock.monotonic_ms])?;
            // Create neighbor rows before applying exit so the issuer's former trusted channel
            // may retain a terminal slot; output always rechecks the current channel policy.
            for neighbor in neighbors { s.insert_control_neighbor(f.activity,f.reference,*neighbor)?; }
            if f.kind==ControlKind::Exit {
                s.conn.execute("UPDATE control_bindings SET state='blocked' WHERE credential=?1",[f.issuer.as_slice()])?;
            }
            Ok(ControlAdmission::Inserted(f.reference))
        })
    }
    pub(super) fn insert_control_neighbor(
        &self,
        activity: ActivityId,
        object: ObjectRef,
        neighbor: ControlNeighbor,
    ) -> Result<()> {
        let local = self.control_live(&activity, self.clock.monotonic_ms)?;
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM control_neighbors WHERE object=?1 AND participant=?2)",
            params![object.as_slice(), neighbor.participant.as_slice()],
            |r| r.get(0),
        )?;
        if exists {
            return Ok(());
        }
        if neighbor.participant == local || !self.participant_active(&neighbor.participant)? {
            return Err(Error::new(Code::Conflict, "forward neighbor not active"));
        }
        let exists: bool = self.conn.query_row(
            "SELECT EXISTS(SELECT 1 FROM control_objects WHERE reference=?1)",
            [object.as_slice()],
            |r| r.get(0),
        )?;
        if !exists {
            return Err(Error::new(Code::Conflict, "control object missing"));
        }
        self.conn.execute(
            "INSERT INTO control_neighbors(object,participant,start,link_up) VALUES(?1,?2,?3,?4)",
            params![
                object.as_slice(),
                neighbor.participant.as_slice(),
                self.clock.monotonic_ms,
                neighbor.link == Link::Up
            ],
        )?;
        Ok(())
    }
    /// A new trusted neighbor gets one slot; duplicates, new addresses and credentials reuse it.
    pub fn schedule_control_neighbor(
        &mut self,
        activity: ActivityId,
        object: ObjectRef,
        neighbor: ControlNeighbor,
    ) -> Result<()> {
        self.atomic(|s| s.insert_control_neighbor(activity, object, neighbor))
    }
    /// Original immutable bytes for a future authorized transport handoff, never a new signature.
    pub fn control_object(
        &self,
        activity: ActivityId,
        object: ObjectRef,
    ) -> Result<Option<Vec<u8>>> {
        self.control_live(&activity, self.clock.monotonic_ms)?;
        Ok(self
            .conn
            .query_row(
                "SELECT body FROM control_objects WHERE reference=?1",
                [object.as_slice()],
                |r| r.get(0),
            )
            .optional()?)
    }
}
