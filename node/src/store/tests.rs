use super::*;
use crate::{
    retry::{Admission, LinkEvent, Reason, Signal},
    service::{Service, Status},
};
use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

static NEXT: AtomicU64 = AtomicU64::new(0);
struct Workspace {
    root: PathBuf,
    dir: PathBuf,
}
impl Workspace {
    fn new() -> Self {
        let temp = fs::canonicalize(std::env::temp_dir()).unwrap();
        let root = temp.join(format!(
            "radishlink-node-test-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::SeqCst)
        ));
        fs::DirBuilder::new().mode(0o700).create(&root).unwrap();
        let dir = root.join("store");
        Self { root, dir }
    }
    fn create(&self) -> Store {
        Store::create(&self.dir, Limits::default(), clock(0)).unwrap()
    }
    fn reopen(&self, now: i64) -> Store {
        Store::open(&self.dir, Limits::default(), clock(now)).unwrap()
    }
}
impl Drop for Workspace {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).expect("remove exact test-owned directory");
    }
}
fn clock(now: i64) -> Clock {
    Clock {
        boot: "test-boot".into(),
        monotonic_ms: now,
        trusted_unix_ms: Some(100000 + now),
    }
}
fn message(key: &str) -> Message {
    Message {
        key: key.into(),
        origin_ref: "A".into(),
        core_binding: format!("core-{key}").into_bytes(),
        payload: b"synthetic-ciphertext".to_vec(),
        deadline_ms: 10000,
        retain_until_ms: 20000,
    }
}
fn security(revision: i64) -> SecurityUpdate {
    SecurityUpdate {
        session: "session".into(),
        expected_revision: revision,
        state: vec![revision as u8 + 1],
    }
}
fn send(key: &str, reference: &str, revision: i64) -> Send {
    Send {
        action: Action {
            scope: "ui".into(),
            generation: 1,
            reference: reference.into(),
            binding: format!("request-{key}").into_bytes(),
        },
        message: message(key),
        security: security(revision),
        text: b"synthetic text".to_vec(),
        neighbor: "B".into(),
        remaining_hops: 1,
    }
}
fn relay(key: &str) -> Receive {
    Receive {
        message: message(key),
        role: Role::Relay,
        neighbor: "A".into(),
        remaining_hops: 1,
        security: None,
        text: None,
        evidence: None,
    }
}
fn destination(key: &str, revision: i64) -> Receive {
    Receive {
        message: message(key),
        role: Role::Destination,
        neighbor: "B".into(),
        remaining_hops: 0,
        security: Some(security(revision)),
        text: Some(b"synthetic text".to_vec()),
        evidence: Some(b"synthetic evidence".to_vec()),
    }
}
fn state_revision(s: &Store) -> Option<i64> {
    s.conn
        .query_row(
            "SELECT revision FROM security_states WHERE session='session'",
            [],
            |r| r.get(0),
        )
        .optional()
        .unwrap()
}
fn event(now: i64) -> Batch {
    Batch {
        now_ms: now,
        link: LinkEvent::Unchanged,
        signal: Signal::Continue,
        admission: Admission::Allow,
    }
}

