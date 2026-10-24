//! Bounded local command owner. No socket, authorization bypass or fake crypto provider.
use crate::{
    error::{Code, Error, Result},
    model::{Clock, HistoryItem, MessageView},
    store::Store,
};
use std::{
    sync::mpsc::{self, Sender, SyncSender, TrySendError},
    thread::{self, JoinHandle},
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    SecurityUnavailable,
    TimeUncertain,
    Quarantined,
}
enum Command {
    Status(Sender<Result<Status>>),
    Message(String, Sender<Result<Option<MessageView>>>),
    Action(String, i64, String, Sender<Result<Option<MessageView>>>),
    History(i64, u32, Sender<Result<Vec<HistoryItem>>>),
    Submit(Sender<Result<()>>),
    Clock(Clock, Sender<Result<()>>),
    Stop,
}
pub struct Service {
    sender: Option<SyncSender<Command>>,
    worker: Option<JoinHandle<()>>,
}
impl Service {
    /// A completed, access-controlled store must be supplied by the future platform integration.
    pub fn start(mut store: Store) -> Result<Self> {
        // In uncertain time retain history rather than guessing expiry.
        if !store.is_time_uncertain() && !store.is_quarantined() {
            match store.purge_expired_history() {
                Ok(_) => {}
                Err(e) if e.code == Code::TimeUncertain => {}
                Err(e) => return Err(e),
            }
        }
        let (sender, receiver) = mpsc::sync_channel(32);
        let worker = thread::Builder::new()
            .name("radishlink-state".into())
            .spawn(move || {
                for command in receiver {
                    // Losing a reply receiver never rolls back a committed command.
                    match command {
                        Command::Status(reply) => {
                            let status = if store.is_quarantined() {
                                Status::Quarantined
                            } else if store.is_time_uncertain() {
                                Status::TimeUncertain
                            } else {
                                Status::SecurityUnavailable
                            };
                            let _ = reply.send(Ok(status));
                        }
                        Command::Message(key, reply) => {
                            let _ = reply.send(store.message(&key));
                        }
                        Command::Action(scope, generation, reference, reply) => {
                            let _ = reply.send(store.action(&scope, generation, &reference));
                        }
                        Command::History(after, limit, reply) => {
                            let _ = reply.send(store.history(after, limit));
                        }
                        Command::Submit(reply) => {
                            let _ = reply.send(Err(Error::new(
                                Code::SecurityUnavailable,
                                "send requires accepted security integration",
                            )));
                        }
                        Command::Clock(clock, reply) => {
                            let result = store
                                .advance_clock(clock)
                                .and_then(|()| store.purge_expired_history().map(|_| ()));
                            let _ = reply.send(result);
                        }
                        Command::Stop => break,
                    }
                }
            })?;
        Ok(Self {
            sender: Some(sender),
            worker: Some(worker),
        })
    }
    fn request<T>(&self, command: impl FnOnce(Sender<Result<T>>) -> Command) -> Result<T> {
        let (tx, rx) = mpsc::channel();
        let sender = self
            .sender
            .as_ref()
            .ok_or_else(|| Error::new(Code::Stopped, "service stopped"))?;
        sender.try_send(command(tx)).map_err(|e| match e {
            TrySendError::Full(_) => Error::new(Code::Busy, "command queue full"),
            TrySendError::Disconnected(_) => Error::new(Code::Stopped, "state owner unavailable"),
        })?;
        rx.recv()
            .map_err(|e| Error::source_error(Code::Stopped, "state owner response", e))?
    }
    pub fn status(&self) -> Result<Status> {
        self.request(Command::Status)
    }
    pub fn message(&self, key: String) -> Result<Option<MessageView>> {
        self.request(|r| Command::Message(key, r))
    }
    pub fn action(
        &self,
        scope: String,
        generation: i64,
        reference: String,
    ) -> Result<Option<MessageView>> {
        self.request(|r| Command::Action(scope, generation, reference, r))
    }
    pub fn history(&self, after: i64, limit: u32) -> Result<Vec<HistoryItem>> {
        self.request(|r| Command::History(after, limit, r))
    }
    /// No body is accepted or retained until authentication and atomic security state are implemented.
    pub fn submit_text(&self) -> Result<()> {
        self.request(Command::Submit)
    }
    /// Platform-only clock input; never exposed as a user/network API operation.
    pub fn advance_clock(&self, clock: Clock) -> Result<()> {
        self.request(|r| Command::Clock(clock, r))
    }
    pub fn stop(mut self) -> Result<()> {
        self.shutdown()
    }
    fn shutdown(&mut self) -> Result<()> {
        if let Some(sender) = self.sender.take() {
            let _ = sender.send(Command::Stop);
        }
        if let Some(worker) = self.worker.take() {
            worker
                .join()
                .map_err(|_| Error::new(Code::Stopped, "state owner panicked"))?;
        }
        Ok(())
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}
