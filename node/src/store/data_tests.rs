use super::tests::{Workspace, binding, clock, destination, relay, send};
use super::*;
use crate::data::{MAX_LIFETIME_MS, UtcInterval};

#[test]
fn core_epoch_roundtrip_and_composite_conflicts() {
    for epoch in [0, i64::MAX as u64, (i64::MAX as u64) + 1, u64::MAX] {
        let w = Workspace::new();
        let mut s = w.create();
        let mut input = relay("one");
        input.message.data.mls_epoch = epoch;
        let expected = input.message.data.clone();
        s.receive(input).unwrap();
        let encoded: Vec<u8> = s
            .conn
            .query_row("SELECT mls_epoch FROM message_data", [], |r| r.get(0))
            .unwrap();
        assert_eq!(encoded, epoch.to_be_bytes());
        drop(s);
        let mut s = w.reopen(1);
        assert!(s.message_core("one").unwrap().unwrap() == expected);
        let mut alias = relay("alias");
        alias.message.data = expected.clone();
        assert_eq!(s.receive(alias).unwrap_err().code, Code::Conflict);
        let mut changed = relay("one");
        changed.message.data = expected.clone();
        changed.message.data.mls_epoch = epoch.wrapping_add(1);
        assert_eq!(s.receive(changed).unwrap_err().code, Code::Conflict);
        let mut changed = relay("one");
        changed.message.data = expected.clone();
        changed.message.payload = b"changed ciphertext".to_vec();
        assert_eq!(s.receive(changed).unwrap_err().code, Code::Conflict);
        assert!(s.message_core("one").unwrap().unwrap() == expected);
    }
}

#[test]
fn utc_interval_boundaries_and_checked_deadline_mapping() {
    let core = relay("one").message.data;
    for width in [1999, 2000, 2001] {
        let mut c = clock(0);
        c.trusted_utc = Some(UtcInterval {
            lower_ms: 100000,
            upper_ms: 100000 + width,
        });
        let result = core.deadline(&c, Some(9000), MAX_LIFETIME_MS);
        if width <= 2000 {
            assert_eq!(result.unwrap(), 10000 - width);
        } else {
            assert_eq!(result.unwrap_err().code, Code::TimeUncertain);
        }
    }
    for offset in [-1, 0, 1] {
        let mut c = clock(0);
        c.trusted_utc = Some(UtcInterval {
            lower_ms: 110000 + offset,
            upper_ms: 110000 + offset,
        });
        let result = core.deadline(&c, None, MAX_LIFETIME_MS);
        if offset < 0 {
            assert_eq!(result.unwrap(), 1);
        } else {
            assert_eq!(result.unwrap_err().code, Code::Expired);
        }
    }
    assert_eq!(core.deadline(&clock(0), Some(500), 100).unwrap(), 100);
    for remaining in [0, MAX_LIFETIME_MS + 1] {
        assert!(core.deadline(&clock(0), Some(remaining), 100).is_err());
    }
    let mut c = clock(0);
    c.monotonic_ms = i64::MAX;
    assert_eq!(
        core.deadline(&c, None, MAX_LIFETIME_MS).unwrap_err().code,
        Code::InvalidInput
    );
    let mut overflow = core.clone();
    overflow.originated_at_ms = i64::MAX;
    assert!(overflow.not_after_ms().is_err());
    let mut future = core;
    future.originated_at_ms = 100001;
    assert_eq!(
        future
            .deadline(&clock(0), None, MAX_LIFETIME_MS)
            .unwrap_err()
            .code,
        Code::TimeUncertain
    );
}

#[test]
fn duplicate_shortens_message_and_all_queues_without_refund() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.schedule_forward("one", super::tests::PEER_3).unwrap();
    let event = Batch {
        now_ms: 0,
        link: crate::retry::LinkEvent::Unchanged,
        signal: crate::retry::Signal::Continue,
        admission: crate::retry::Admission::Allow,
    };
    assert!(
        s.advance_queue("one", "data", super::tests::PEER_3, event)
            .unwrap()
            .send
    );
    let before: String = s
        .conn
        .query_row("SELECT retry FROM queues", [], |r| r.get(0))
        .unwrap();
    let mut duplicate = relay("one");
    duplicate.message.deadline_ms = 500;
    duplicate.message.retain_until_ms = 999999;
    s.receive(duplicate).unwrap();
    let after: String = s
        .conn
        .query_row("SELECT retry FROM queues", [], |r| r.get(0))
        .unwrap();
    let mut expected: serde_json::Value = serde_json::from_str(&before).unwrap();
    expected["deadline_ms"] = 500.into();
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&after).unwrap(),
        expected
    );
    s.receive(relay("one")).unwrap();
    let (deadline, retain): (i64, i64) = s
        .conn
        .query_row("SELECT deadline,retain_until FROM messages", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .unwrap();
    assert_eq!((deadline, retain), (500, 20000));
    drop(s);
    let s = w.reopen(1);
    assert_eq!(s.message_remaining_ms("one").unwrap(), 499);
}

