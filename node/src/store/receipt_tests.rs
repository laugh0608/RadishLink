use super::tests::{Workspace, clock, destination, relay, send};
use super::*;
use crate::retry::{Admission, LinkEvent, Reason, Signal};

fn event(now_ms: i64) -> Batch {
    Batch {
        now_ms,
        link: LinkEvent::Unchanged,
        signal: Signal::Continue,
        admission: Admission::Allow,
    }
}
fn finalize(s: &mut Store, key: &str) -> Result<()> {
    s.finalize_receipt(key, b"synthetic intent", b"synthetic proof", 5)
}
fn retry_json(s: &Store, key: &str) -> serde_json::Value {
    let encoded: String = s
        .conn
        .query_row(
            "SELECT retry FROM queues WHERE message_key=?1 AND kind='evidence'",
            [key],
            |r| r.get(0),
        )
        .unwrap();
    serde_json::from_str(&encoded).unwrap()
}
fn version(w: &Workspace) -> i64 {
    Connection::open(w.dir.join("node.sqlite3"))
        .unwrap()
        .pragma_query_value(None, "user_version", |r| r.get(0))
        .unwrap()
}
fn make_v2(s: &Store) {
    super::tests::strip_v4(s);
    // Construct the old evidence behavior without running any cryptographic provider.
    s.conn
        .execute_batch(
            "DROP TABLE receipt_intents; DROP INDEX message_deadline; PRAGMA user_version=2;",
        )
        .unwrap();
    let mut stmt = s
        .conn
        .prepare("SELECT rowid,retry FROM queues WHERE kind='evidence'")
        .unwrap();
    let rows = stmt
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
        .unwrap()
        .collect::<std::result::Result<Vec<_>, _>>()
        .unwrap();
    drop(stmt);
    for (id, encoded) in rows {
        let mut old: serde_json::Value = serde_json::from_str(&encoded).unwrap();
        old["deadline_ms"] = 20000.into();
        s.conn
            .execute(
                "UPDATE queues SET retry=?2 WHERE rowid=?1",
                params![id, old.to_string()],
            )
            .unwrap();
    }
}

#[test]
fn destination_commits_only_intent_and_conversion_preserves_budget_and_history() {
    let w = Workspace::new();
    let mut s = w.create();
    assert!(s.receipt_intent("one").unwrap().is_none());
    s.receive(destination("one", 0)).unwrap();
    let view = s.message("one").unwrap().unwrap();
    assert!(view.receipt_intent_pending && !view.evidence_pending);
    let intent = s.receipt_intent("one").unwrap().unwrap();
    assert_eq!(intent.core_binding, super::tests::binding("one"));
    assert_eq!(intent.neighbor, super::tests::PEER_2);
    assert_eq!(intent.deadline_ms, 10000);
    assert_eq!(s.usage().unwrap().reserved_control_bytes, 4096);
    drop(s);
    let mut s = w.reopen(1);
    s.finalize_receipt("one", &intent.body, b"synthetic proof", 5)
        .unwrap();
    assert!(s.receipt_intent("one").unwrap().is_none());
    let result = s
        .advance_queue("one", "evidence", super::tests::PEER_2, event(1))
        .unwrap();
    assert!(!result.send); // A reopened shared control bucket starts empty.
    assert_eq!(result.reason, Reason::Quota);
    let saved = retry_json(&s, "one");
    finalize(&mut s, "one").unwrap();
    s.receive(destination("one", 0)).unwrap();
    assert_eq!(retry_json(&s, "one"), saved);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert_eq!(s.usage().unwrap().reserved_control_count, 0);
    assert_eq!(s.usage().unwrap().evidence_count, 1);
}

