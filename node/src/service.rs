//! One state owner, bounded admission, ordered shutdown and optional platform maintenance.
use crate::{
    error::{Code, Error, Result},
    model::{Clock, HistoryItem, MessageView, check_ref},
    store::{MaintenanceReport, Store, Usage},
};
use std::{
    ops::Deref,
    sync::{
        Arc, Mutex,
        mpsc::{self, RecvTimeoutError, Sender, SyncSender, TrySendError},
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant},
};

pub const COMMAND_CAPACITY: usize = 32;

/// Platform integration must supply a bounded, nonblocking sample with a verified boot identity.
/// No wall-clock or boot trust is inferred here; UI/network callers must not implement this input.
pub trait ClockSource: Send + 'static {
    fn sample(&mut self) -> Result<Clock>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    SecurityUnavailable,
    TimeUncertain,
    Quarantined,
    MaintenanceFailed(Code),
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Diagnostics {
    pub status: Status,
    pub last_maintenance: Option<MaintenanceReport>,
    pub maintenance_error_operation: Option<&'static str>,
}

enum Command {
    Diagnostics(Sender<Result<Diagnostics>>),
    Message(String, Sender<Result<Option<MessageView>>>),
    Action(String, i64, String, Sender<Result<Option<MessageView>>>),
    History(i64, u32, Sender<Result<Vec<HistoryItem>>>),
    Usage(Sender<Result<Usage>>),
    Submit(Sender<Result<()>>),
    Clock(Clock, Sender<Result<MaintenanceReport>>),
    Stop,
    #[cfg(test)]
    Hold(Sender<()>, mpsc::Receiver<()>),
    #[cfg(test)]
    Panic,
}

