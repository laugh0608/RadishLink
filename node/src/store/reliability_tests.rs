use super::tests::{Workspace, clock, destination, relay, send};
use super::*;

fn make_v1(s: &Store) {
    super::tests::strip_v4(s);
    // schema.sql is unchanged from 2936c6e; remove exactly the later additions.
    s.conn
        .execute_batch(
            "DROP TABLE receipt_intents; DROP INDEX message_deadline; DROP TABLE control_reservations; DROP INDEX message_expiry; PRAGMA user_version=1;",
        )
        .unwrap();
}
fn version(w: &Workspace) -> i64 {
    Connection::open(w.dir.join("node.sqlite3"))
        .unwrap()
        .pragma_query_value(None, "user_version", |r| r.get(0))
        .unwrap()
}

#[test]
fn old_store_requires_explicit_atomic_migration_and_preserves_records() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("origin", "a", 0)).unwrap();
    s.receive(relay("relay")).unwrap();
    make_v1(&s);
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    assert_eq!(version(&w), 1);
    let s = Store::migrate_v1(&w.dir, Limits::default(), clock(1)).unwrap();
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert!(s.action("ui", 1, "a").unwrap().is_some());
    drop(s);
    assert_eq!(version(&w), 6);
    assert!(Store::migrate_v1(&w.dir, Limits::default(), clock(2)).is_err());
    let mut s = w.reopen(2);
    assert_eq!(
        s.finish_delivery(
            "relay",
            &super::tests::binding("relay"),
            Some((super::tests::PEER_2, b"proof")),
            5
        )
        .unwrap_err()
        .code,
        Code::UnsupportedVersion
    );
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
}

#[test]
fn migration_quota_or_sql_failure_rolls_back_schema_and_data() {
    for sql_failure in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("relay")).unwrap();
        make_v1(&s);
        let limits = if sql_failure {
            s.conn.execute_batch("CREATE TRIGGER reject_migration BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT,'synthetic migration failure'); END;").unwrap();
            Limits::default()
        } else {
            let l = Limits {
                control_bytes: 1,
                ..Limits::default()
            };
            s.conn
                .execute("UPDATE meta SET limits=?1", [limits_json(&l).unwrap()])
                .unwrap();
            l
        };
        drop(s);
        let error = Store::migrate_v1(&w.dir, limits, clock(1)).err().unwrap();
        assert_eq!(
            error.code,
            if sql_failure {
                Code::StoreUnavailable
            } else {
                Code::Quota
            }
        );
        assert_eq!(version(&w), 1);
        let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        let exists: bool = conn
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='control_reservations')",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert!(!exists);
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM messages WHERE payload IS NOT NULL",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            1
        );
    }
}

#[test]
fn relay_reserves_control_until_delivery_or_expiry() {
    let w = Workspace::new();
    let limits = Limits {
        control_count: CONTROL_RESERVED_RECORDS + 1,
        control_bytes: CONTROL_RESERVED_BYTES + 4096,
        ..Limits::default()
    };
    let mut s = Store::create(&w.dir, limits.clone(), clock(0)).unwrap();
    super::tests::prepare_business(&mut s);
    s.receive(relay("one")).unwrap();
    assert_eq!(s.usage().unwrap().reserved_control_bytes, 4096);
    assert_eq!(
        s.receive(destination("two", 0)).unwrap_err().code,
        Code::Quota
    );
    assert_eq!(s.receive(relay("two")).unwrap_err().code, Code::Quota);
    drop(s);
    let mut s = Store::open(&w.dir, limits, clock(1)).unwrap();
    s.fault = Some(TestFault::BeforeCommit);
    assert!(
        s.finish_delivery(
            "one",
            &super::tests::binding("one"),
            Some((super::tests::PEER_2, b"proof")),
            5
        )
        .is_err()
    );
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
    assert!(s.message("one").unwrap().unwrap().payload_present);
    s.fault = None;
    s.finish_delivery(
        "one",
        &super::tests::binding("one"),
        Some((super::tests::PEER_2, b"proof")),
        5,
    )
    .unwrap();
    assert_eq!(s.usage().unwrap().reserved_control_count, 0);
    assert_eq!(s.usage().unwrap().evidence_count, 1);
}

