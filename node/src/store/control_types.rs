//! Internal, caller-verified D16 records. These types do not authenticate bytes.
//! No CBOR, COSE, hashing, signing, trust UI or transport is implemented here.
use crate::{
    error::{Code, Error, Result},
    retry::{Admission, LinkEvent, Signal},
};

pub const CONTROL_RESERVED_BYTES: u64 = 1024 * 1024;
pub const CONTROL_RESERVED_RECORDS: u32 = 576;
pub const MAX_ACTIVITY_MS: i64 = 12 * 60 * 60 * 1000;
pub type ActivityId = [u8; 32];
pub type CredentialRef = [u8; 32];
pub type ObjectRef = [u8; 32];
pub type ParticipantId = [u8; 16];

pub struct ControlBinding {
    pub participant: ParticipantId,
    pub credential: CredentialRef,
    pub generation: u32,
    /// Exact BindingV1 bytes; validity, hash and owner's confirmation are caller prerequisites.
    pub body: Vec<u8>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BindingState {
    Pending,
    Active,
    Blocked,
    Retiring,
}
impl BindingState {
    pub(super) fn parse(value: &str) -> Result<Self> {
        match value {
            "pending" => Ok(Self::Pending),
            "active" => Ok(Self::Active),
            "blocked" => Ok(Self::Blocked),
            "retiring" => Ok(Self::Retiring),
            _ => Err(Error::new(Code::StoreCorrupt, "control binding state")),
        }
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlKind {
    Exit,
    Report,
}
impl ControlKind {
    pub(super) fn number(self) -> i64 {
        match self {
            Self::Exit => 2,
            Self::Report => 3,
        }
    }
}
/// All decoded fields must correspond to payload and its standard digest reference.
/// A future verified parser supplies this record, never an untrusted public request.
pub struct ControlPayload {
    pub activity: ActivityId,
    pub kind: ControlKind,
    pub issuer: CredentialRef,
    pub issuer_id: ParticipantId,
    pub target: CredentialRef,
    pub target_id: ParticipantId,
    pub operation: [u8; 16],
    pub reason: u8,
    pub reference: ObjectRef,
    pub payload: Vec<u8>,
}
impl ControlPayload {
    pub(super) fn validate(&self) -> Result<()> {
        if self.payload.is_empty()
            || self.payload.len() > 512
            || self.reason > 3
            || (self.kind == ControlKind::Exit
                && (self.issuer != self.target || self.issuer_id != self.target_id))
            || (self.kind == ControlKind::Report && self.issuer_id == self.target_id)
        {
            return Err(Error::new(
                Code::InvalidInput,
                "control payload bounds or kind",
            ));
        }
        Ok(())
    }
}
pub struct PreparedControl {
    pub fields: ControlPayload,
    /// Original strictly encoded, verified COSE bytes, at most 512 bytes.
    pub cose: Vec<u8>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ControlAdmission {
    Inserted(ObjectRef),
    Merged(ObjectRef),
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ControlNeighbor {
    pub participant: ParticipantId,
    pub link: crate::retry::Link,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ControlEvent {
    pub object: ObjectRef,
    pub neighbor: ParticipantId,
    pub link: LinkEvent,
    /// Pause is a caller-authenticated persistent ACK; Stop is a policy stop. Both are terminal.
    pub signal: Signal,
    pub admission: Admission,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ControlProgress {
    pub slots_consumed: u8,
    pub recoveries_consumed: u8,
    pub attempts: u8,
    pub ack_attempts: u8,
    pub terminal: bool,
}
pub struct ControlDecision {
    pub object: ObjectRef,
    pub neighbor: ParticipantId,
    /// Only returned after COMMIT. Recheck authorization/time at future transport handoff.
    pub send: bool,
    pub progress: ControlProgress,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ControlUsage {
    pub reserved_bytes: u64,
    pub reserved_records: u32,
    pub used_bytes: u64,
    pub used_records: u64,
    pub bindings: u64,
    pub objects: u64,
    pub neighbors: u64,
}
