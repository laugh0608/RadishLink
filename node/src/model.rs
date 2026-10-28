//! Storage/application records; these are not wire formats or authentication results.
use crate::error::{Code, Error, Result};

pub const MAX_TEXT: usize = 4096;
pub const MAX_PAYLOAD: usize = 65536;
pub const MAX_CONTROL: usize = 4096;
pub const MAX_SECURITY_STATE: usize = 65536;
pub const HISTORY_MS: i64 = 7 * 24 * 60 * 60 * 1000;

pub fn check_ref(value: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-:.".contains(&b))
    {
        return Err(Error::new(Code::InvalidInput, "record reference"));
    }
    Ok(())
}
pub fn check_text(body: &[u8]) -> Result<()> {
    if body.is_empty() || body.len() > MAX_TEXT || std::str::from_utf8(body).is_err() {
        return Err(Error::new(Code::InvalidInput, "UTF-8 text size"));
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Role {
    Origin,
    Relay,
    Destination,
}
impl Role {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Origin => "origin",
            Self::Relay => "relay",
            Self::Destination => "destination",
        }
    }
}

/// Prepared by a future authenticated protocol layer, never accepted from public API input.
/// The storage layer checks consistency, not authenticity.
pub struct Message {
    pub key: String,
    pub core_binding: Vec<u8>,
    pub data: crate::data::PreparedCore,
    pub payload: Vec<u8>,
    pub deadline_ms: i64,
    pub retain_until_ms: i64,
}
impl Message {
    pub fn validate(&self, now_ms: i64) -> Result<()> {
        check_ref(&self.key)?;
        if self.core_binding.len() != 32
            || self.payload.is_empty()
            || self.payload.len() > crate::data::MAX_MLS_MESSAGE
            || self.retain_until_ms < self.deadline_ms
        {
            return Err(Error::new(Code::InvalidInput, "message bounds"));
        }
        if self.deadline_ms <= now_ms {
            return Err(Error::new(Code::Expired, "message deadline"));
        }
        Ok(())
    }
}
pub struct Action {
    pub scope: String,
    pub generation: i64,
    pub reference: String,
    pub binding: Vec<u8>,
}
impl Action {
    pub fn validate(&self) -> Result<()> {
        check_ref(&self.scope)?;
        check_ref(&self.reference)?;
        if self.generation < 1 || self.binding.is_empty() || self.binding.len() > 512 {
            return Err(Error::new(Code::InvalidInput, "action binding"));
        }
        Ok(())
    }
}
pub struct SecurityUpdate {
    pub session: String,
    pub expected_revision: i64,
    pub state: Vec<u8>,
}
impl SecurityUpdate {
    pub fn validate(&self) -> Result<()> {
        check_ref(&self.session)?;
        if self.expected_revision < 0
            || self.expected_revision == i64::MAX
            || self.state.is_empty()
            || self.state.len() > MAX_SECURITY_STATE
        {
            return Err(Error::new(Code::InvalidInput, "security state bounds"));
        }
        Ok(())
    }
}
pub struct Send {
    pub expected_policy_revision: i64,
    pub action: Action,
    pub message: Message,
    pub security: SecurityUpdate,
    pub text: Vec<u8>,
    pub neighbor: String,
    pub remaining_hops: u8,
}
pub struct Receive {
    pub expected_policy_revision: i64,
    pub remaining_lifetime_ms: i64,
    pub message: Message,
    pub role: Role,
    pub neighbor: String,
    pub remaining_hops: u8,
    pub security: Option<SecurityUpdate>,
    pub text: Option<Vec<u8>>,
    /// Reconstructible unsigned intent. Never an already produced delivery proof.
    pub receipt_intent: Option<Vec<u8>>,
}

/// Committed input for a future signer, not a signature or permission to send.
/// Deliberately does not implement Debug: the application-defined body is private.
pub struct ReceiptIntent {
    pub policy_revision: i64,
    pub key: String,
    pub core_binding: Vec<u8>,
    pub body: Vec<u8>,
    pub neighbor: String,
    pub deadline_ms: i64,
}

/// Does not contain plaintext or secret state, including in Debug output.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MessageView {
    pub policy_stopped: bool,
    pub key: String,
    pub source_neighbor: Option<String>,
    pub state: String,
    pub payload_present: bool,
    pub custody_observed: bool,
    pub evidence_pending: bool,
    pub receipt_intent_pending: bool,
}
pub struct HistoryItem {
    pub sequence: i64,
    pub key: String,
    pub text: Vec<u8>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Clock {
    pub boot: String,
    pub monotonic_ms: i64,
    /// Only a trusted platform clock may populate this; no network clock is implemented.
    pub trusted_utc: Option<crate::data::UtcInterval>,
}
impl Clock {
    pub fn utc_lower_ms(&self) -> Option<i64> {
        self.trusted_utc.map(|v| v.lower_ms)
    }
    pub fn utc_upper_ms(&self) -> Option<i64> {
        self.trusted_utc.map(|v| v.upper_ms)
    }
    pub fn validate(&self) -> Result<()> {
        check_ref(&self.boot)?;
        if self.monotonic_ms < 0 {
            return Err(Error::new(Code::InvalidInput, "clock bounds"));
        }
        if let Some(utc) = self.trusted_utc {
            utc.validate()?;
        }
        Ok(())
    }
}
