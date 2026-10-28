//! D15 prepared fields and conservative time arithmetic; no CBOR or cryptography.
//! A future authenticated decoder must bind these fields to the exact raw bytes.
use crate::{
    error::{Code, Error, Result},
    model::Clock,
};

pub const MAX_CORE: usize = 512;
pub const MAX_MLS_MESSAGE: usize = 61440;
pub const MAX_LIFETIME_MS: i64 = 3600000;
pub const MAX_UTC_WIDTH_MS: i64 = 2000;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct UtcInterval {
    pub lower_ms: i64,
    pub upper_ms: i64,
}
impl UtcInterval {
    pub fn validate(self) -> Result<()> {
        if self.lower_ms < 0 || self.upper_ms < self.lower_ms {
            return Err(Error::new(Code::InvalidInput, "UTC interval bounds"));
        }
        if self.upper_ms - self.lower_ms > MAX_UTC_WIDTH_MS {
            return Err(Error::new(Code::TimeUncertain, "UTC interval width"));
        }
        Ok(())
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct MessageIdentity {
    pub activity_id: [u8; 32],
    pub origin_id: [u8; 16],
    pub origin_credential_ref: [u8; 32],
    pub message_id: [u8; 16],
}

/// The type fixes version=1, kind=1, priority=0 and content_type=1.
/// This is a prepared record, never evidence of successful authentication/decoding.
#[derive(Clone, PartialEq, Eq)]
pub struct PreparedCore {
    pub raw: Vec<u8>,
    pub identity: MessageIdentity,
    pub destination_id: [u8; 16],
    pub destination_credential_ref: [u8; 32],
    pub mls_group_id: [u8; 32],
    pub mls_epoch: u64,
    pub originated_at_ms: i64,
    pub lifetime_ms: i64,
    pub initial_hops: u8,
}
impl PreparedCore {
    /// Stable quota scope; supplied aliases cannot split one credential's allowance.
    pub fn origin_ref(&self) -> String {
        self.identity
            .origin_credential_ref
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect()
    }
    pub fn not_after_ms(&self) -> Result<i64> {
        if self.raw.is_empty()
            || self.raw.len() > MAX_CORE
            || self.identity.origin_id == self.destination_id
            || self.originated_at_ms < 0
            || !(1..=MAX_LIFETIME_MS).contains(&self.lifetime_ms)
            || !(1..=2).contains(&self.initial_hops)
        {
            return Err(Error::new(Code::InvalidInput, "D15 core bounds"));
        }
        self.originated_at_ms
            .checked_add(self.lifetime_ms)
            .ok_or_else(|| Error::new(Code::InvalidInput, "D15 not-after overflow"))
    }

    /// Map one trusted simultaneous UTC/BOOTTIME sample, checking every addition.
    /// Origin supplies None; receivers supply the frame's remaining lifetime.
    pub fn deadline(
        &self,
        clock: &Clock,
        received_ms: Option<i64>,
        local_cap_ms: i64,
    ) -> Result<i64> {
        clock.validate()?;
        let utc = clock
            .trusted_utc
            .ok_or_else(|| Error::new(Code::TimeUncertain, "D15 trusted UTC required"))?;
        let not_after = self.not_after_ms()?;
        if self.originated_at_ms > utc.upper_ms {
            return Err(Error::new(Code::TimeUncertain, "D15 future origin time"));
        }
        if utc.upper_ms >= not_after {
            return Err(Error::new(Code::Expired, "D15 UTC deadline"));
        }
        if !(1..=MAX_LIFETIME_MS).contains(&local_cap_ms)
            || received_ms.is_some_and(|v| !(1..=MAX_LIFETIME_MS).contains(&v))
        {
            return Err(Error::new(Code::InvalidInput, "D15 remaining lifetime"));
        }
        let remaining = (not_after - utc.upper_ms)
            .min(local_cap_ms)
            .min(received_ms.unwrap_or(MAX_LIFETIME_MS));
        clock
            .monotonic_ms
            .checked_add(remaining)
            .ok_or_else(|| Error::new(Code::InvalidInput, "D15 monotonic deadline overflow"))
    }
}
