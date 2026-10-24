use super::*;
use crate::model::HISTORY_MS;
use crate::store::tests::{Workspace, clock, send};

#[test]
fn full_queue_rejects_new_work_and_shutdown_drains_accepted_queries() {
    let w = Workspace::new();
    let service = Service::start(w.create()).unwrap();
    let client = service.client();
    let (entered, at_hold) = mpsc::channel();
    let (release, held) = mpsc::channel();
    client.enqueue(Command::Hold(entered, held)).unwrap();
    at_hold.recv_timeout(Duration::from_secs(2)).unwrap();
    let mut replies = vec![];
    for _ in 0..COMMAND_CAPACITY {
        let (tx, rx) = mpsc::channel();
        client.enqueue(Command::Diagnostics(tx)).unwrap();
        replies.push(rx);
    }
    assert_eq!(client.status().unwrap_err().code, Code::Busy);
    let closer = thread::spawn(move || service.stop());
    // Wait on the actual admission gate, not an assumed thread scheduling delay.
    let deadline = Instant::now() + Duration::from_secs(2);
    while client.gate.sender.lock().unwrap().is_some() {
        assert!(Instant::now() < deadline);
        thread::yield_now();
    }
    assert_eq!(client.status().unwrap_err().code, Code::Stopped);
    release.send(()).unwrap();
    for rx in replies {
        assert!(rx.recv_timeout(Duration::from_secs(2)).unwrap().is_ok());
    }
    closer.join().unwrap().unwrap();
    drop(w.reopen(0));
}

#[test]
fn owner_panic_closes_clients_and_is_reported_by_join() {
    let w = Workspace::new();
    let service = Service::start(w.create()).unwrap();
    let client = service.client();
    client.enqueue(Command::Panic).unwrap();
    assert_eq!(client.status().unwrap_err().code, Code::Stopped);
    assert_eq!(service.stop().unwrap_err().code, Code::Stopped);
    drop(w.reopen(0));
}

struct TestClock {
    input: Arc<Mutex<Clock>>,
    fail: Arc<Mutex<bool>>,
}
impl ClockSource for TestClock {
    fn sample(&mut self) -> Result<Clock> {
        if *self.fail.lock().unwrap() {
            Err(Error::new(
                Code::TimeUncertain,
                "synthetic clock unavailable",
            ))
        } else {
            Ok(self.input.lock().unwrap().clone())
        }
    }
}
fn wait_for(mut condition: impl FnMut() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(3);
    while !condition() {
        assert!(Instant::now() < deadline, "maintenance deadline");
        thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn timer_maintains_without_ui_clock_commands_and_reports_source_failure() {
    let w = Workspace::new();
    let mut store = w.create();
    store.create_action_scope("ui").unwrap();
    store.submit(send("one", "a", 0)).unwrap();
    let input = Arc::new(Mutex::new(clock(HISTORY_MS)));
    let fail = Arc::new(Mutex::new(false));
    let source = TestClock {
        input: input.clone(),
        fail: fail.clone(),
    };
    let service = Service::start_with_clock(store, source, Duration::from_millis(100)).unwrap();
    wait_for(|| service.history(0, 10).unwrap().is_empty());
    assert_eq!(service.usage().unwrap().payload_count, 0);
    assert!(
        service
            .action("ui".into(), 1, "a".into())
            .unwrap()
            .is_some()
    );
    assert_eq!(
        service.advance_clock(clock(HISTORY_MS)).unwrap_err().code,
        Code::Conflict
    );
    *fail.lock().unwrap() = true;
    wait_for(|| service.status().unwrap() == Status::MaintenanceFailed(Code::TimeUncertain));
    assert_eq!(
        service.diagnostics().unwrap().maintenance_error_operation,
        Some("synthetic clock unavailable")
    );
    *fail.lock().unwrap() = false;
    wait_for(|| service.status().unwrap() == Status::SecurityUnavailable);
    input.lock().unwrap().boot = "changed-boot".into();
    wait_for(|| service.status().unwrap() == Status::TimeUncertain);
    assert_eq!(service.submit_text().unwrap_err().code, Code::TimeUncertain);
    assert!(
        service
            .action("ui".into(), 1, "a".into())
            .unwrap()
            .is_some()
    );
    service.stop().unwrap();
}

#[test]
fn input_bounds_apply_before_command_admission() {
    let w = Workspace::new();
    let service = Service::start(w.create()).unwrap();
    assert_eq!(
        service.message("x".repeat(65)).unwrap_err().code,
        Code::InvalidInput
    );
    assert!(service.history(0, 101).is_err());
    service.stop().unwrap();
}

#[test]
fn disconnected_reply_does_not_cancel_committed_maintenance_and_clients_stop_on_drop() {
    let w = Workspace::new();
    let mut store = w.create();
    store.create_action_scope("ui").unwrap();
    store.submit(send("one", "a", 0)).unwrap();
    let service = Service::start(store).unwrap();
    let client = service.client();
    let (reply, rx) = mpsc::channel();
    drop(rx);
    client
        .enqueue(Command::Clock(clock(HISTORY_MS), reply))
        .unwrap();
    assert_eq!(client.usage().unwrap().history_count, 0);
    drop(service);
    assert_eq!(client.status().unwrap_err().code, Code::Stopped);
    let s = w.reopen(HISTORY_MS);
    assert_eq!(s.usage().unwrap().payload_count, 0);
    assert!(s.action("ui", 1, "a").unwrap().is_some());
}

#[test]
fn poisoned_admission_still_closes_and_joins_state_owner() {
    let w = Workspace::new();
    let service = Service::start(w.create()).unwrap();
    let client = service.client();
    let gate = client.gate.clone();
    assert!(
        thread::spawn(move || {
            let _lock = gate.sender.lock().unwrap();
            panic!("controlled admission poison");
        })
        .join()
        .is_err()
    );
    assert_eq!(client.status().unwrap_err().code, Code::Stopped);
    assert_eq!(service.stop().unwrap_err().code, Code::Stopped);
    drop(w.reopen(0));
}