#[test]
fn intent_and_conversion_failures_never_publish_partial_work() {
    for fault in [
        TestFault::AfterSecurity,
        TestFault::BeforeCommit,
        TestFault::AfterCommit,
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.fault = Some(fault);
        assert!(s.receive(destination("one", 0)).is_err());
        drop(s);
        let s = w.reopen(1);
        let committed = fault == TestFault::AfterCommit;
        assert_eq!(s.receipt_intent("one").unwrap().is_some(), committed);
        assert_eq!(s.history(0, 100).unwrap().len(), usize::from(committed));
        assert_eq!(s.usage().unwrap().evidence_count, 0);
    }
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("one", 0)).unwrap();
        s.fault = Some(fault);
        assert!(finalize(&mut s, "one").is_err());
        drop(s);
        let mut s = w.reopen(1);
        let view = s.message("one").unwrap().unwrap();
        assert_eq!(
            view.receipt_intent_pending,
            fault == TestFault::BeforeCommit
        );
        assert_eq!(view.evidence_pending, fault == TestFault::AfterCommit);
        finalize(&mut s, "one").unwrap();
        assert_eq!(s.history(0, 100).unwrap().len(), 1);
    }
}

#[test]
fn invalid_conversion_does_not_consume_committed_intent() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    let revision = s.revision().unwrap();
    for (body, proof, expected) in [
        (&b"wrong"[..], &b"proof"[..], Code::Conflict),
        (&b"synthetic intent"[..], &b""[..], Code::InvalidInput),
        (&b"synthetic intent"[..], &[1; 4097][..], Code::InvalidInput),
    ] {
        assert_eq!(
            s.finalize_receipt("one", body, proof, 5).unwrap_err().code,
            expected
        );
        assert_eq!(s.revision().unwrap(), revision);
        assert!(s.receipt_intent("one").unwrap().is_some());
    }
    finalize(&mut s, "one").unwrap();
    assert_eq!(
        s.finalize_receipt("one", b"synthetic intent", b"changed", 5)
            .unwrap_err()
            .code,
        Code::Conflict
    );
    s.receive(relay("relay")).unwrap();
    assert_eq!(
        finalize(&mut s, "relay").unwrap_err().code,
        Code::InvalidInput
    );
}

#[test]
fn destination_reservation_supports_maximum_proof_at_full_quota() {
    let w = Workspace::new();
    let limits = Limits {
        record_count: CONTROL_RESERVED_RECORDS + 3,
        control_count: CONTROL_RESERVED_RECORDS + 1,
        control_bytes: CONTROL_RESERVED_BYTES + 4096,
        ..Limits::default()
    };
    let mut s = Store::create(&w.dir, limits, clock(0)).unwrap();
    super::tests::prepare_business(&mut s);
    s.receive(destination("one", 0)).unwrap();
    assert_eq!(
        s.usage().unwrap().records,
        3 + s.control_usage().unwrap().used_records
    );
    assert_eq!(s.receive(relay("two")).unwrap_err().code, Code::Quota);
    s.finalize_receipt("one", b"synthetic intent", &[1; 4096], 5)
        .unwrap();
    assert_eq!(
        s.usage().unwrap().records,
        3 + s.control_usage().unwrap().used_records
    );
    assert_eq!(s.usage().unwrap().evidence_bytes, 4096);
    assert_eq!(s.usage().unwrap().reserved_control_bytes, 0);
}

#[test]
fn deadline_blocks_intent_conversion_and_relay_delivery_without_maintenance() {
    for now in [9999, 10000, 10001] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("dest", 0)).unwrap();
        s.receive(relay("relay")).unwrap();
        s.create_action_scope("ui").unwrap();
        s.submit(send("origin", "a", 1)).unwrap();
        s.advance_clock(clock(now)).unwrap(); // Deliberately does not perform cleanup.
        let intent = s.receipt_intent("dest");
        let proof = finalize(&mut s, "dest");
        let relay_result = s.finish_delivery(
            "relay",
            &super::tests::binding("relay"),
            Some((super::tests::PEER_2, b"proof")),
            5,
        );
        let origin_result = s.finish_delivery("origin", &super::tests::binding("origin"), None, 5);
        if now < 10000 {
            assert!(
                intent.is_ok() && proof.is_ok() && relay_result.is_ok() && origin_result.is_ok()
            );
        } else {
            assert_eq!(intent.err().unwrap().code, Code::Expired);
            for result in [proof, relay_result, origin_result] {
                assert_eq!(result.unwrap_err().code, Code::Expired);
            }
            assert!(s.message("relay").unwrap().unwrap().payload_present);
            assert_eq!(s.message("dest").unwrap().unwrap().state, "committed");
        }
    }
}

