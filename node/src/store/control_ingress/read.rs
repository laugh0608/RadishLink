//! One synchronous read from an authenticated application stream.
use super::*;
use crate::framing::Ingress;
use std::io;

const READ_CHUNK_BYTES: usize = 4096;

/// A frame whose backing storage has been transferred to a reserved downstream slot.
pub struct InboundFrame {
    pub channel: OutboundChannel,
    pub body: Vec<u8>,
}

pub enum InboundReadProgress {
    /// No ready instance remains after this step's maintenance.
    Idle,
    /// A read was attempted and no frame was completed. Recheck readiness next step.
    Pending,
    /// Downstream declined the reservation for a complete frame.
    Discarded,
    Frame(InboundFrame),
}

pub struct InboundReadStep {
    pub result: Result<InboundReadProgress>,
    /// Newly fenced instances, with the reason to close their original transport.
    pub closing: Vec<(OutboundChannel, Error)>,
}

impl Store {
    /// Opens framing on a previously registered handle. An open failure fences that
    /// instance and the caller retains the handle for actual closure confirmation.
    pub fn open_inbound_stream(
        &mut self,
        channel: &ControlIngressChannel,
        clock: &Clock,
    ) -> Result<()> {
        let (activity, binding) = self.control_ingress_channel(channel)?;
        if self.ingress.channels[&binding.peer].read_ready.is_some() {
            return Err(Error::new(Code::Conflict, "inbound stream already open"));
        }
        let result = (|| {
            self.validate_clock_advance(clock)?;
            self.check_registered_channel(activity, &binding, clock.monotonic_ms)?;
            let framing = match &mut self.ingress.framing {
                Some(framing) => framing,
                empty @ None => empty.insert(Ingress::new(clock)?),
            };
            framing.open(binding.peer, clock)
        })();
        if let Err(error) = result {
            self.time_uncertain |= error.code == Code::TimeUncertain;
            self.fence_control_channel(binding);
            return Err(error);
        }
        self.registered_control_channel(channel)?.read_ready = Some(false);
        Ok(())
    }

    pub fn mark_inbound_ready(&mut self, channel: &ControlIngressChannel) -> Result<()> {
        self.require_owner_running()?;
        self.control_ingress_channel(channel)?;
        let ready = self
            .registered_control_channel(channel)?
            .read_ready
            .as_mut()
            .ok_or_else(|| Error::new(Code::Stopped, "inbound stream not open"))?;
        *ready = true;
        Ok(())
    }

    /// Services deadlines even without readiness. At most one instance is read per call.
    /// All callbacks run synchronously under the owning caller and must be bounded.
    /// A successful reservation covers the body capacity until the recipient drops it.
    pub fn poll_inbound(
        &mut self,
        before: &Clock,
        read: impl FnOnce(OutboundChannel, &mut [u8]) -> io::Result<usize>,
        sample_after: impl FnOnce() -> Result<Clock>,
        reserve: impl FnOnce(OutboundChannel, usize) -> bool,
    ) -> InboundReadStep {
        let mut closing = Vec::new();
        let result = (|| {
            self.maintain_inbound(before, &mut closing)?;
            let mut ready = self
                .ingress
                .channels
                .values()
                .filter(|entry| entry.read_ready == Some(true));
            let Some(first) = ready.next() else {
                return Ok(InboundReadProgress::Idle);
            };
            let channel = std::iter::once(first)
                .chain(ready)
                .find(|entry| Some(entry.binding.peer) > self.ingress.last_read_peer)
                .unwrap_or(first)
                .binding;
            self.ingress.last_read_peer = Some(channel.peer);
            let mut scratch = [0; READ_CHUNK_BYTES];
            let credit = self
                .ingress
                .framing
                .as_ref()
                .expect("attached framing")
                .read_credit(&channel.peer)
                .expect("attached frame slot")
                .min(scratch.len());
            assert!(
                credit > 0,
                "each completed inbound frame is consumed in its read step"
            );
            let read_result = read(channel, &mut scratch[..credit]);
            let sampled = sample_after().and_then(|clock| {
                if clock.precedes(before) {
                    Err(Error::new(
                        Code::TimeUncertain,
                        "inbound clock regression after read",
                    ))
                } else {
                    Ok(clock)
                }
            });
            let after = match sampled {
                Ok(clock) => clock,
                Err(error) => {
                    self.time_uncertain = true;
                    self.fence_inbound_channels(
                        self.attached_inbound_channels(),
                        &error,
                        &mut closing,
                    );
                    return Err(error);
                }
            };
            self.maintain_inbound(&after, &mut closing)?;
            if self.ingress.channels[&channel.peer].closing {
                return Ok(InboundReadProgress::Pending);
            }
            if let Err(error) =
                self.apply_inbound_read(channel, &after, &scratch[..credit], read_result)
            {
                self.fence_control_channel(channel);
                closing.push((channel, error));
                return Ok(InboundReadProgress::Pending);
            }

            let framing = self.ingress.framing.as_mut().expect("attached framing");
            let Some(capacity) = framing.ready_capacity(&channel.peer) else {
                return Ok(InboundReadProgress::Pending);
            };
            let reserved = reserve(channel, capacity);
            let body = framing.take(&channel.peer, &after)?.expect("ready frame");
            Ok(if reserved {
                InboundReadProgress::Frame(InboundFrame { channel, body })
            } else {
                InboundReadProgress::Discarded
            })
        })();
        InboundReadStep { result, closing }
    }

