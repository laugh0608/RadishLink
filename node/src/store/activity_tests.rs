use super::tests::{ACTIVITY, PEER_3, Workspace, clock, relay, send, test_credential};
use super::*;
const NEW: ActivityId = [42; 32];

/// Test-only reconstruction from the unchanged historical SQL, never a product downgrade.
/// Fixtures must contain at most the original activity; stopping is an explicit test input.
pub(super) fn strip_v8(s: &Store, stopped: bool) {
    let tables = [
        (
            "control_activity",
            "id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision",
        ),
        (
            "control_bindings",
            "credential,participant,generation,body,state",
        ),
        (
            "control_objects",
            "reference,kind,issuer,reporter,target,operation,reason,payload,body,accepted",
        ),
        (
            "control_neighbors",
            "object,participant,start,next_slot,recoveries,last_recovery,link_up,terminal,attempts,ack_attempts,last_ms,last_event",
        ),
        (
            "control_output_rate",
            "id,last_ms,frames,bytes,exit_cursor,ordinary_cursor",
        ),
    ];
    for (t, cols) in tables {
        s.conn
            .execute_batch(&format!(
                "CREATE TEMP TABLE saved_{t} AS SELECT {cols} FROM {t};"
            ))
            .unwrap();
    }
    for t in [
        "control_activity",
        "control_bindings",
        "control_objects",
        "control_neighbors",
    ] {
        for op in ["update", "delete"] {
            s.conn
                .execute_batch(&format!("DROP TRIGGER {t}_archive_{op};"))
                .unwrap();
        }
    }
    for t in [
        "control_bindings",
        "control_objects",
        "control_neighbors",
        "security_states",
    ] {
        s.conn
            .execute_batch(&format!("DROP TRIGGER {t}_current_insert;"))
            .unwrap();
    }
    s.conn.execute_batch("DROP TRIGGER security_states_archive_update; DROP TRIGGER security_states_archive_delete;").unwrap();
    s.conn.execute_batch("DROP VIEW activity_archive_usage; DROP VIEW current_control_neighbors; DROP VIEW current_control_objects; DROP VIEW current_control_bindings; DROP VIEW current_control_activity;
        ALTER TABLE meta DROP COLUMN current_activity; DROP INDEX action_scope_activity; ALTER TABLE action_scopes DROP COLUMN activity; ALTER TABLE action_scopes DROP COLUMN retired;
        DROP TABLE control_neighbors; DROP TABLE control_objects; DROP TABLE control_bindings; DROP TABLE control_activity; DROP TABLE control_output_rate;
        CREATE TEMP TABLE saved_security AS SELECT session,revision,state FROM security_states; DROP TABLE security_states;
        CREATE TABLE security_states(session TEXT PRIMARY KEY,revision INTEGER NOT NULL CHECK(revision>0),state BLOB NOT NULL CHECK(length(state) BETWEEN 1 AND 65536)) STRICT;
        INSERT INTO security_states SELECT * FROM saved_security; DROP TABLE saved_security;").unwrap();
    s.conn
        .execute_batch(include_str!("migration_v4.sql"))
        .unwrap();
    s.conn.execute_batch("ALTER TABLE control_activity ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 0 CHECK(policy_revision>=0); ALTER TABLE control_output_rate ADD COLUMN exit_cursor TEXT CHECK(length(exit_cursor)<=512); ALTER TABLE control_output_rate ADD COLUMN ordinary_cursor TEXT CHECK(length(ordinary_cursor)<=512);").unwrap();
    for (t, cols) in tables {
        s.conn
            .execute_batch(&format!(
                "INSERT INTO {t}({cols}) SELECT {cols} FROM saved_{t}; DROP TABLE saved_{t};"
            ))
            .unwrap();
    }
    if stopped {
        s.conn
            .execute_batch(
                "UPDATE control_activity SET stopped=1; UPDATE messages SET policy_stopped=1;",
            )
            .unwrap();
    }
    s.conn.execute_batch("PRAGMA user_version=7;").unwrap();
}
fn request(s: &Store) -> ActivitySwitch {
    let p = s.preflight_activity_switch().unwrap();
    ActivitySwitch {
        previous_activity: p.previous.activity,
        expected_policy_revision: p.previous.policy_revision,
        activity: NEW,
        local_participant: [11; 16],
        deadline_ms: MAX_ACTIVITY_MS,
    }
}
fn switched(s: &mut Store) {
    s.stop_control_activity(ACTIVITY).unwrap();
    s.switch_control_activity(request(s)).unwrap();
}
fn prepare_new(s: &mut Store) {
    for n in 11..=15 {
        s.stage_control_binding(
            NEW,
            ControlBinding {
                participant: [n; 16],
                credential: test_credential(n),
                generation: 1,
                body: vec![n],
            },
        )
        .unwrap();
        s.activate_control_binding(NEW, test_credential(n), &[n])
            .unwrap();
    }
}
fn new_send() -> Send {
    let mut v = send("new", "new-action", 0);
    v.message.data.identity.activity_id = NEW;
    v.message.data.identity.origin_id = [11; 16];
    v.message.data.identity.origin_credential_ref = test_credential(11);
    v.message.data.destination_id = [12; 16];
    v.message.data.destination_credential_ref = test_credential(12);
    v.neighbor = credential_key(&test_credential(12));
    v.action.scope = "new-ui".into();
    v
}
#[test]
fn stopped_switch_preserves_history_and_isolates_sessions_actions_and_business() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("old", "old-action", 0)).unwrap();
    s.receive(relay("relay")).unwrap();
    let before = s.message_core("old").unwrap();
    let plan = s.preflight_activity_switch().unwrap();
    assert_eq!(
        (plan.archive_bytes, plan.archive_records),
        (4096 + 5 * 1024, 6)
    );
    assert_eq!(
        s.switch_control_activity(request(&s)).unwrap_err().code,
        Code::Conflict
    );
    switched(&mut s);
    assert!(s.message_core("old").unwrap() == before);
    assert!(s.message("old").unwrap().unwrap().payload_present);
    assert!(s.message("old").unwrap().unwrap().policy_stopped);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert_eq!(
        s.action("ui", 1, "old-action").unwrap_err().code,
        Code::Expired
    );
    assert_eq!(
        s.conn
            .query_row("SELECT count(*) FROM actions", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        s.schedule_forward("relay", PEER_3).unwrap_err().code,
        Code::Conflict
    );
    assert_eq!(s.control_binding_state(test_credential(1)).unwrap(), None);
    s.create_action_scope("new-ui").unwrap();
    assert_eq!(s.submit(new_send()).unwrap_err().code, Code::Conflict); // No trust inferred.
    prepare_new(&mut s);
    s.submit(new_send()).unwrap();
    assert_eq!(
        s.conn
            .query_row(
                "SELECT count(*) FROM security_states WHERE session='session' AND revision=1",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        2
    );
    assert_eq!(
        s.usage().unwrap().archived_control_bytes,
        plan.archive_bytes
    );
    drop(s);
    let s = w.reopen(1);
    assert_eq!(
        s.activity_status(ACTIVITY).unwrap().unwrap().successor,
        Some(NEW)
    );
    assert_eq!(s.current_activity_id().unwrap(), NEW);
    assert_eq!(s.history(0, 100).unwrap().len(), 2);
}
#[test]
fn old_ids_and_preparations_cannot_be_reused() {
    let w = Workspace::new();
    let mut s = w.create();
    s.stop_control_activity(ACTIVITY).unwrap();
    for (id, local) in [(ACTIVITY, [11; 16]), (NEW, [1; 16]), (NEW, [3; 16])] {
        let mut r = request(&s);
        r.activity = id;
        r.local_participant = local;
        assert_eq!(
            s.switch_control_activity(r).unwrap_err().code,
            Code::Conflict
        );
    }
    let mut stale = request(&s);
    stale.expected_policy_revision -= 1;
    assert_eq!(
        s.switch_control_activity(stale).unwrap_err().code,
        Code::Conflict
    );
    s.switch_control_activity(request(&s)).unwrap();
    for (participant, credential) in [
        ([2; 16], test_credential(12)),
        ([12; 16], test_credential(2)),
    ] {
        assert_eq!(
            s.stage_control_binding(
                NEW,
                ControlBinding {
                    participant,
                    credential,
                    generation: 1,
                    body: vec![1]
                }
            )
            .unwrap_err()
            .code,
            Code::Conflict
        );
    }
    assert!(
        s.activate_control_binding(NEW, test_credential(2), &[2, 1])
            .is_err()
    );
    assert!(s.block_control_binding(NEW, test_credential(2)).is_err());
    assert!(s.activity_status(ACTIVITY).unwrap().unwrap().archived);
}
#[test]
fn pending_and_leased_verification_must_be_explicitly_drained() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(1000)).unwrap();
    s.queue_control_candidate(ACTIVITY, test_credential(2), b"synthetic-a")
        .unwrap();
    s.queue_control_candidate(ACTIVITY, test_credential(3), b"synthetic-b")
        .unwrap();
    let job = s.next_control_verification().unwrap().job.unwrap();
    s.stop_control_activity(ACTIVITY).unwrap();
    assert_eq!(
        s.switch_control_activity(request(&s)).unwrap_err().code,
        Code::Busy
    );
    assert_eq!(s.next_control_verification().unwrap().discarded.len(), 1);
    assert_eq!(
        s.switch_control_activity(request(&s)).unwrap_err().code,
        Code::Busy
    );
    s.cancel_control_verification(job).unwrap();
    s.switch_control_activity(request(&s)).unwrap();
    prepare_new(&mut s);
    assert_eq!(
        s.queue_control_candidate(NEW, test_credential(12), b"new")
            .unwrap(),
        ControlIngressAdmission::RateLimited
    );
    assert_eq!(s.control_ingress_usage().verifying, 0);
    assert_eq!(
        s.conn
            .query_row("SELECT frames+bytes FROM control_output_rate", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}
#[test]
fn archive_capacity_exact_bytes_and_records_and_stop_without_capacity() {
    for (byte_delta, record_delta, global_delta, pass) in [
        (0, 0, 0, true),
        (-1, 0, 0, false),
        (0, -1, 0, false),
        (0, 0, -1, false),
    ] {
        let w = Workspace::new();
        let mut s = w.create_bare();
        s.start_control_activity(ACTIVITY, [1; 16], MAX_ACTIVITY_MS)
            .unwrap();
        s.limits.control_bytes = (CONTROL_RESERVED_BYTES as i64 + 4096 + byte_delta) as u64;
        s.limits.control_count = (i64::from(CONTROL_RESERVED_RECORDS) + 1 + record_delta) as u32;
        s.limits.record_count = (i64::from(CONTROL_RESERVED_RECORDS) + 1 + global_delta) as u32;
        // Local stop needs no archive allocation even when no archive slot remains.
        s.stop_control_activity(ACTIVITY).unwrap();
        let r = s.switch_control_activity(request(&s));
        if pass {
            assert!(r.is_ok());
        } else {
            assert_eq!(r.unwrap_err().code, Code::Quota);
            assert!(s.activity_status(ACTIVITY).unwrap().unwrap().stopped);
            assert_eq!(s.current_activity_id().unwrap(), ACTIVITY);
        }
    }
}
#[test]
fn multiple_empty_archives_are_charged_and_cannot_be_deleted() {
    let w = Workspace::new();
    let mut s = w.create_bare();
    s.start_control_activity(ACTIVITY, [1; 16], MAX_ACTIVITY_MS)
        .unwrap();
    switched(&mut s);
    s.stop_control_activity(NEW).unwrap();
    let mut r = request(&s);
    r.activity = [43; 32];
    r.local_participant = [12; 16];
    s.switch_control_activity(r).unwrap();
    let u = s.usage().unwrap();
    assert_eq!(
        (u.archived_control_bytes, u.archived_control_records),
        (8192, 2)
    );
    assert!(
        s.conn
            .execute(
                "DELETE FROM control_activity WHERE activity=?1",
                [ACTIVITY.as_slice()]
            )
            .is_err()
    );
    drop(s);
    assert_eq!(w.reopen(1).usage().unwrap().archived_control_records, 2);
}
#[test]
fn switch_commit_faults_preserve_stop_or_complete_new_context() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.create_action_scope("ui").unwrap();
        s.submit(send("old", "a", 0)).unwrap();
        s.stop_control_activity(ACTIVITY).unwrap();
        s.fault = Some(fault);
        let e = s.switch_control_activity(request(&s)).unwrap_err();
        assert_eq!(
            e.code,
            if fault == TestFault::BeforeCommit {
                Code::StoreUnavailable
            } else {
                Code::OutcomeUnknown
            }
        );
        drop(s);
        let s = w.reopen(1);
        let committed = fault == TestFault::AfterCommit;
        assert_eq!(
            s.current_activity_id().unwrap(),
            if committed { NEW } else { ACTIVITY }
        );
        assert_eq!(
            s.activity_status(ACTIVITY).unwrap().unwrap().archived,
            committed
        );
        assert!(s.message("old").unwrap().unwrap().payload_present);
        assert!(s.message("old").unwrap().unwrap().policy_stopped);
    }
}
#[test]
fn cross_boot_and_time_regression_never_unlock_activity_switch() {
    for boot_change in [true, false] {
        let w = Workspace::new();
        let mut s = w.create();
        s.advance_clock(clock(10)).unwrap();
        s.stop_control_activity(ACTIVITY).unwrap();
        let r = request(&s);
        drop(s);
        let mut c = clock(if boot_change { 10 } else { 9 });
        if boot_change {
            c.boot = "new-boot".into();
        }
        let mut s = Store::open(&w.dir, Limits::default(), c).unwrap();
        assert!(s.is_time_uncertain());
        assert_eq!(
            s.switch_control_activity(r).unwrap_err().code,
            Code::TimeUncertain
        );
        assert_eq!(s.current_activity_id().unwrap(), ACTIVITY);
    }
}
#[test]
fn migration_requires_explicit_stop_and_quarantines_legacy_sessions_and_actions() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("old", "a", 0)).unwrap();
    strip_v8(&s, false);
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    assert_eq!(
        Store::migrate_v7(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    {
        let c = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        c.execute_batch(
            "UPDATE control_activity SET stopped=1; UPDATE messages SET policy_stopped=1;",
        )
        .unwrap();
    }
    let mut s = Store::migrate_v7(&w.dir, Limits::default(), clock(1)).unwrap();
    assert_eq!(s.action("ui", 1, "a").unwrap_err().code, Code::Expired);
    assert_eq!(
        s.conn
            .query_row("SELECT length(activity) FROM security_states", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert_eq!(
        s.conn
            .query_row("SELECT count(*) FROM actions", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        1
    );
    s.switch_control_activity(request(&s)).unwrap();
    prepare_new(&mut s);
    s.create_action_scope("new-ui").unwrap();
    s.submit(new_send()).unwrap();
    assert_eq!(
        s.conn
            .query_row("SELECT count(*) FROM security_states", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        2
    );
    drop(s);
    assert_eq!(
        Store::migrate_v7(&w.dir, Limits::default(), clock(2))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
}
#[test]
fn migration_faults_leave_whole_source_or_whole_v8() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let s = w.create();
        strip_v8(&s, true);
        drop(s);
        let e = Store::open_version(
            &w.dir,
            Limits::default(),
            clock(1),
            OpenMode::MigrateV7Fault(fault),
        )
        .err()
        .unwrap();
        assert_eq!(
            e.code,
            if fault == TestFault::BeforeCommit {
                Code::StoreUnavailable
            } else {
                Code::OutcomeUnknown
            }
        );
        let c = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        assert_eq!(
            c.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                .unwrap(),
            if fault == TestFault::BeforeCommit {
                7
            } else {
                8
            }
        );
    }
}

#[test]
fn renewed_scope_keeps_old_action_facts_and_requires_new_generation() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("old", "a", 0)).unwrap();
    assert_eq!(
        s.renew_action_scope("ui", 1).unwrap_err().code,
        Code::Conflict
    );
    switched(&mut s);
    prepare_new(&mut s);
    assert_eq!(
        s.renew_action_scope("ui", 2).unwrap_err().code,
        Code::Conflict
    );
    assert_eq!(s.renew_action_scope("ui", 1).unwrap(), 2);
    assert_eq!(s.action("ui", 1, "a").unwrap_err().code, Code::Expired);
    assert!(s.action("ui", 2, "a").unwrap().is_none());
    let mut v = new_send();
    v.action.scope = "ui".into();
    v.action.generation = 2;
    v.action.reference = "a".into();
    s.submit(v).unwrap();
    assert_eq!(
        s.conn
            .query_row(
                "SELECT count(*) FROM actions WHERE scope='ui' AND reference='a'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        2
    );
    assert_eq!(
        s.renew_action_scope("ui", 2).unwrap_err().code,
        Code::Conflict
    );
}
#[test]
fn every_switch_write_failure_rolls_back_archive_pointer_scopes_and_rate() {
    for trigger in [
        "BEFORE UPDATE ON control_activity",
        "BEFORE UPDATE ON action_scopes",
        "BEFORE INSERT ON control_activity",
        "BEFORE UPDATE OF current_activity ON meta",
        "BEFORE UPDATE ON control_output_rate",
        "BEFORE UPDATE OF monotonic_ms ON meta",
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.create_action_scope("ui").unwrap();
        s.stop_control_activity(ACTIVITY).unwrap();
        let before = s.preflight_activity_switch().unwrap();
        s.conn.execute_batch(&format!("CREATE TRIGGER reject_switch {trigger} BEGIN SELECT RAISE(ABORT,'synthetic switch write failure'); END;")).unwrap();
        assert_eq!(
            s.switch_control_activity(request(&s)).unwrap_err().code,
            Code::StoreUnavailable
        );
        assert_eq!(s.preflight_activity_switch().unwrap(), before);
        assert_eq!(s.activity_status(NEW).unwrap(), None);
        assert_eq!(
            s.conn
                .query_row(
                    "SELECT retired FROM action_scopes WHERE scope='ui'",
                    [],
                    |r| r.get::<_, i64>(0)
                )
                .unwrap(),
            0
        );
        assert_eq!(
            s.conn
                .query_row("SELECT count(*) FROM control_activity", [], |r| r
                    .get::<_, i64>(0))
                .unwrap(),
            1
        );
    }
}
fn report() -> PreparedControl {
    PreparedControl {
        fields: ControlPayload {
            activity: ACTIVITY,
            kind: ControlKind::Report,
            issuer: test_credential(3),
            issuer_id: [3; 16],
            target: test_credential(2),
            target_id: [2; 16],
            operation: [9; 16],
            reason: 0,
            reference: [9; 32],
            payload: vec![3, 2, 9],
        },
        cose: vec![1, 3, 2, 9],
    }
}
#[test]
fn archived_objects_attempts_ack_budgets_and_original_bytes_are_immutable() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("relay")).unwrap();
    s.accept_control(
        report(),
        &[ControlNeighbor {
            participant: [2; 16],
            link: Link::Up,
        }],
    )
    .unwrap();
    s.process_outbound_batch(
        clock(1000),
        vec![
            OutboundEvent::Control(ControlEvent {
                object: [9; 32],
                neighbor: [2; 16],
                link: crate::retry::LinkEvent::Unchanged,
                signal: crate::retry::Signal::Continue,
                admission: crate::retry::Admission::Allow,
            }),
            OutboundEvent::DataAck {
                message: "relay".into(),
                neighbor: super::tests::PEER_2.into(),
            },
        ],
    )
    .unwrap();
    let progress = s.control_progress([9; 32], [2; 16]).unwrap().unwrap();
    assert_eq!(progress.attempts, 1);
    let ack: String = s
        .conn
        .query_row(
            "SELECT data_ack_budget FROM messages WHERE key='relay'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    switched(&mut s);
    prepare_new(&mut s);
    assert_eq!(s.control_object(NEW, [9; 32]).unwrap(), None);
    assert_eq!(s.control_progress([9; 32], [2; 16]).unwrap(), None);
    assert_eq!(
        s.conn
            .query_row("SELECT attempts FROM control_neighbors", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert_eq!(
        s.conn
            .query_row("SELECT body FROM control_objects", [], |r| r
                .get::<_, Vec<u8>>(0))
            .unwrap(),
        report().cose
    );
    assert_eq!(
        s.conn
            .query_row(
                "SELECT data_ack_budget FROM messages WHERE key='relay'",
                [],
                |r| r.get::<_, String>(0)
            )
            .unwrap(),
        ack
    );
    assert!(
        s.conn
            .execute("UPDATE control_neighbors SET attempts=0", [])
            .is_err()
    );
    assert_eq!(
        s.schedule_control_neighbor(
            NEW,
            [9; 32],
            ControlNeighbor {
                participant: [12; 16],
                link: Link::Up
            }
        )
        .unwrap_err()
        .code,
        Code::Conflict
    );
    assert_eq!(
        s.usage().unwrap().archived_control_bytes,
        4096 + 5 * 1024 + 4096 + 512
    );
    drop(s);
    assert!(
        w.reopen(1001)
            .message("relay")
            .unwrap()
            .unwrap()
            .policy_stopped
    );
}
#[test]
fn old_worker_result_after_reopen_and_switch_cannot_match_new_owner() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(1000)).unwrap();
    s.queue_control_candidate(ACTIVITY, test_credential(2), b"old")
        .unwrap();
    let job = s.next_control_verification().unwrap().job.unwrap();
    drop(s);
    let mut s = w.reopen(1000);
    switched(&mut s);
    assert_eq!(
        s.complete_control_verification(job, ControlVerificationOutcome::Rejected, &[])
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert_eq!(s.control_ingress_usage().waiting, 0);
}
#[test]
fn lifecycle_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_ACTIVITY_TEST_STORE") else {
        return;
    };
    let fault = match std::env::var("RADISHLINK_ACTIVITY_TEST_SIDE")
        .unwrap()
        .as_str()
    {
        "before" => TestFault::CrashBeforeCommit,
        "after" => TestFault::CrashAfterCommit,
        _ => panic!("side"),
    };
    if std::env::var("RADISHLINK_ACTIVITY_TEST_OPERATION").unwrap() == "migration" {
        Store::open_version(
            Path::new(&dir),
            Limits::default(),
            clock(1),
            OpenMode::MigrateV7Fault(fault),
        )
        .unwrap();
    } else {
        let mut s = Store::open(Path::new(&dir), Limits::default(), clock(1)).unwrap();
        s.fault = Some(fault);
        s.switch_control_activity(request(&s)).unwrap();
    }
    panic!("expected controlled exit");
}
#[test]
fn process_exit_recovers_entire_switch_and_migration() {
    for operation in ["switch", "migration"] {
        for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
            let w = Workspace::new();
            let mut s = w.create();
            s.create_action_scope("ui").unwrap();
            s.submit(send("old", "a", 0)).unwrap();
            s.stop_control_activity(ACTIVITY).unwrap();
            if operation == "migration" {
                strip_v8(&s, true);
            }
            drop(s);
            let status = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::activity_tests::lifecycle_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_ACTIVITY_TEST_STORE", &w.dir)
                .env("RADISHLINK_ACTIVITY_TEST_SIDE", side)
                .env("RADISHLINK_ACTIVITY_TEST_OPERATION", operation)
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(exit));
            let c = Connection::open(w.dir.join("node.sqlite3")).unwrap();
            assert_eq!(
                c.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                    .unwrap(),
                if operation == "migration" && !committed {
                    7
                } else {
                    8
                }
            );
            drop(c);
            let s = if operation == "migration" && !committed {
                Store::migrate_v7(&w.dir, Limits::default(), clock(2)).unwrap()
            } else {
                w.reopen(2)
            };
            assert_eq!(
                s.current_activity_id().unwrap(),
                if operation == "switch" && committed {
                    NEW
                } else {
                    ACTIVITY
                }
            );
            assert!(s.message("old").unwrap().unwrap().payload_present);
            assert!(s.message("old").unwrap().unwrap().policy_stopped);
            assert_eq!(s.history(0, 100).unwrap().len(), 1);
            assert_eq!(
                s.conn
                    .query_row("SELECT count(*) FROM actions", [], |r| r.get::<_, i64>(0))
                    .unwrap(),
                1
            );
        }
    }
}