#[test]
fn utc_jump_stops_data_delivery_and_receipts_before_monotonic_deadline() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("origin", "a", 0)).unwrap();
    s.receive(relay("relay")).unwrap();
    s.schedule_forward("relay", super::tests::PEER_3).unwrap();
    s.receive(destination("dest", 1)).unwrap();
    let mut c = clock(1);
    c.trusted_utc = Some(UtcInterval {
        lower_ms: 110000,
        upper_ms: 110000,
    });
    s.advance_clock(c).unwrap();
    assert_eq!(
        s.message_remaining_ms("origin").unwrap_err().code,
        Code::Expired
    );
    assert_eq!(
        s.finish_delivery(
            "relay",
            &binding("relay"),
            Some((super::tests::PEER_2, b"proof")),
            5
        )
        .unwrap_err()
        .code,
        Code::Expired
    );
    assert_eq!(
        s.finalize_receipt("dest", b"synthetic intent", b"proof", 5)
            .unwrap_err()
            .code,
        Code::Expired
    );
    assert_eq!(s.receipt_intent("dest").err().unwrap().code, Code::Expired);
    let event = Batch {
        now_ms: 1,
        link: crate::retry::LinkEvent::Unchanged,
        signal: crate::retry::Signal::Continue,
        admission: crate::retry::Admission::Allow,
    };
    assert!(
        !s.advance_queue("origin", "data", super::tests::PEER_2, event)
            .unwrap()
            .send
    );
    let report = s.maintain(s.current_clock()).unwrap();
    assert_eq!(report.expired_payloads, 3);
    assert_eq!(report.expired_receipt_intents, 1);
}

#[test]
fn clock_uncertainty_latches_and_history_uses_opposite_interval_ends() {
    let w = Workspace::new();
    let mut c = clock(0);
    c.trusted_utc = Some(UtcInterval {
        lower_ms: 100000,
        upper_ms: 102000,
    });
    let mut s = Store::create(&w.dir, Limits::default(), c).unwrap();
    super::tests::prepare_business(&mut s);
    s.create_action_scope("ui").unwrap();
    let mut input = send("one", "a", 0);
    input.message.deadline_ms = 8000;
    s.submit(input).unwrap();
    let expiry: i64 = s
        .conn
        .query_row("SELECT expires FROM history", [], |r| r.get(0))
        .unwrap();
    assert_eq!(expiry, 102000 + HISTORY_MS);
    let mut c = clock(1);
    c.trusted_utc = Some(UtcInterval {
        lower_ms: 100001,
        upper_ms: 102002,
    });
    assert_eq!(s.advance_clock(c).unwrap_err().code, Code::TimeUncertain);
    assert!(s.is_time_uncertain());
    assert!(s.advance_clock(clock(2)).is_err());
    drop(s);
    let mut c = clock(2);
    c.trusted_utc = Some(UtcInterval {
        lower_ms: 100002,
        upper_ms: 101999,
    });
    let s = Store::open(&w.dir, Limits::default(), c).unwrap();
    assert!(s.is_time_uncertain());
}

#[test]
fn migration_keeps_legacy_facts_and_disables_every_output_path() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("origin", "a", 0)).unwrap();
    s.receive(relay("relay")).unwrap();
    s.schedule_forward("relay", super::tests::PEER_3).unwrap();
    s.receive(destination("dest", 1)).unwrap();
    let prior = s.usage().unwrap();
    super::tests::strip_v5(&s);
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    let mut s = Store::migrate_v4(&w.dir, Limits::default(), clock(1)).unwrap();
    assert_eq!(s.usage().unwrap().records, prior.records);
    assert_eq!(s.history(0, 100).unwrap().len(), 2);
    assert!(s.action("ui", 1, "a").unwrap().is_some());
    assert!(s.message_core("relay").unwrap().is_none());
    assert_eq!(
        s.message_remaining_ms("origin").unwrap_err().code,
        Code::UnsupportedVersion
    );
    assert_eq!(
        s.schedule_forward("relay", "other").unwrap_err().code,
        Code::UnsupportedVersion
    );
    assert_eq!(
        s.finish_delivery(
            "relay",
            &binding("relay"),
            Some((super::tests::PEER_2, b"proof")),
            5
        )
        .unwrap_err()
        .code,
        Code::UnsupportedVersion
    );
    assert_eq!(
        s.finalize_receipt("dest", b"synthetic intent", b"proof", 5)
            .unwrap_err()
            .code,
        Code::UnsupportedVersion
    );
    assert_eq!(
        s.receipt_intent("dest").err().unwrap().code,
        Code::UnsupportedVersion
    );
    let event = Batch {
        now_ms: 1,
        link: crate::retry::LinkEvent::Unchanged,
        signal: crate::retry::Signal::Continue,
        admission: crate::retry::Admission::Allow,
    };
    assert_eq!(
        s.advance_queue("origin", "data", super::tests::PEER_2, event)
            .unwrap_err()
            .code,
        Code::UnsupportedVersion
    );
    assert_eq!(
        s.receive(relay("relay")).unwrap_err().code,
        Code::UnsupportedVersion
    );
    let mut new = relay("new");
    new.expected_policy_revision = 0;
    s.receive(new).unwrap();
    assert!(s.message_core("new").unwrap().is_some());
    drop(s);
    assert_eq!(
        Store::migrate_v4(&w.dir, Limits::default(), clock(2))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
}