#[test]
fn origin_action_atomicity_conflict_and_reopen() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    let first = s.submit(send("one", "action", 0)).unwrap();
    let revision = s.revision().unwrap();
    assert_eq!(s.submit(send("one", "action", 0)).unwrap(), first);
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(state_revision(&s), Some(1));
    assert_eq!(
        s.submit(send("two", "action", 1)).unwrap_err().code,
        Code::Conflict
    );
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    drop(s);
    let s = w.reopen(1);
    assert_eq!(
        s.action("ui", 1, "action").unwrap().unwrap().state,
        "queued"
    );
    assert_eq!(s.history(0, 100).unwrap()[0].text, b"synthetic text");
}
#[test]
fn failure_after_security_rolls_back_all_records() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    for fault in [TestFault::AfterSecurity, TestFault::BeforeCommit] {
        s.fault = Some(fault);
        assert!(s.submit(send("one", "action", 0)).is_err());
        assert_eq!(state_revision(&s), None);
        assert!(s.message("one").unwrap().is_none());
        assert!(s.action("ui", 1, "action").unwrap().is_none());
        assert!(s.history(0, 10).unwrap().is_empty());
    }
    s.fault = None;
    s.submit(send("one", "action", 0)).unwrap();
}
#[test]
fn lost_commit_response_quarantines_until_reopen_and_query() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.fault = Some(TestFault::AfterCommit);
    assert_eq!(
        s.submit(send("one", "action", 0)).unwrap_err().code,
        Code::OutcomeUnknown
    );
    assert!(s.is_quarantined());
    assert!(s.message("one").is_err());
    assert!(s.submit(send("two", "other", 1)).is_err());
    drop(s);
    let mut s = w.reopen(1);
    assert!(s.action("ui", 1, "action").unwrap().is_some());
    s.submit(send("one", "action", 0)).unwrap();
    assert_eq!(state_revision(&s), Some(1));
}
#[test]
fn destination_duplicate_has_one_history_and_persistent_return_work() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    let revision = s.revision().unwrap();
    s.receive(destination("one", 0)).unwrap();
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert_eq!(state_revision(&s), Some(1));
    assert!(s.message("one").unwrap().unwrap().evidence_pending);
    let mut conflict = destination("one", 1);
    conflict.message.core_binding = b"different".to_vec();
    assert!(s.receive(conflict).is_err());
    drop(s);
    let s = w.reopen(1);
    assert!(s.message("one").unwrap().unwrap().evidence_pending);
}
#[test]
fn relay_delivery_keeps_return_work_after_payload_cleanup() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.schedule_forward("one", "C").unwrap();
    assert!(s.schedule_forward("one", "C").is_err());
    let hops: i64 = s
        .conn
        .query_row("SELECT hops FROM queues WHERE kind='data'", [], |r| {
            r.get(0)
        })
        .unwrap();
    assert_eq!(hops, 0);
    assert_eq!(
        s.finish_delivery("one", b"wrong", Some(("A", b"evidence")))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    s.finish_delivery("one", b"core-one", Some(("A", b"evidence")))
        .unwrap();
    let v = s.message("one").unwrap().unwrap();
    assert_eq!(v.state, "delivered");
    assert!(!v.payload_present);
    assert!(v.evidence_pending);
    assert!(s.history(0, 10).unwrap().is_empty());
    drop(s);
    let s = w.reopen(1);
    assert!(s.message("one").unwrap().unwrap().evidence_pending);
}
#[test]
fn control_quota_prevents_destination_commit_and_relay_cleanup() {
    let w = Workspace::new();
    let limits = Limits {
        control_count: 1,
        ..Limits::default()
    };
    let mut s = Store::create(&w.dir, limits, clock(0)).unwrap();
    s.receive(destination("one", 0)).unwrap();
    assert_eq!(
        s.receive(destination("two", 1)).unwrap_err().code,
        Code::Quota
    );
    assert_eq!(state_revision(&s), Some(1));
    assert!(s.message("two").unwrap().is_none());
    s.receive(relay("relay")).unwrap();
    assert_eq!(
        s.finish_delivery("relay", b"core-relay", Some(("A", b"evidence")))
            .unwrap_err()
            .code,
        Code::Quota
    );
    assert!(s.message("relay").unwrap().unwrap().payload_present);
}
#[test]
fn full_history_and_payload_fail_without_partial_security_update() {
    let w = Workspace::new();
    let limits = Limits {
        history_count: 1,
        payload_count: 1,
        ..Limits::default()
    };
    let mut s = Store::create(&w.dir, limits, clock(0)).unwrap();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    assert_eq!(s.submit(send("two", "b", 1)).unwrap_err().code, Code::Quota);
    assert_eq!(state_revision(&s), Some(1));
    assert!(s.message("two").unwrap().is_none());
}
#[test]
fn readonly_and_sqlite_full_do_not_report_commit() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.conn.pragma_update(None, "query_only", true).unwrap();
    assert!(s.submit(send("one", "a", 0)).is_err());
    assert!(s.message("one").unwrap().is_none());
    s.conn.pragma_update(None, "query_only", false).unwrap();
    let pages: i64 = s
        .conn
        .pragma_query_value(None, "page_count", |r| r.get(0))
        .unwrap();
    s.conn.pragma_update(None, "max_page_count", pages).unwrap();
    let mut large = send("one", "a", 0);
    large.message.payload = vec![1; MAX_PAYLOAD];
    assert!(s.submit(large).is_err());
    drop(s);
    let s = w.reopen(1);
    assert!(s.message("one").unwrap().is_none());
    assert_eq!(state_revision(&s), None);
}
#[test]
fn clock_change_quarantines_writes_but_preserves_history() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    drop(s);
    let mut c = clock(0);
    c.boot = "new-boot".into();
    let mut s = Store::open(&w.dir, Limits::default(), c).unwrap();
    assert!(s.is_time_uncertain());
    assert_eq!(
        s.expire_payload("one").unwrap_err().code,
        Code::TimeUncertain
    );
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
    assert_eq!(
        s.purge_expired_history().unwrap_err().code,
        Code::TimeUncertain
    );
}
#[test]
fn history_retention_never_deletes_actions_or_transport_state() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    s.advance_clock(clock(HISTORY_MS - 1)).unwrap();
    assert_eq!(s.purge_expired_history().unwrap(), 0);
    s.advance_clock(clock(HISTORY_MS)).unwrap();
    assert_eq!(s.purge_expired_history().unwrap(), 1);
    assert!(s.action("ui", 1, "a").unwrap().is_some());
    assert!(s.message("one").unwrap().unwrap().payload_present);
    s.expire_payload("one").unwrap();
    assert_eq!(s.message("one").unwrap().unwrap().state, "expired");
    assert!(s.history(0, 10).unwrap().is_empty());
}
#[test]
fn expired_action_generation_cannot_be_reused() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    s.retire_action_generation("ui", 1).unwrap();
    assert_eq!(
        s.submit(send("one", "a", 0)).unwrap_err().code,
        Code::Expired
    );
    drop(s);
    let s = w.reopen(1);
    assert_eq!(s.action("ui", 1, "a").unwrap_err().code, Code::Expired);
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
}
#[test]
fn retry_consumption_survives_reopen_without_refund() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    assert!(s.advance_queue("one", "data", "B", event(0)).unwrap().send);
    drop(s);
    let mut s = w.reopen(1);
    assert!(!s.advance_queue("one", "data", "B", event(1)).unwrap().send);
    s.advance_clock(clock(250)).unwrap();
    s.observe_custody("one", "B").unwrap();
    assert!(s.message("one").unwrap().unwrap().payload_present);
    s.advance_clock(clock(251)).unwrap();
    assert_eq!(
        s.advance_queue("one", "data", "B", event(251))
            .unwrap()
            .reason,
        Reason::Paused
    );
}
#[test]
fn unknown_schema_corruption_symlink_and_second_owner_are_rejected() {
    let w = Workspace::new();
    let s = w.create();
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::Busy
    );
    s.conn.pragma_update(None, "user_version", 2).unwrap();
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::UnsupportedVersion
    );
    assert!(Store::create(&w.dir, Limits::default(), clock(0)).is_err());
    fs::write(w.dir.join("node.sqlite3"), b"corrupt synthetic database").unwrap();
    assert!(Store::open(&w.dir, Limits::default(), clock(1)).is_err());
    let link = w.root.join("link");
    std::os::unix::fs::symlink(&w.dir, &link).unwrap();
    assert!(Store::open(&link, Limits::default(), clock(1)).is_err());
}
#[test]
fn service_has_one_owner_queries_committed_state_and_refuses_send() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    let service = Service::start(s).unwrap();
    assert_eq!(service.status().unwrap(), Status::SecurityUnavailable);
    assert!(
        service
            .action("ui".into(), 1, "a".into())
            .unwrap()
            .is_some()
    );
    assert_eq!(service.history(0, 10).unwrap().len(), 1);
    assert_eq!(
        service.submit_text().unwrap_err().code,
        Code::SecurityUnavailable
    );
    service.stop().unwrap();
    let s = w.reopen(1);
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
}
#[test]
fn crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_NODE_TEST_STORE") else {
        return;
    };
    let fault = std::env::var("RADISHLINK_NODE_TEST_FAULT").unwrap();
    let mut s = Store::open(Path::new(&dir), Limits::default(), clock(1)).unwrap();
    s.fault = Some(if fault == "before" {
        TestFault::CrashBeforeCommit
    } else {
        TestFault::CrashAfterCommit
    });
    s.submit(send("one", "a", 0)).unwrap();
    panic!("expected controlled process exit");
}
#[test]
fn process_exit_on_both_sides_of_commit_recovers_atomic_result() {
    for (fault, exit, committed) in [("before", 71, false), ("after", 72, true)] {
        let w = Workspace::new();
        let mut s = w.create();
        s.create_action_scope("ui").unwrap();
        drop(s);
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "store::tests::crash_child", "--nocapture"])
            .env("RADISHLINK_NODE_TEST_STORE", &w.dir)
            .env("RADISHLINK_NODE_TEST_FAULT", fault)
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(exit));
        let s = w.reopen(2);
        assert_eq!(s.message("one").unwrap().is_some(), committed);
        assert_eq!(s.history(0, 10).unwrap().len(), usize::from(committed));
        assert_eq!(state_revision(&s).is_some(), committed);
        assert_eq!(s.action("ui", 1, "a").unwrap().is_some(), committed);
    }
}

