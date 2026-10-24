//! Bounded application framing for already authorized neighbor streams.
//!
//! This module does not open transports, authenticate peers, decode CBOR/MLS, or
//! grant custody. The caller must supply a trusted same-boot clock and must stop
//! polling a stream after it is removed. Completed frames still need protocol,
//! authorization, lifetime and transaction checks before any external effect.
use crate::{
    error::{Code, Error, Result},
    model::Clock,
};
use std::collections::BTreeMap;

pub const MAX_FRAME_BYTES: usize = 65_536;
pub const MAX_BODY_BYTES: usize = MAX_FRAME_BYTES - 4;
pub const MAX_NEIGHBORS: usize = 4;
pub const ASSEMBLY_TIMEOUT_MS: i64 = 10_000;

/// An application binding supplied by the authenticated transport owner.
/// This identifier by itself is not an authentication result.
pub type Neighbor = [u8; 16];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Progress {
    /// Input bytes consumed, stopping at the first complete frame.
    pub consumed: usize,
    pub complete: bool,
}

#[derive(Default)]
struct Assembly {
    prefix: [u8; 4],
    prefix_len: usize,
    started_ms: Option<i64>,
    expected: Option<usize>,
    body: Vec<u8>,
}

impl Assembly {
    fn complete(&self) -> bool {
        self.expected.is_some_and(|len| self.body.len() == len)
    }

    fn expired(&self, now_ms: i64) -> bool {
        !self.complete()
            && self
                .started_ms
                .is_some_and(|start| now_ms - start >= ASSEMBLY_TIMEOUT_MS)
    }

    fn push(&mut self, now_ms: i64, input: &[u8]) -> Result<Progress> {
        if self.complete() {
            return Err(Error::new(Code::Busy, "frame awaiting consumption"));
        }
        if input.is_empty() {
            return Ok(Progress {
                consumed: 0,
                complete: false,
            });
        }
        self.started_ms.get_or_insert(now_ms);
        let mut consumed = 0;
        if self.prefix_len < 4 {
            let count = (4 - self.prefix_len).min(input.len());
            self.prefix[self.prefix_len..self.prefix_len + count].copy_from_slice(&input[..count]);
            self.prefix_len += count;
            consumed += count;
            if self.prefix_len < 4 {
                return Ok(Progress {
                    consumed,
                    complete: false,
                });
            }
            let len = u32::from_be_bytes(self.prefix) as usize;
            if len == 0 || len > MAX_BODY_BYTES {
                return Err(Error::new(Code::InvalidInput, "frame body length"));
            }
            self.body.try_reserve_exact(len).map_err(|error| {
                Error::source_error(Code::Quota, "frame buffer allocation", error)
            })?;
            // Vec may overallocate. Keep the logical capacity bound explicit.
            if self.body.capacity() > MAX_BODY_BYTES {
                return Err(Error::new(Code::Quota, "frame buffer capacity"));
            }
            self.expected = Some(len);
        }
        let remaining = self.expected.expect("validated complete prefix") - self.body.len();
        let count = remaining.min(input.len() - consumed);
        self.body
            .extend_from_slice(&input[consumed..consumed + count]);
        consumed += count;
        Ok(Progress {
            consumed,
            complete: self.complete(),
        })
    }
}

/// Owns at most one partial or completed frame for each of four neighbors.
/// No Debug implementation: buffers and bindings must not be logged.
pub struct Ingress {
    boot: String,
    last_ms: i64,
    failed: bool,
    streams: BTreeMap<Neighbor, Assembly>,
}

impl Ingress {
    pub fn new(clock: &Clock) -> Result<Self> {
        clock.validate()?;
        Ok(Self {
            boot: clock.boot.clone(),
            last_ms: clock.monotonic_ms,
            failed: false,
            streams: BTreeMap::new(),
        })
    }

    /// Must be called only after the transport owner validates the peer binding.
    /// Reopening an occupied neighbor never resets its in-flight frame or timer.
    pub fn open(&mut self, neighbor: Neighbor, clock: &Clock) -> Result<()> {
        self.observe(clock)?;
        if self.streams.contains_key(&neighbor) {
            return Err(Error::new(Code::Conflict, "neighbor stream already open"));
        }
        if self.streams.len() >= MAX_NEIGHBORS {
            return Err(Error::new(Code::Quota, "neighbor stream count"));
        }
        self.streams.insert(neighbor, Assembly::default());
        Ok(())
    }

    /// Removal is explicit; the caller must also close its corresponding stream.
    pub fn close(&mut self, neighbor: &Neighbor) {
        self.streams.remove(neighbor);
    }

    /// Consume at most the first frame. The caller retains any unconsumed input.
    /// Malformed/expired input removes this stream; Busy retains the ready frame.
    pub fn push(&mut self, neighbor: &Neighbor, clock: &Clock, input: &[u8]) -> Result<Progress> {
        self.observe(clock)?;
        let stream = self
            .streams
            .get_mut(neighbor)
            .ok_or_else(|| Error::new(Code::Stopped, "neighbor stream not open"))?;
        if stream.expired(clock.monotonic_ms) {
            self.streams.remove(neighbor);
            return Err(Error::new(Code::Expired, "frame assembly deadline"));
        }
        let result = stream.push(clock.monotonic_ms, input);
        if result.as_ref().is_err_and(|error| error.code != Code::Busy) {
            self.streams.remove(neighbor);
        }
        result
    }

    /// Transfer the ready buffer to the next bounded processing stage.
    /// Its subsequent memory charge belongs to that stage, not this ingress.
    pub fn take(&mut self, neighbor: &Neighbor, clock: &Clock) -> Result<Option<Vec<u8>>> {
        self.observe(clock)?;
        let stream = self
            .streams
            .get_mut(neighbor)
            .ok_or_else(|| Error::new(Code::Stopped, "neighbor stream not open"))?;
        if stream.expired(clock.monotonic_ms) {
            self.streams.remove(neighbor);
            return Err(Error::new(Code::Expired, "frame assembly deadline"));
        }
        if !stream.complete() {
            return Ok(None);
        }
        let body = std::mem::take(&mut stream.body);
        *stream = Assembly::default();
        Ok(Some(body))
    }

    /// Periodic same-boot maintenance. Returned peers must have their streams closed.
    pub fn expire(&mut self, clock: &Clock) -> Result<Vec<Neighbor>> {
        self.observe(clock)?;
        let expired: Vec<_> = self
            .streams
            .iter()
            .filter_map(|(peer, stream)| stream.expired(clock.monotonic_ms).then_some(*peer))
            .collect();
        for peer in &expired {
            self.streams.remove(peer);
        }
        Ok(expired)
    }

    pub fn stream_count(&self) -> usize {
        self.streams.len()
    }

    /// Logical body capacity plus four prefix bytes per allocated stream.
    /// This is not an allocator/RSS or encrypted transport buffer measurement.
    pub fn buffered_capacity(&self) -> usize {
        self.streams
            .values()
            .map(|stream| 4 + stream.body.capacity())
            .sum()
    }

    fn observe(&mut self, clock: &Clock) -> Result<()> {
        if self.failed {
            return Err(Error::new(Code::TimeUncertain, "ingress clock quarantined"));
        }
        if clock.validate().is_err() || clock.boot != self.boot || clock.monotonic_ms < self.last_ms
        {
            self.failed = true;
            self.streams.clear();
            return Err(Error::new(Code::TimeUncertain, "ingress clock continuity"));
        }
        self.last_ms = clock.monotonic_ms;
        Ok(())
    }
}

#[cfg(test)]
mod tests;