#[test]
fn migration_failure_and_cross_boot_leave_v4_intact() {
    for kind in ["before", "after", "boot", "sql"] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        super::tests::strip_v5(&s);
        if kind == "sql" {
            s.conn.execute_batch("CREATE TRIGGER reject_v5 BEFORE UPDATE ON meta BEGIN SELECT RAISE(ABORT,'synthetic migration failure'); END;").unwrap();
        }
        drop(s);
        let mut c = clock(1);
        if kind == "boot" {
            c.boot = "another-boot".into();
        }
        let mode = match kind {
            "before" => OpenMode::MigrateV4Fault(TestFault::BeforeCommit),
            "after" => OpenMode::MigrateV4Fault(TestFault::AfterCommit),
            _ => OpenMode::MigrateV4,
        };
        let error = Store::open_version(&w.dir, Limits::default(), c, mode)
            .err()
            .unwrap();
        assert_eq!(
            error.code,
            match kind {
                "after" => Code::OutcomeUnknown,
                "boot" => Code::TimeUncertain,
                _ => Code::StoreUnavailable,
            }
        );
        let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        let version: i64 = conn
            .pragma_query_value(None, "user_version", |r| r.get(0))
            .unwrap();
        assert_eq!(version, if kind == "after" { 7 } else { 4 });
        let has: bool = conn
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='message_data')",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(has, kind == "after");
        let payload: bool = conn
            .query_row("SELECT payload IS NOT NULL FROM messages", [], |r| r.get(0))
            .unwrap();
        assert!(payload);
    }
}

#[test]
fn admission_rejects_raw_core_payload_time_and_hop_bounds_without_partial_write() {
    for case in [
        "empty",
        "oversized",
        "epoch",
        "future",
        "time",
        "remaining",
        "hops",
        "binding",
        "payload",
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.create_action_scope("ui").unwrap();
        let mut input = destination("one", 0);
        match case {
            "empty" => input.message.data.raw.clear(),
            "oversized" => input.message.data.raw = vec![1; 513],
            "epoch" => {
                input.message.data.mls_epoch = u64::MAX;
                input.message.data.originated_at_ms = i64::MAX;
            }
            "future" => input.message.data.originated_at_ms = 100001,
            "time" => input.message.deadline_ms = 10001,
            "remaining" => input.remaining_lifetime_ms = 9999,
            "hops" => input.remaining_hops = 2,
            "binding" => input.message.core_binding = vec![1; 31],
            "payload" => input.message.payload = vec![1; 61441],
            _ => unreachable!(),
        }
        assert!(s.receive(input).is_err());
        assert!(s.message("one").unwrap().is_none());
        assert!(s.history(0, 10).unwrap().is_empty());
        let states: i64 = s
            .conn
            .query_row("SELECT count(*) FROM security_states", [], |r| r.get(0))
            .unwrap();
        assert_eq!(states, 0);
    }
    let w = Workspace::new();
    let mut s = w.create();
    let mut input = relay("one");
    input.message.data.raw = vec![1; 512];
    input.message.payload = vec![1; 61440];
    s.receive(input).unwrap();
}

#[test]
fn stored_metadata_corruption_is_rejected_before_output() {
    for sql in [
        "DELETE FROM message_data",
        "UPDATE messages SET data_version=0",
        "UPDATE messages SET deadline=10001",
        "UPDATE messages SET origin_ref='other'",
        "UPDATE message_data SET boot='other'",
        "UPDATE message_data SET originated_at=9223372036854775807",
        "UPDATE meta SET unix_upper_ms=102001",
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        s.conn.execute_batch(sql).unwrap();
        drop(s);
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::StoreCorrupt,
            "{sql}"
        );
    }
}