#[test]
fn receive_and_cleanup_faults_preserve_whole_transaction() {
    for destination_role in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        s.fault = Some(TestFault::BeforeCommit);
        let input = if destination_role {
            destination("one", 0)
        } else {
            relay("one")
        };
        assert!(s.receive(input).is_err());
        assert!(s.message("one").unwrap().is_none());
        assert_eq!(state_revision(&s), None);
        assert!(s.history(0, 100).unwrap().is_empty());
    }
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        s.schedule_forward("one", "C").unwrap();
        s.fault = Some(fault);
        assert!(
            s.finish_delivery("one", b"core-one", Some(("A", b"proof")))
                .is_err()
        );
        drop(s);
        let s = w.reopen(1);
        let view = s.message("one").unwrap().unwrap();
        assert_eq!(view.payload_present, fault == TestFault::BeforeCommit);
        assert_eq!(view.evidence_pending, fault == TestFault::AfterCommit);
    }
}

#[test]
fn three_independent_stores_preserve_endpoint_and_relay_responsibilities() {
    let wa = Workspace::new();
    let wb = Workspace::new();
    let wc = Workspace::new();
    let mut a = wa.create();
    let mut b = wb.create();
    let mut c = wc.create();
    a.create_action_scope("ui").unwrap();
    a.submit(send("one", "a", 0)).unwrap();
    b.receive(relay("one")).unwrap();
    b.schedule_forward("one", "C").unwrap();
    a.observe_custody("one", "B").unwrap();
    assert!(a.message("one").unwrap().unwrap().payload_present);
    c.receive(destination("one", 0)).unwrap();
    c.receive(destination("one", 0)).unwrap();
    b.finish_delivery("one", b"core-one", Some(("A", b"proof")))
        .unwrap();
    assert!(b.message("one").unwrap().unwrap().evidence_pending);
    a.finish_delivery("one", b"core-one", None).unwrap();
    assert_eq!(a.message("one").unwrap().unwrap().state, "delivered");
    assert_eq!(a.history(0, 100).unwrap().len(), 1);
    assert_eq!(c.history(0, 100).unwrap().len(), 1);
    assert!(b.history(0, 100).unwrap().is_empty());
}