#[test]
fn maintenance_clock_cleanup_and_reservation_release_are_atomic() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("origin", "a", 0)).unwrap();
    s.receive(relay("relay")).unwrap();
    s.receive(destination("endpoint", 1)).unwrap();
    s.fault = Some(TestFault::BeforeCommit);
    assert!(s.maintain(clock(HISTORY_MS)).is_err());
    assert_eq!(s.current_clock(), clock(0));
    assert_eq!(s.usage().unwrap().reserved_control_count, 2);
    assert_eq!(s.history(0, 100).unwrap().len(), 2);
    s.fault = None;
    let r = s.maintain(clock(HISTORY_MS)).unwrap();
    assert_eq!((r.expired_payloads, r.deleted_history), (3, 2));
    assert!(!r.more_due);
    assert!(s.action("ui", 1, "a").unwrap().is_some());
    assert!(!s.message("endpoint").unwrap().unwrap().evidence_pending);
    assert_eq!(s.message("endpoint").unwrap().unwrap().state, "delivered");
    assert_eq!(s.usage().unwrap().reserved_control_count, 0);
    drop(s);
    assert!(w.reopen(HISTORY_MS - 1).is_time_uncertain());
}

#[test]
fn maintenance_is_bounded_and_unknown_wall_time_preserves_history() {
    let w = Workspace::new();
    let mut s = w.create();
    for i in 0..257 {
        s.receive(relay(&format!("m{i}"))).unwrap();
    }
    let r = s.maintain(clock(10000)).unwrap();
    assert_eq!(r.expired_payloads, 256);
    assert!(r.more_due);
    let r = s.maintain(clock(10000)).unwrap();
    assert_eq!(r.expired_payloads, 1);
    assert!(!r.more_due);
    let w2 = Workspace::new();
    let mut c = clock(0);
    c.trusted_utc = None;
    let mut s2 = Store::create(&w2.dir, Limits::default(), c.clone()).unwrap();
    assert_eq!(
        s2.receive(relay("one")).unwrap_err().code,
        Code::TimeUncertain
    );
    c.monotonic_ms = 10000;
    let r = s2.maintain(c).unwrap();
    assert!(!r.history_time_available);
    assert_eq!(r.expired_payloads, 0);
}

#[test]
fn missing_reservation_is_rejected_on_reopen() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.conn
        .execute("DELETE FROM control_reservations", [])
        .unwrap();
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::StoreCorrupt
    );
}

#[test]
fn migration_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_MIGRATION_TEST_STORE") else {
        return;
    };
    let fault = if std::env::var("RADISHLINK_MIGRATION_TEST_SIDE").unwrap() == "before" {
        TestFault::CrashBeforeCommit
    } else {
        TestFault::CrashAfterCommit
    };
    Store::open_version(
        Path::new(&dir),
        Limits::default(),
        clock(1),
        OpenMode::MigrateV1Fault(fault),
    )
    .unwrap();
    panic!("expected migration process exit");
}

#[test]
fn migration_process_exit_preserves_old_or_new_schema_without_partial_reservation() {
    for (side, exit, expected_version) in [("before", 71, 1), ("after", 72, 6)] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        make_v1(&s);
        drop(s);
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "store::reliability_tests::migration_crash_child",
                "--nocapture",
            ])
            .env("RADISHLINK_MIGRATION_TEST_STORE", &w.dir)
            .env("RADISHLINK_MIGRATION_TEST_SIDE", side)
            .status()
            .unwrap();
        assert_eq!(result.code(), Some(exit));
        assert_eq!(version(&w), expected_version);
        let s = if expected_version == 1 {
            Store::migrate_v1(&w.dir, Limits::default(), clock(2)).unwrap()
        } else {
            w.reopen(2)
        };
        assert_eq!(s.usage().unwrap().reserved_control_count, 1);
        assert!(s.message("one").unwrap().unwrap().payload_present);
    }
}

fn queue_event(key: &str, now: i64, signal: crate::retry::Signal) -> QueueEvent {
    QueueEvent {
        queue: QueueKey {
            message: key.into(),
            kind: QueueKind::Data,
            neighbor: super::tests::PEER_2.into(),
        },
        batch: Batch {
            now_ms: now,
            link: crate::retry::LinkEvent::Unchanged,
            signal,
            admission: crate::retry::Admission::Allow,
        },
    }
}

#[test]
fn same_coordinate_events_merge_before_durable_decision_and_do_not_refund_on_reopen() {
    use crate::retry::{Reason, Signal};
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    s.submit(send("two", "b", 1)).unwrap();
    let result = s
        .process_queue_batch(
            clock(250),
            vec![
                queue_event("one", 250, Signal::Continue),
                queue_event("one", 250, Signal::Pause),
                queue_event("two", 250, Signal::Continue),
            ],
        )
        .unwrap();
    assert_eq!(result.decisions.len(), 2);
    assert_eq!(result.decisions[0].1.reason, Reason::Paused);
    assert!(!result.decisions[0].1.send);
    assert!(result.decisions[1].1.send);
    assert_eq!(result.decisions[1].1.consumed, 2);
    assert!(s.message("one").unwrap().unwrap().custody_observed);
    drop(s);
    let mut s = w.reopen(251);
    let result = s
        .process_queue_batch(clock(251), vec![queue_event("two", 251, Signal::Continue)])
        .unwrap();
    assert!(!result.decisions[0].1.send);
}