#[test]
fn reopened_same_monotonic_sample_uses_new_utc_upper_for_queue_decision() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("one", "a", 0)).unwrap();
    drop(s);
    let mut c = clock(0);
    c.trusted_utc = Some(UtcInterval {
        lower_ms: 110000,
        upper_ms: 110000,
    });
    let mut s = Store::open(&w.dir, Limits::default(), c).unwrap();
    let event = Batch {
        now_ms: 0,
        link: crate::retry::LinkEvent::Unchanged,
        signal: crate::retry::Signal::Continue,
        admission: crate::retry::Admission::Allow,
    };
    let decision = s
        .advance_queue("one", "data", super::tests::PEER_2, event)
        .unwrap();
    assert!(!decision.send);
    assert_eq!(decision.reason, crate::retry::Reason::Expired);
}

#[test]
fn core_identity_scopes_and_immutable_fields_are_all_compared() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    for field in 0..9 {
        let mut changed = relay("one");
        match field {
            0 => changed.message.data.raw.push(1),
            1 => changed.message.data.identity.activity_id = [9; 32],
            2 => changed.message.data.identity.origin_id = [9; 16],
            3 => changed.message.data.identity.message_id = [9; 16],
            4 => changed.message.data.destination_id = [9; 16],
            5 => changed.message.data.destination_credential_ref = [9; 32],
            6 => changed.message.data.mls_group_id = [9; 32],
            7 => changed.message.data.lifetime_ms += 1,
            8 => {
                changed.message.data.initial_hops = 1;
                changed.remaining_hops = 0;
            }
            _ => unreachable!(),
        }
        assert_eq!(s.receive(changed).unwrap_err().code, Code::Conflict);
    }
    for (key, field) in [("activity", 0), ("origin", 1), ("credential", 2)] {
        let mut distinct = relay(key);
        distinct.message.data.identity.message_id = relay("one").message.data.identity.message_id;
        match field {
            0 => distinct.message.data.identity.activity_id = [9; 32],
            1 => distinct.message.data.identity.origin_id = [9; 16],
            _ => distinct.message.data.identity.origin_credential_ref = [9; 32],
        };
        assert_eq!(s.receive(distinct).unwrap_err().code, Code::Conflict);
    }
    let mut distinct = relay("other-origin");
    distinct.message.data.identity.message_id = relay("one").message.data.identity.message_id;
    distinct.message.data.identity.origin_id = [4; 16];
    distinct.message.data.identity.origin_credential_ref = super::tests::test_credential(4);
    s.receive(distinct).unwrap();
    assert_eq!(s.usage().unwrap().payload_count, 2);
}

#[test]
fn data_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_DATA_TEST_STORE") else {
        return;
    };
    let fault = match std::env::var("RADISHLINK_DATA_TEST_SIDE").unwrap().as_str() {
        "before" => TestFault::CrashBeforeCommit,
        "after" => TestFault::CrashAfterCommit,
        _ => panic!("side"),
    };
    let operation = std::env::var("RADISHLINK_DATA_TEST_OPERATION").unwrap();
    if operation == "migration" {
        Store::open_version(
            Path::new(&dir),
            Limits::default(),
            clock(1),
            OpenMode::MigrateV4Fault(fault),
        )
        .unwrap();
    } else {
        let mut s = Store::open(Path::new(&dir), Limits::default(), clock(1)).unwrap();
        s.fault = Some(fault);
        if operation == "receive" {
            s.receive(destination("one", 0)).unwrap();
        } else {
            let mut input = relay("one");
            input.message.deadline_ms = 500;
            s.receive(input).unwrap();
        }
    }
    panic!("expected controlled exit");
}

#[test]
fn process_exit_keeps_atomic_d15_metadata_migration_and_shortening() {
    for operation in ["migration", "receive", "shorten"] {
        for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
            let w = Workspace::new();
            let mut s = w.create();
            if operation != "receive" {
                s.receive(relay("one")).unwrap();
                s.schedule_forward("one", super::tests::PEER_3).unwrap();
            }
            if operation == "migration" {
                super::tests::strip_v5(&s);
            }
            drop(s);
            let status = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::data_tests::data_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_DATA_TEST_STORE", &w.dir)
                .env("RADISHLINK_DATA_TEST_SIDE", side)
                .env("RADISHLINK_DATA_TEST_OPERATION", operation)
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(exit));
            let s = if operation == "migration" && !committed {
                Store::migrate_v4(&w.dir, Limits::default(), clock(2)).unwrap()
            } else {
                w.reopen(2)
            };
            match operation {
                "migration" => {
                    assert!(s.message_core("one").unwrap().is_none());
                    assert!(s.message("one").unwrap().unwrap().payload_present);
                }
                "receive" => {
                    assert_eq!(s.message_core("one").unwrap().is_some(), committed);
                    assert_eq!(s.history(0, 10).unwrap().len(), usize::from(committed));
                }
                _ => {
                    assert_eq!(
                        s.message_remaining_ms("one").unwrap(),
                        if committed { 498 } else { 9998 }
                    );
                    s.check_queue_deadlines(false).unwrap();
                }
            }
        }
    }
}