    fn maintain_inbound(
        &mut self,
        clock: &Clock,
        closing: &mut Vec<(OutboundChannel, Error)>,
    ) -> Result<()> {
        let result = (|| {
            self.validate_clock_advance(clock)?;
            match &mut self.ingress.framing {
                Some(framing) => framing.expire(clock),
                None => Ok(Vec::new()),
            }
        })();
        let attached = self.attached_inbound_channels();
        let expired = match result {
            Ok(expired) => expired,
            Err(error) => {
                self.time_uncertain |= error.code == Code::TimeUncertain;
                self.fence_inbound_channels(attached, &error, closing);
                return Err(error);
            }
        };
        if !attached.is_empty() {
            let activity = match self.current_activity_id() {
                Ok(activity) => activity,
                Err(error) => {
                    self.fence_inbound_channels(attached, &error, closing);
                    return Err(error);
                }
            };
            for channel in attached {
                let result = if expired.contains(&channel.peer) {
                    Err(Error::new(Code::Expired, "frame assembly deadline"))
                } else {
                    self.check_registered_channel(activity, &channel, clock.monotonic_ms)
                };
                if let Err(error) = result {
                    self.fence_control_channel(channel);
                    closing.push((channel, error));
                }
            }
        }
        Ok(())
    }

    fn attached_inbound_channels(&self) -> Vec<OutboundChannel> {
        self.ingress
            .channels
            .values()
            .filter_map(|entry| entry.read_ready.map(|_| entry.binding))
            .collect()
    }

    fn fence_inbound_channels(
        &mut self,
        channels: Vec<OutboundChannel>,
        error: &Error,
        closing: &mut Vec<(OutboundChannel, Error)>,
    ) {
        for channel in channels {
            self.fence_control_channel(channel);
            closing.push((channel, Error::new(error.code, error.operation)));
        }
    }

    fn apply_inbound_read(
        &mut self,
        channel: OutboundChannel,
        clock: &Clock,
        scratch: &[u8],
        read: io::Result<usize>,
    ) -> Result<()> {
        let count = match read {
            Ok(0) => return Err(Error::new(Code::Stopped, "inbound stream EOF")),
            Ok(count) if count <= scratch.len() => count,
            Ok(_) => {
                return Err(Error::new(
                    Code::InvalidInput,
                    "inbound read exceeds credit",
                ));
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                self.ingress
                    .channels
                    .get_mut(&channel.peer)
                    .expect("registered channel")
                    .read_ready = Some(false);
                return Ok(());
            }
            Err(error) => {
                return Err(Error::source_error(
                    Code::Stopped,
                    "inbound stream read",
                    error,
                ));
            }
        };
        let progress = self
            .ingress
            .framing
            .as_mut()
            .expect("attached framing")
            .push(&channel.peer, clock, &scratch[..count])?;
        if progress.consumed != count {
            return Err(Error::new(Code::InvalidInput, "inbound frame consumption"));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;