#[test]
fn service_clock_drives_retention_and_commits_floor() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    let service = Service::start(s).unwrap();
    service.advance_clock(clock(HISTORY_MS)).unwrap();
    assert!(service.history(0, 100).unwrap().is_empty());
    assert!(
        service
            .action("ui".into(), 1, "a".into())
            .unwrap()
            .is_some()
    );
    service.stop().unwrap();
    let s = w.reopen(HISTORY_MS - 1);
    assert!(s.is_time_uncertain());
}

#[test]
fn monotonic_floor_from_reopened_commit_cannot_regress() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    drop(s);
    let mut s = w.reopen(100);
    s.submit(send("one", "a", 0)).unwrap();
    drop(s);
    let s = w.reopen(99);
    assert!(s.is_time_uncertain());
}

#[test]
fn sensitive_records_have_limits_and_no_raw_error_output() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    let mut invalid = send("one", "a", 0);
    invalid.text = vec![b'x'; MAX_TEXT + 1];
    assert_eq!(s.submit(invalid).unwrap_err().code, Code::InvalidInput);
    let mut invalid = relay("one");
    invalid.remaining_hops = 0;
    assert!(s.receive(invalid).is_err());
    let mut invalid = relay("one");
    invalid.text = Some(b"private plaintext".to_vec());
    let e = s.receive(invalid).unwrap_err();
    assert!(!format!("{e:?}").contains("private plaintext"));
    assert!(s.history(0, 101).is_err());
    assert!(s.message("one").unwrap().is_none());
}

#[test]
fn reopened_relay_retains_upstream_and_rejects_origin_or_return_changes() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    drop(s);
    let mut s = w.reopen(1);
    assert_eq!(
        s.message("one")
            .unwrap()
            .unwrap()
            .source_neighbor
            .as_deref(),
        Some("A")
    );
    let mut changed = relay("one");
    changed.message.origin_ref = "other-origin".into();
    assert_eq!(s.receive(changed).unwrap_err().code, Code::Conflict);
    assert_eq!(
        s.finish_delivery("one", b"core-one", Some(("wrong", b"proof")))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert!(s.message("one").unwrap().unwrap().payload_present);
    s.finish_delivery("one", b"core-one", Some(("A", b"proof")))
        .unwrap();
    drop(s);
    let s = w.reopen(2);
    let neighbor: String = s
        .conn
        .query_row(
            "SELECT neighbor FROM queues WHERE kind='evidence'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(neighbor, "A");
}
