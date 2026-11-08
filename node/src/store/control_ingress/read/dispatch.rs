//! Owner-side routing of prepared decoder results. No wire decoder is installed here.
use super::*;
use crate::data::{MAX_CORE, MAX_MLS_MESSAGE};
use std::ops::Range;

const MAX_DATA_BODY: usize = 61_704;
const MAX_COSE_BODY: usize = 518;
const LINK_ACK_BODY: usize = 123;

/// Internal handoff from a strict decoder. Ranges refer to the exact frame body.
/// The offline caller supplies synthetic results while D14 remains gated.
pub enum DecodedInbound {
    Data {
        core: Range<usize>,
        mls: Range<usize>,
    },
    Receipt {
        cose: Range<usize>,
    },
    /// Structurally valid COSE inner kind 2 or 3, still awaiting verification.
    Control {
        cose: Range<usize>,
    },
    LinkAck {
        activity: ActivityId,
        custodian: ParticipantId,
        credential: CredentialRef,
        /// A data target also carries the caller's resolved internal message key.
        target: OutboundTerminalAck,
    },
}

/// Independently available backing bytes for this synchronous consumer call.
/// Zero closes the corresponding lane. Neither lane queues frames in Store.
#[derive(Default)]
pub struct InboundPayloadCredit {
    pub data: usize,
    pub receipt: usize,
}

pub enum InboundPayload<'a> {
    Data { core: &'a [u8], mls: &'a [u8] },
    Receipt { cose: &'a [u8] },
}

#[derive(Debug, PartialEq, Eq)]
pub enum InboundDispatch {
    Payload,
    PayloadFull,
    Control {
        admission: ControlIngressAdmission,
        ack: OutboundAckAdmission,
    },
    LinkAck(OutboundTerminalAdmission),
}

impl Store {
    /// Consumes the original frame even on rejection. Decoding is a synchronous
    /// borrowed step followed by a fresh owner sample. The payload callback
    /// borrows slices for this step; copies or async work need separate credit.
    pub fn dispatch_inbound_frame(
        &mut self,
        frame: InboundFrame,
        decode: impl FnOnce(&[u8]) -> Result<DecodedInbound>,
        sample_after: impl FnOnce() -> Result<Clock>,
        credit: InboundPayloadCredit,
        payload: impl FnOnce(OutboundChannel, InboundPayload<'_>) -> Result<()>,
    ) -> Result<InboundDispatch> {
        self.require_control_channel_owner(&frame.owner)?;
        let channel = frame.channel;
        self.ingress.require_channel(&channel)?;
        self.writable()?;
        let body = frame.body.as_slice();
        let decoded = decode(body);
        let clock = sample_after().inspect_err(|_| self.time_uncertain = true)?;
        self.observe_clock(&clock)?;
        // A change of activity or clock domain replaces the registry and its owner.
        let activity = self.current_activity_id()?;
        self.check_registered_channel(activity, &channel, clock.monotonic_ms)?;
        let source = ControlIngressChannel {
            owner: frame.owner,
            activity,
            binding: channel,
        };
        let (item, available) = match decoded? {
            DecodedInbound::Data { core, mls } => {
                if body.len() > MAX_DATA_BODY || core.end > mls.start {
                    return Err(Error::new(Code::InvalidInput, "inbound data layout"));
                }
                let core = inbound_bytes(body, core, MAX_CORE)?;
                let mls = inbound_bytes(body, mls, MAX_MLS_MESSAGE)?;
                (InboundPayload::Data { core, mls }, credit.data)
            }
            DecodedInbound::Receipt { cose } => (
                InboundPayload::Receipt {
                    cose: cose_bytes(body, cose)?,
                },
                credit.receipt,
            ),
            DecodedInbound::Control { cose } => {
                let bytes = cose_bytes(body, cose)?;
                let (admission, ack) = self.queue_control_candidate_on_channel(&source, bytes)?;
                return Ok(InboundDispatch::Control { admission, ack });
            }
            DecodedInbound::LinkAck {
                activity: claimed_activity,
                custodian,
                credential,
                target,
            } => {
                if body.len() != LINK_ACK_BODY {
                    return Err(Error::new(Code::InvalidInput, "inbound LinkAck size"));
                }
                if claimed_activity != activity
                    || custodian != channel.peer
                    || credential != channel.peer_credential
                {
                    return Err(Error::new(Code::Conflict, "inbound LinkAck source binding"));
                }
                return self
                    .accept_outbound_terminal(&source, target, clock)
                    .map(InboundDispatch::LinkAck);
            }
        };
        if frame.body.capacity() > available {
            return Ok(InboundDispatch::PayloadFull);
        }
        payload(channel, item)?;
        Ok(InboundDispatch::Payload)
    }
}

fn cose_bytes(body: &[u8], range: Range<usize>) -> Result<&[u8]> {
    if body.len() > MAX_COSE_BODY || range.end != body.len() {
        return Err(Error::new(Code::InvalidInput, "inbound COSE envelope"));
    }
    inbound_bytes(body, range, MAX_CONTROL_BYTES)
}

fn inbound_bytes(body: &[u8], range: Range<usize>, max: usize) -> Result<&[u8]> {
    body.get(range)
        .filter(|bytes| !bytes.is_empty() && bytes.len() <= max)
        .ok_or_else(|| Error::new(Code::InvalidInput, "inbound decoded byte range"))
}

#[cfg(test)]
mod tests;