#[test]
fn both_proof_legs_stop_at_original_deadline_and_destination_fact_survives() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("dest", 0)).unwrap();
    finalize(&mut s, "dest").unwrap();
    s.receive(relay("relay")).unwrap();
    s.finish_delivery(
        "relay",
        &super::tests::binding("relay"),
        Some((super::tests::PEER_2, b"proof")),
        5,
    )
    .unwrap();
    for key in ["dest", "relay"] {
        assert_eq!(retry_json(&s, key)["deadline_ms"], 10000);
    }
    s.advance_clock(clock(10000)).unwrap();
    for (key, neighbor) in [
        ("dest", super::tests::PEER_2),
        ("relay", super::tests::PEER_2),
    ] {
        let result = s
            .advance_queue(key, "evidence", neighbor, event(10000))
            .unwrap();
        assert!(!result.send);
        assert_eq!(result.reason, Reason::Expired);
    }
    s.fault = Some(TestFault::BeforeCommit);
    assert!(s.maintain(clock(10000)).is_err());
    assert_eq!(s.usage().unwrap().evidence_count, 2);
    s.fault = None;
    let report = s.maintain(clock(10000)).unwrap();
    assert_eq!(report.expired_evidence, 2);
    assert_eq!(s.message("dest").unwrap().unwrap().state, "delivered");
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert!(s.message("relay").unwrap().is_some());
    drop(s);
    assert_eq!(
        w.reopen(10001).message("dest").unwrap().unwrap().state,
        "delivered"
    );
}

#[test]
fn bounded_intent_cleanup_releases_reservations_without_erasing_delivery() {
    let w = Workspace::new();
    let mut s = w.create();
    for i in 0..257 {
        s.receive(destination(&format!("m{i}"), i)).unwrap();
    }
    let first = s.maintain(clock(10000)).unwrap();
    assert_eq!(first.expired_receipt_intents, 256);
    assert!(first.more_due);
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
    let second = s.maintain(clock(10000)).unwrap();
    assert_eq!(second.expired_receipt_intents, 1);
    assert!(!second.more_due);
    assert_eq!(s.usage().unwrap().history_count, 257);
    assert_eq!(s.usage().unwrap().payload_count, 0);
    assert_eq!(s.message("m0").unwrap().unwrap().state, "delivered");
}

#[test]
fn proof_cleanup_is_bounded_and_batch_at_deadline_cannot_send() {
    let w = Workspace::new();
    let mut s = w.create();
    for i in 0..257 {
        let key = format!("m{i:03}");
        s.receive(relay(&key)).unwrap();
        s.finish_delivery(
            &key,
            &super::tests::binding(&key),
            Some((super::tests::PEER_2, b"proof")),
            5,
        )
        .unwrap();
    }
    let report = s
        .process_queue_batch(
            clock(10000),
            vec![QueueEvent {
                queue: QueueKey {
                    message: "m256".into(),
                    kind: QueueKind::Evidence,
                    neighbor: super::tests::PEER_2.into(),
                },
                batch: event(10000),
            }],
        )
        .unwrap();
    assert!(!report.decisions[0].1.send);
    assert_eq!(report.decisions[0].1.reason, Reason::Expired);
    assert_eq!(report.maintenance.expired_evidence, 256);
    assert!(report.maintenance.more_due);
    assert_eq!(s.usage().unwrap().evidence_count, 1);
    // Remaining storage backlog cannot be used to send or renew return responsibility.
    assert!(
        !s.advance_queue("m256", "evidence", super::tests::PEER_2, event(10000))
            .unwrap()
            .send
    );
    assert_eq!(
        s.finish_delivery(
            "m256",
            &super::tests::binding("m256"),
            Some((super::tests::PEER_2, b"proof")),
            5
        )
        .unwrap_err()
        .code,
        Code::Expired
    );
    let report = s.maintain(clock(10000)).unwrap();
    assert_eq!(report.expired_evidence, 1);
    assert!(!report.more_due);
    assert_eq!(s.message("m256").unwrap().unwrap().state, "delivered");
}