#[test]
fn scheduling_batch_conflict_or_write_failure_does_not_consume_any_queue_or_clock() {
    use crate::retry::{LinkEvent, Signal};
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    s.submit(send("two", "b", 1)).unwrap();
    let mut up = queue_event("one", 0, Signal::Continue);
    up.batch.link = LinkEvent::Up;
    let mut down = queue_event("one", 0, Signal::Continue);
    down.batch.link = LinkEvent::Down;
    assert_eq!(
        s.process_queue_batch(clock(0), vec![up, down])
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    s.fault = Some(TestFault::BeforeCommit);
    assert!(
        s.process_queue_batch(
            clock(250),
            vec![
                queue_event("one", 250, Signal::Continue),
                queue_event("two", 250, Signal::Continue)
            ]
        )
        .is_err()
    );
    assert_eq!(s.current_clock(), clock(0));
    s.fault = None;
    assert_eq!(
        s.process_queue_batch(
            clock(250),
            vec![
                queue_event("one", 250, Signal::Continue),
                queue_event("zz-missing", 250, Signal::Continue)
            ]
        )
        .err()
        .unwrap()
        .code,
        Code::Conflict
    );
    assert_eq!(s.current_clock(), clock(0));
    let result = s
        .process_queue_batch(
            clock(0),
            vec![
                queue_event("one", 0, Signal::Continue),
                queue_event("two", 0, Signal::Continue),
            ],
        )
        .unwrap();
    assert!(
        result
            .decisions
            .iter()
            .all(|(_, decision)| decision.send && decision.consumed == 1)
    );
}

#[test]
fn expired_history_is_hidden_while_bounded_cleanup_retains_backlog() {
    let w = Workspace::new();
    let mut s = w.create();
    for i in 0..257 {
        s.receive(destination(&format!("m{i}"), i)).unwrap();
    }
    let r = s.maintain(clock(HISTORY_MS)).unwrap();
    assert_eq!(r.deleted_history, 256);
    assert!(r.more_due);
    assert_eq!(s.usage().unwrap().history_count, 1);
    assert!(s.history(0, 100).unwrap().is_empty());
    let r = s.maintain(clock(HISTORY_MS)).unwrap();
    assert_eq!(r.deleted_history, 1);
    assert!(!r.more_due);
    assert_eq!(s.usage().unwrap().evidence_count, 0);
    assert_eq!(s.usage().unwrap().reserved_control_count, 0);
}

#[test]
fn corrupt_retry_is_rejected_before_migration_changes_any_schema() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.schedule_forward("one", super::tests::PEER_3).unwrap();
    make_v1(&s);
    s.conn.execute("UPDATE queues SET retry='{}'", []).unwrap();
    drop(s);
    assert_eq!(
        Store::migrate_v1(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::StoreCorrupt
    );
    assert_eq!(version(&w), 1);
}

#[test]
fn full_record_budget_still_allows_reserved_return_proof_conversion() {
    let w = Workspace::new();
    let limits = Limits {
        record_count: CONTROL_RESERVED_RECORDS + 3,
        control_count: CONTROL_RESERVED_RECORDS + 1,
        control_bytes: CONTROL_RESERVED_BYTES + 4096,
        ..Limits::default()
    };
    let mut s = Store::create(&w.dir, limits, clock(0)).unwrap();
    super::tests::prepare_business(&mut s);
    s.receive(relay("one")).unwrap();
    s.schedule_forward("one", super::tests::PEER_3).unwrap();
    assert_eq!(
        s.usage().unwrap().records,
        3 + s.control_usage().unwrap().used_records
    );
    s.finish_delivery(
        "one",
        &super::tests::binding("one"),
        Some((super::tests::PEER_2, &[1; 4096])),
        5,
    )
    .unwrap();
    assert_eq!(
        s.usage().unwrap().records,
        2 + s.control_usage().unwrap().used_records
    );
    assert_eq!(s.usage().unwrap().evidence_bytes, 4096);
    assert!(!s.message("one").unwrap().unwrap().payload_present);
}
