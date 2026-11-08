//! One nonblocking result slot per dispatched lease.
use super::*;
use std::sync::mpsc::{Receiver, SyncSender, TryRecvError, TrySendError, sync_channel};

pub(super) enum VerificationState {
    Waiting,
    Manual,
    Dispatched(Receiver<Result<ControlVerificationOutcome>>),
}

/// A worker owns the job and its one-shot result sender together.
pub struct ControlVerificationDispatch {
    job: ControlVerificationJob,
    result: SyncSender<Result<ControlVerificationOutcome>>,
}

impl ControlVerificationDispatch {
    pub fn job(&self) -> &ControlVerificationJob {
        &self.job
    }

    /// Returns the job once, independently of owner command admission.
    /// The bound applies to storage awaiting collection by the owner.
    pub fn return_result(self, outcome: ControlVerificationOutcome) -> Result<()> {
        let Self { job, result } = self;
        drop(job);
        let outcome = match &outcome {
            ControlVerificationOutcome::Verified(object)
                if object.cose.capacity() > MAX_CONTROL_BYTES
                    || object.fields.payload.capacity() > MAX_CONTROL_BYTES =>
            {
                Err(Error::new(
                    Code::InvalidInput,
                    "control verification result capacity",
                ))
            }
            _ => Ok(outcome),
        };
        result.try_send(outcome).map_err(|error| match error {
            TrySendError::Full(_) => {
                Error::new(Code::Busy, "control verification result slot full")
            }
            TrySendError::Disconnected(_) => {
                Error::new(Code::Stopped, "control verification owner disconnected")
            }
        })
    }
}

pub struct ControlVerificationDispatchPoll {
    pub dispatch: Option<ControlVerificationDispatch>,
    pub discarded: Vec<Error>,
}

impl Store {
    /// Leases the next FIFO candidate with a dedicated result position in its existing slot.
    pub fn dispatch_control_verification(&mut self) -> Result<ControlVerificationDispatchPoll> {
        let (index, discarded) = self.next_waiting_verification()?;
        let dispatch = index.map(|index| {
            let (result, receiver) = sync_channel(1);
            let job = self.lease_control_job(index, VerificationState::Dispatched(receiver));
            ControlVerificationDispatch { job, result }
        });
        Ok(ControlVerificationDispatchPoll {
            dispatch,
            discarded,
        })
    }

    /// Collects at most one result, including while stopping. A missing sender keeps
    /// its lease until worker termination is confirmed through owner shutdown.
    pub fn poll_control_verification_result(
        &mut self,
        neighbors: &[ControlNeighbor],
    ) -> Result<Option<(ControlVerificationCompletion, OutboundAckAdmission)>> {
        let mut disconnected = false;
        for (index, pending) in self.ingress.pending.iter().enumerate() {
            let VerificationState::Dispatched(result) = &pending.verification else {
                continue;
            };
            match result.try_recv() {
                Ok(outcome) => {
                    let pending = self
                        .ingress
                        .pending
                        .remove(index)
                        .expect("located result slot");
                    return self
                        .accept_control_verification(pending, outcome?, neighbors, true)
                        .map(Some);
                }
                Err(TryRecvError::Empty) => {}
                Err(TryRecvError::Disconnected) => disconnected = true,
            }
        }
        if disconnected {
            return Err(Error::new(
                Code::Stopped,
                "control verification result sender disconnected",
            ));
        }
        Ok(None)
    }

    /// The caller has joined the workers and the owner is stopping. Discard returns
    /// and reclaim abandoned slots. A still-connected sender keeps its lease.
    pub(in crate::store) fn discard_joined_control_dispatches(&mut self) {
        self.ingress
            .pending
            .retain(|pending| match &pending.verification {
                VerificationState::Dispatched(result) => {
                    matches!(result.try_recv(), Err(TryRecvError::Empty))
                }
                _ => true,
            });
    }
}

#[cfg(test)]
mod tests;