#[test]
fn existing_business_reservation_is_never_spent_on_archive() {
    for shortage in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("relay")).unwrap();
        let archive = s.preflight_activity_switch().unwrap().archive_bytes;
        s.limits.control_bytes = CONTROL_RESERVED_BYTES + 4096 + archive - u64::from(shortage);
        s.stop_control_activity(ACTIVITY).unwrap();
        let before = s.usage().unwrap();
        let result = s.switch_control_activity(request(&s));
        if shortage {
            assert_eq!(result.unwrap_err().code, Code::Quota);
        } else {
            result.unwrap();
        }
        let after = s.usage().unwrap();
        assert_eq!(after.reserved_control_bytes, before.reserved_control_bytes);
        assert_eq!(after.payload_bytes, before.payload_bytes);
        assert_eq!(after.payload_count, 1);
    }
}
#[test]
fn archived_association_and_summary_corruption_are_rejected_on_open() {
    for sql in [
        "UPDATE meta SET current_activity=(SELECT activity FROM control_activity WHERE archived=1)",
        "DROP TRIGGER control_activity_archive_update; UPDATE control_activity SET final_rate='{\"extra\":1}' WHERE archived=1",
        "DROP TRIGGER control_activity_archive_update; UPDATE control_activity SET successor=zeroblob(32) WHERE archived=1",
        "DROP TRIGGER control_bindings_archive_update; UPDATE control_bindings SET participant=zeroblob(16) WHERE credential=X'0101010101010101010101010101010101010101010101010101010101010101'",
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.create_action_scope("ui").unwrap();
        s.submit(send("old", "a", 0)).unwrap();
        switched(&mut s);
        s.conn.execute_batch(sql).unwrap();
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
fn empty_source_migrates_without_fabricating_activity_and_archived_security_is_readonly() {
    let w = Workspace::new();
    let s = w.create_bare();
    strip_v8(&s, false);
    drop(s);
    let mut s = Store::migrate_v7(&w.dir, Limits::default(), clock(1)).unwrap();
    assert!(s.current_activity_id().is_err());
    super::tests::prepare_business(&mut s);
    s.create_action_scope("ui").unwrap();
    s.submit(send("old", "a", 0)).unwrap();
    switched(&mut s);
    assert!(
        s.conn
            .execute(
                "UPDATE security_states SET revision=revision+1 WHERE session='session'",
                []
            )
            .is_err()
    );
    assert!(
        s.conn
            .execute("DELETE FROM security_states WHERE session='session'", [])
            .is_err()
    );
}