struct AdmissionGate {
    sender: Mutex<Option<SyncSender<Command>>>,
}
/// Cloneable query/control handle. It never owns or opens a database connection.
#[derive(Clone)]
pub struct Client {
    gate: Arc<AdmissionGate>,
}
pub struct Service {
    client: Client,
    worker: Option<JoinHandle<()>>,
}
impl Deref for Service {
    type Target = Client;
    fn deref(&self) -> &Client {
        &self.client
    }
}
impl Service {
    /// Manual platform clock input; useful before a trusted platform source is available.
    pub fn start(store: Store) -> Result<Self> {
        Self::start_inner(store, None)
    }
    /// Periodic maintenance is independent of UI requests and runs between bounded commands.
    pub fn start_with_clock(
        store: Store,
        source: impl ClockSource,
        interval: Duration,
    ) -> Result<Self> {
        if !(Duration::from_millis(100)..=Duration::from_secs(60)).contains(&interval) {
            return Err(Error::new(Code::InvalidInput, "maintenance interval"));
        }
        Self::start_inner(store, Some((Box::new(source), interval)))
    }
    fn start_inner(
        mut store: Store,
        timer: Option<(Box<dyn ClockSource>, Duration)>,
    ) -> Result<Self> {
        let mut report = None;
        if !store.is_time_uncertain() && !store.is_quarantined() {
            report = Some(store.maintain(store.current_clock())?);
        }
        let (sender, receiver) = mpsc::sync_channel(COMMAND_CAPACITY);
        let gate = Arc::new(AdmissionGate {
            sender: Mutex::new(Some(sender)),
        });
        let worker_gate = gate.clone();
        let worker = thread::Builder::new()
            .name("radishlink-state".into())
            .spawn(move || {
                // Also closes admission during unwinding, so no new work enters a dead owner.
                struct CloseAdmission(Arc<AdmissionGate>);
                impl Drop for CloseAdmission {
                    fn drop(&mut self) {
                        // Poison remains observable to clients/stop, but cannot retain admission.
                        match self.0.sender.lock() {
                            Ok(mut sender) => {
                                sender.take();
                            }
                            Err(poison) => {
                                poison.into_inner().take();
                            }
                        };
                    }
                }
                let _close = CloseAdmission(worker_gate);
                let mut timer = timer;
                let mut next_tick = timer
                    .as_ref()
                    .map(|(_, interval)| Instant::now() + *interval);
                let mut failure = None;
                loop {
                    // Check on every iteration: a busy command queue cannot starve maintenance.
                    if next_tick.is_some_and(|at| Instant::now() >= at) {
                        let (source, interval) =
                            timer.as_mut().expect("timer accompanies deadline");
                        match source.sample().and_then(|clock| store.maintain(clock)) {
                            Ok(done) => {
                                report = Some(done);
                                failure = None;
                            }
                            Err(e) => failure = Some(e),
                        }
                        next_tick = Some(Instant::now() + *interval);
                    }
                    let command = match next_tick {
                        Some(at) => match receiver
                            .recv_timeout(at.saturating_duration_since(Instant::now()))
                        {
                            Ok(command) => command,
                            Err(RecvTimeoutError::Timeout) => continue,
                            Err(RecvTimeoutError::Disconnected) => break,
                        },
                        None => match receiver.recv() {
                            Ok(command) => command,
                            Err(_) => break,
                        },
                    };
                    match command {
                        Command::Diagnostics(reply) => {
                            let status = if store.is_quarantined() {
                                Status::Quarantined
                            } else if store.is_time_uncertain() {
                                Status::TimeUncertain
                            } else if let Some(error) = &failure {
                                Status::MaintenanceFailed(error.code)
                            } else {
                                Status::SecurityUnavailable
                            };
                            let _ = reply.send(Ok(Diagnostics {
                                status,
                                last_maintenance: report.clone(),
                                maintenance_error_operation: failure.as_ref().map(|e| e.operation),
                            }));
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
                        Command::Usage(reply) => {
                            let _ = reply.send(store.usage());
                        }
                        Command::Submit(reply) => {
                            let code = if store.is_quarantined() {
                                Code::OutcomeUnknown
                            } else if store.is_time_uncertain() {
                                Code::TimeUncertain
                            } else {
                                Code::SecurityUnavailable
                            };
                            let _ = reply.send(Err(Error::new(code, "send unavailable")));
                        }
                        Command::Clock(clock, reply) => {
                            if timer.is_some() {
                                let _ = reply.send(Err(Error::new(
                                    Code::Conflict,
                                    "automatic clock already owns time input",
                                )));
                                continue;
                            }
                            let result = store.maintain(clock);
                            match &result {
                                Ok(done) => {
                                    report = Some(done.clone());
                                    failure = None;
                                }
                                Err(e) => failure = Some(Error::new(e.code, e.operation)),
                            }
                            let _ = reply.send(result);
                        }
                        Command::Stop => break,
                        #[cfg(test)]
                        Command::Hold(entered, release) => {
                            let _ = entered.send(());
                            let _ = release.recv();
                        }
                        #[cfg(test)]
                        Command::Panic => panic!("controlled state owner failure"),
                    }
                }
            })?;
        Ok(Self {
            client: Client { gate },
            worker: Some(worker),
        })
    }
    pub fn client(&self) -> Client {
        self.client.clone()
    }
    pub fn stop(mut self) -> Result<()> {
        self.shutdown()
    }
    fn shutdown(&mut self) -> Result<()> {
        // Remove the sender under the same gate as try_send. All accepted commands precede Stop.
        let (sender, poisoned) = match self.client.gate.sender.lock() {
            Ok(mut gate) => (gate.take(), false),
            Err(poison) => (poison.into_inner().take(), true),
        };
        if let Some(sender) = sender {
            let _ = sender.send(Command::Stop);
        }
        if let Some(worker) = self.worker.take() {
            worker
                .join()
                .map_err(|_| Error::new(Code::Stopped, "state owner panicked"))?;
        }
        if poisoned {
            return Err(Error::new(
                Code::Stopped,
                "admission gate poisoned; owner joined",
            ));
        }
        Ok(())
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}

impl Client {
    fn enqueue(&self, command: Command) -> Result<()> {
        let gate = self
            .gate
            .sender
            .lock()
            .map_err(|_| Error::new(Code::Stopped, "admission gate poisoned"))?;
        let sender = gate
            .as_ref()
            .ok_or_else(|| Error::new(Code::Stopped, "service stopped"))?;
        sender.try_send(command).map_err(|e| match e {
            TrySendError::Full(_) => Error::new(Code::Busy, "command queue full"),
            TrySendError::Disconnected(_) => Error::new(Code::Stopped, "state owner unavailable"),
        })
    }
    fn request<T>(&self, command: impl FnOnce(Sender<Result<T>>) -> Command) -> Result<T> {
        let (tx, rx) = mpsc::channel();
        self.enqueue(command(tx))?;
        rx.recv()
            .map_err(|e| Error::source_error(Code::Stopped, "state owner response", e))?
    }
    pub fn diagnostics(&self) -> Result<Diagnostics> {
        self.request(Command::Diagnostics)
    }
    pub fn status(&self) -> Result<Status> {
        Ok(self.diagnostics()?.status)
    }
    pub fn message(&self, key: String) -> Result<Option<MessageView>> {
        check_ref(&key)?;
        self.request(|r| Command::Message(key, r))
    }
    pub fn action(
        &self,
        scope: String,
        generation: i64,
        reference: String,
    ) -> Result<Option<MessageView>> {
        check_ref(&scope)?;
        check_ref(&reference)?;
        if generation < 1 {
            return Err(Error::new(Code::InvalidInput, "action generation"));
        }
        self.request(|r| Command::Action(scope, generation, reference, r))
    }
    pub fn history(&self, after: i64, limit: u32) -> Result<Vec<HistoryItem>> {
        if after < 0 || !(1..=100).contains(&limit) {
            return Err(Error::new(Code::InvalidInput, "history page"));
        }
        self.request(|r| Command::History(after, limit, r))
    }
    pub fn usage(&self) -> Result<Usage> {
        self.request(Command::Usage)
    }
    pub fn submit_text(&self) -> Result<()> {
        self.request(Command::Submit)
    }
    /// Manual platform input; automatically driven services reject this method.
    pub fn advance_clock(&self, clock: Clock) -> Result<MaintenanceReport> {
        // The owner must observe invalid trusted samples and latch time uncertainty.
        self.request(|r| Command::Clock(clock, r))
    }
}

#[cfg(test)]
mod tests;