#[test]
fn sqlite_rejection_rolls_back_intent_conversion() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    s.conn.execute_batch("CREATE TRIGGER reject_proof BEFORE INSERT ON queues BEGIN SELECT RAISE(ABORT,'synthetic proof write failure'); END;").unwrap();
    assert_eq!(
        finalize(&mut s, "one").unwrap_err().code,
        Code::StoreUnavailable
    );
    assert!(s.receipt_intent("one").unwrap().is_some());
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
    assert_eq!(s.usage().unwrap().evidence_count, 0);
    s.conn.execute_batch("DROP TRIGGER reject_proof;").unwrap();
    finalize(&mut s, "one").unwrap();
}

#[test]
fn cross_boot_never_exposes_signing_work_or_releases_old_responsibility() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("dest", 0)).unwrap();
    s.receive(relay("relay")).unwrap();
    let revision = s.revision().unwrap();
    drop(s);
    let mut new_boot = clock(HISTORY_MS * 2);
    new_boot.boot = "new-boot".into();
    let mut s = Store::open(&w.dir, Limits::default(), new_boot.clone()).unwrap();
    assert!(s.is_time_uncertain());
    assert_eq!(
        s.receipt_intent("dest").err().unwrap().code,
        Code::TimeUncertain
    );
    for result in [
        finalize(&mut s, "dest"),
        s.finish_delivery(
            "relay",
            &super::tests::binding("relay"),
            Some((super::tests::PEER_2, b"proof")),
            5,
        ),
        s.expire_payload("relay"),
        s.advance_clock(new_boot.clone()),
        s.advance_clock(clock(1)),
    ] {
        assert_eq!(result.unwrap_err().code, Code::TimeUncertain);
    }
    assert_eq!(s.maintain(new_boot).unwrap_err().code, Code::TimeUncertain);
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(s.usage().unwrap().reserved_control_count, 2);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert!(s.message("relay").unwrap().unwrap().payload_present);
}

#[test]
fn v2_migration_shortens_deadline_without_refunding_consumed_retries() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    finalize(&mut s, "one").unwrap();
    let denied = s
        .advance_queue("one", "evidence", super::tests::PEER_2, event(0))
        .unwrap();
    assert!(!denied.send && denied.consumed == 1);
    make_v2(&s);
    let old = retry_json(&s, "one");
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    assert_eq!(
        Store::migrate_v1(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    let mut s = Store::migrate_v2(&w.dir, Limits::default(), clock(1)).unwrap();
    let mut expected = old;
    expected["deadline_ms"] = 10000.into();
    assert_eq!(retry_json(&s, "one"), expected);
    assert_eq!(
        s.advance_queue("one", "evidence", super::tests::PEER_2, event(1))
            .unwrap_err()
            .code,
        Code::UnsupportedVersion
    );
    drop(s);
    assert_eq!(version(&w), 8);
    assert_eq!(
        Store::migrate_v2(&w.dir, Limits::default(), clock(2))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
}

#[test]
fn migration_terminates_expired_proof_and_preserves_destination_delivery() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    finalize(&mut s, "one").unwrap();
    make_v2(&s);
    // Legacy maintenance retained evidence but represented the destination as expired.
    s.conn
        .execute("UPDATE messages SET state='expired',payload=NULL", [])
        .unwrap();
    drop(s);
    let s = Store::migrate_v2(&w.dir, Limits::default(), clock(10001)).unwrap();
    assert_eq!(s.message("one").unwrap().unwrap().state, "delivered");
    assert_eq!(s.usage().unwrap().evidence_count, 0);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
}

#[test]
fn corrupt_deadline_and_missing_intent_are_rejected_on_reopen() {
    for damage in ["deadline", "intent"] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("one", 0)).unwrap();
        if damage == "intent" {
            s.conn.execute("DELETE FROM receipt_intents", []).unwrap();
        } else {
            finalize(&mut s, "one").unwrap();
            let mut encoded = retry_json(&s, "one");
            encoded["deadline_ms"] = 20000.into();
            s.conn
                .execute("UPDATE queues SET retry=?1", [encoded.to_string()])
                .unwrap();
            assert_eq!(
                s.advance_queue("one", "evidence", super::tests::PEER_2, event(0))
                    .unwrap_err()
                    .code,
                Code::StoreCorrupt
            );
        }
        drop(s);
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::StoreCorrupt
        );
    }
}

