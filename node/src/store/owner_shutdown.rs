//! Owner-local shutdown fence. The caller supplies transport closure and Join results.
use super::*;

/// Bounded work for the stopping owner. The interrupted output may be one of the
/// registered channels. It must be aborted before the corresponding instance is closed.
pub struct OwnerShutdownWork {
    pub channels: Vec<OutboundChannel>,
    pub interrupted_output: Option<OutboundChannel>,
}

pub(super) struct OwnerShutdown {
    interrupted_output: Option<OutboundChannel>,
}

impl Store {
    pub(super) fn require_owner_running(&self) -> Result<()> {
        if self.owner_shutdown.is_some() {
            return Err(Error::new(Code::Stopped, "store owner stopping"));
        }
        Ok(())
    }

    /// Close runtime admission and withdraw transient work before requesting worker stop.
    /// Leased jobs and registered channels remain until they are explicitly returned/closed.
    /// The existing durable activity and consumed budgets are kept.
    pub fn begin_owner_shutdown(&mut self) -> OwnerShutdownWork {
        let interrupted_output = if let Some(shutdown) = &self.owner_shutdown {
            shutdown.interrupted_output
        } else {
            self.conn.hold_shutdown(true);
            let interrupted_output = self.cancel_outbound_handoff();
            self.owner_shutdown = Some(OwnerShutdown { interrupted_output });
            self.outbound_acks.clear();
            self.outbound_terminal = None;
            self.ingress.discard_waiting();
            self.discard_inbound_reads();
            interrupted_output
        };
        OwnerShutdownWork {
            channels: self.ingress.registered_channels().collect(),
            interrupted_output,
        }
    }

    pub(super) fn note_owner_channel_closed(&mut self, channel: OutboundChannel) {
        if let Some(shutdown) = &mut self.owner_shutdown
            && shutdown.interrupted_output == Some(channel)
        {
            shutdown.interrupted_output = None;
        }
    }

    /// Record closure of an interrupted output that has no registered ingress handle.
    /// Registered instances must be closed with their original handle.
    pub fn confirm_owner_output_closed(&mut self, channel: OutboundChannel) -> Result<()> {
        let shutdown = self
            .owner_shutdown
            .as_ref()
            .ok_or_else(|| Error::new(Code::Conflict, "store owner shutdown not begun"))?;
        if shutdown.interrupted_output != Some(channel)
            || self
                .ingress
                .registered_channels()
                .any(|registered| registered == channel)
        {
            return Err(Error::new(Code::Conflict, "owner shutdown output instance"));
        }
        self.note_owner_channel_closed(channel);
        Ok(())
    }

    /// Allow the subsequent Store close only after the owner has joined all workers
    /// and recorded closure/return of the known channels and leases.
    /// On failure the caller retains the original cause and the Store remains fenced.
    pub fn finish_owner_shutdown(&mut self, workers_joined: Result<()>) -> Result<()> {
        let shutdown = self
            .owner_shutdown
            .as_ref()
            .ok_or_else(|| Error::new(Code::Conflict, "store owner shutdown not begun"))?;
        workers_joined?;
        if shutdown.interrupted_output.is_some() || self.ingress.has_channels() {
            return Err(Error::new(Code::Busy, "owner shutdown channels remain"));
        }
        let ingress = self.control_ingress_usage();
        if ingress.waiting != 0 || ingress.verifying != 0 {
            return Err(Error::new(
                Code::Busy,
                "owner shutdown verification tasks remain",
            ));
        }
        self.conn.hold_shutdown(false);
        Ok(())
    }
}