#[test]
fn v2_migration_failure_and_cross_boot_leave_old_schema_untouched() {
    for kind in ["before", "boot", "corrupt"] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("one", 0)).unwrap();
        finalize(&mut s, "one").unwrap();
        make_v2(&s);
        if kind == "corrupt" {
            s.conn.execute("UPDATE queues SET retry='{}'", []).unwrap();
        }
        drop(s);
        let mut now = clock(1);
        if kind == "boot" {
            now.boot = "new-boot".into();
        }
        let mode = if kind == "before" {
            OpenMode::MigrateV2Fault(TestFault::BeforeCommit)
        } else {
            OpenMode::MigrateV2
        };
        let err = Store::open_version(&w.dir, Limits::default(), now, mode)
            .err()
            .unwrap();
        assert_eq!(
            err.code,
            match kind {
                "boot" => Code::TimeUncertain,
                "corrupt" => Code::StoreCorrupt,
                _ => Code::StoreUnavailable,
            }
        );
        assert_eq!(version(&w), 2);
        let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        assert_eq!(
            conn.query_row(
                "SELECT count(*) FROM sqlite_master WHERE name='receipt_intents'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
            0
        );
    }
}

#[test]
fn receipt_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_RECEIPT_TEST_STORE") else {
        return;
    };
    let fault = match std::env::var("RADISHLINK_RECEIPT_TEST_SIDE")
        .unwrap()
        .as_str()
    {
        "before" => TestFault::CrashBeforeCommit,
        "after" => TestFault::CrashAfterCommit,
        _ => panic!("invalid crash side"),
    };
    let operation = std::env::var("RADISHLINK_RECEIPT_TEST_OPERATION").unwrap();
    if operation == "migration" {
        Store::open_version(
            Path::new(&dir),
            Limits::default(),
            clock(1),
            OpenMode::MigrateV2Fault(fault),
        )
        .unwrap();
    } else {
        let mut s = Store::open(Path::new(&dir), Limits::default(), clock(1)).unwrap();
        s.fault = Some(fault);
        match operation.as_str() {
            "receive" => {
                s.receive(destination("one", 0)).unwrap();
            }
            "convert" => finalize(&mut s, "one").unwrap(),
            _ => panic!("invalid crash operation"),
        }
    }
    panic!("expected controlled process exit");
}

#[test]
fn process_exit_recovers_whole_intent_conversion_and_v2_migration() {
    for operation in ["receive", "convert", "migration"] {
        for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
            let w = Workspace::new();
            let mut s = w.create();
            if operation != "receive" {
                s.receive(destination("one", 0)).unwrap();
            }
            if operation == "migration" {
                finalize(&mut s, "one").unwrap();
                make_v2(&s);
            }
            drop(s);
            let result = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::receipt_tests::receipt_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_RECEIPT_TEST_STORE", &w.dir)
                .env("RADISHLINK_RECEIPT_TEST_SIDE", side)
                .env("RADISHLINK_RECEIPT_TEST_OPERATION", operation)
                .status()
                .unwrap();
            assert_eq!(result.code(), Some(exit));
            if operation == "migration" {
                assert_eq!(version(&w), if committed { 8 } else { 2 });
                let s = if committed {
                    w.reopen(2)
                } else {
                    Store::migrate_v2(&w.dir, Limits::default(), clock(2)).unwrap()
                };
                assert_eq!(retry_json(&s, "one")["deadline_ms"], 10000);
            } else {
                let s = w.reopen(2);
                let view = s.message("one").unwrap();
                if operation == "receive" && !committed {
                    assert!(view.is_none());
                    assert!(s.history(0, 100).unwrap().is_empty());
                } else {
                    let view = view.unwrap();
                    assert_eq!(view.evidence_pending, operation == "convert" && committed);
                    assert_eq!(
                        view.receipt_intent_pending,
                        operation != "convert" || !committed
                    );
                    assert_eq!(s.history(0, 100).unwrap().len(), 1);
                }
            }
        }
    }
}
