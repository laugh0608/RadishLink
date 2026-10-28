use super::tests::{ACTIVITY, Workspace, clock, relay, test_credential};
use super::*;
#[test]
fn exact_endpoint_revocation_stops_existing_responsibility() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.block_control_binding(ACTIVITY, test_credential(3))
        .unwrap();
    assert!(s.message("one").unwrap().unwrap().policy_stopped);
    assert_eq!(
        s.schedule_forward("one", &credential_key(&test_credential(3)))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    drop(s);
    assert!(w.reopen(1).message("one").unwrap().unwrap().policy_stopped);
}
#[test]
fn policy_migration_fault_is_atomic() {
    let w = Workspace::new();
    let s = w.create();
    super::tests::strip_v6(&s);
    drop(s);
    assert_eq!(
        Store::open_version(
            &w.dir,
            Limits::default(),
            clock(1),
            OpenMode::MigrateV5Fault(TestFault::BeforeCommit)
        )
        .err()
        .unwrap()
        .code,
        Code::StoreUnavailable
    );
    let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
    assert_eq!(
        conn.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
            .unwrap(),
        5
    );
}

fn object(issuer: u8, target: u8, operation: u8) -> PreparedControl {
    PreparedControl {
        fields: ControlPayload {
            activity: ACTIVITY,
            kind: if issuer == target {
                ControlKind::Exit
            } else {
                ControlKind::Report
            },
            issuer: test_credential(issuer),
            issuer_id: [issuer; 16],
            target: test_credential(target),
            target_id: [target; 16],
            operation: [operation; 16],
            reason: 0,
            reference: [operation; 32],
            payload: vec![issuer, target, operation],
        },
        cose: vec![1, issuer, target, operation],
    }
}
fn event(now_ms: i64) -> Batch {
    Batch {
        now_ms,
        link: crate::retry::LinkEvent::Unchanged,
        signal: crate::retry::Signal::Continue,
        admission: crate::retry::Admission::Allow,
    }
}
fn revision(s: &Store) -> i64 {
    s.business_policy_revision(ACTIVITY).unwrap()
}
fn replace(s: &mut Store, n: u8) -> CredentialRef {
    let mut credential = test_credential(n);
    credential[31] = 2;
    s.stage_control_binding(
        ACTIVITY,
        ControlBinding {
            participant: [n; 16],
            credential,
            generation: 2,
            body: vec![n, 2],
        },
    )
    .unwrap();
    s.activate_control_binding(ACTIVITY, credential, &[n, 2])
        .unwrap();
    credential
}

#[test]
fn absent_pending_mismatched_endpoints_roles_and_neighbor_aliases_are_rejected() {
    let w = Workspace::new();
    let mut s = w.create_bare();
    assert_eq!(s.receive(relay("one")).unwrap_err().code, Code::Conflict);
    super::tests::prepare_business(&mut s);
    for case in 0..6 {
        let mut input = relay("one");
        match case {
            0 => input.message.data.identity.activity_id = [9; 32],
            1 => input.message.data.identity.origin_credential_ref = test_credential(4),
            2 => input.message.data.destination_credential_ref = [9; 32],
            3 => {
                input.message.data.destination_id = [1; 16];
                input.message.data.destination_credential_ref = test_credential(1);
            }
            4 => input.neighbor = "nickname".into(),
            5 => input.neighbor = credential_key(&test_credential(1)),
            _ => unreachable!(),
        }
        assert!(s.receive(input).is_err());
    }
    let mut pending = test_credential(2);
    pending[31] = 2;
    s.stage_control_binding(
        ACTIVITY,
        ControlBinding {
            participant: [2; 16],
            credential: pending,
            generation: 2,
            body: vec![2, 2],
        },
    )
    .unwrap();
    let mut input = relay("one");
    input.message.data.identity.origin_credential_ref = pending;
    assert_eq!(s.receive(input).unwrap_err().code, Code::Conflict);
    assert!(s.message("one").unwrap().is_none());
}

#[test]
fn prepared_work_revision_is_rechecked_before_security_state_or_history_changes() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    let input = super::tests::send("send", "a", 0);
    s.block_control_binding(ACTIVITY, test_credential(5))
        .unwrap();
    assert_eq!(s.submit(input).unwrap_err().code, Code::Conflict);
    assert_eq!(
        s.receive(super::tests::destination("dest", 0))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(
        s.conn
            .query_row("SELECT count(*) FROM security_states", [], |r| r
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
    assert!(s.history(0, 10).unwrap().is_empty());
    let mut input = super::tests::send("send", "a", 0);
    input.expected_policy_revision = revision(&s);
    s.submit(input).unwrap();
    drop(s);
    let s = w.reopen(1);
    assert_eq!(revision(&s), 6);
}

#[test]
fn endpoint_source_and_queued_neighbor_revocations_cancel_only_affected_work() {
    for target in [1, 2, 3, 4, 5] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        s.schedule_forward("one", &credential_key(&test_credential(4)))
            .unwrap();
        s.block_control_binding(ACTIVITY, test_credential(target))
            .unwrap();
        let view = s.message("one").unwrap().unwrap();
        assert_eq!(view.policy_stopped, target != 5);
        assert!(view.payload_present);
        if target != 5 {
            assert!(
                s.advance_queue(
                    "one",
                    "data",
                    &credential_key(&test_credential(4)),
                    event(0)
                )
                .is_err()
            );
        } else {
            assert!(
                s.advance_queue(
                    "one",
                    "data",
                    &credential_key(&test_credential(4)),
                    event(0)
                )
                .unwrap()
                .send
            );
        }
    }
}

#[test]
fn signer_completion_and_both_proof_legs_recheck_current_policy() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(super::tests::destination("dest", 0)).unwrap();
    let intent = s.receipt_intent("dest").unwrap().unwrap();
    assert_eq!(intent.policy_revision, 5);
    s.block_control_binding(ACTIVITY, test_credential(5))
        .unwrap();
    assert_eq!(
        s.finalize_receipt("dest", &intent.body, b"proof", intent.policy_revision)
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let fresh = s.receipt_intent("dest").unwrap().unwrap();
    s.finalize_receipt("dest", &fresh.body, b"proof", fresh.policy_revision)
        .unwrap();
    let mut relay = relay("relay");
    relay.expected_policy_revision = revision(&s);
    s.receive(relay).unwrap();
    s.create_action_scope("ui").unwrap();
    let mut send = super::tests::send("origin", "a", 1);
    send.expected_policy_revision = revision(&s);
    s.submit(send).unwrap();
    let checked = revision(&s);
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    assert!(
        s.validate_business_output("dest", "evidence", super::tests::PEER_2, checked)
            .is_err()
    );
    assert!(
        s.finish_delivery(
            "relay",
            &super::tests::binding("relay"),
            Some((super::tests::PEER_2, b"proof")),
            checked
        )
        .is_err()
    );
    // The origin's queued neighbor is the revoked credential even though destination remains active.
    assert!(
        s.finish_delivery("origin", &super::tests::binding("origin"), None, checked)
            .is_err()
    );
    let done = s.maintain(s.current_clock()).unwrap();
    assert_eq!(done.stopped_evidence, 1);
    assert_eq!(s.history(0, 10).unwrap().len(), 2);
    assert_eq!(s.message("dest").unwrap().unwrap().state, "committed");
    assert!(s.message("relay").unwrap().unwrap().payload_present);
}

#[test]
fn retained_exit_is_the_only_control_exception_to_local_retirement() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.receive(super::tests::destination("dest", 0)).unwrap();
    s.begin_control_exit(object(1, 1, 7).fields).unwrap();
    assert!(s.message("one").unwrap().unwrap().policy_stopped);
    assert!(s.receipt_intent("dest").is_err());
    s.accept_control(
        object(1, 1, 7),
        &[ControlNeighbor {
            participant: [2; 16],
            link: Link::Up,
        }],
    )
    .unwrap();
    let output = s
        .process_control_batch(
            ACTIVITY,
            clock(1000),
            vec![ControlEvent {
                object: [7; 32],
                neighbor: [2; 16],
                link: crate::retry::LinkEvent::Unchanged,
                signal: crate::retry::Signal::Continue,
                admission: crate::retry::Admission::Allow,
            }],
        )
        .unwrap();
    assert!(output[0].send);
    assert!(!s.consume_control_ack(ACTIVITY, [7; 32], [2; 16]).unwrap());
    let report = s.maintain(s.current_clock()).unwrap();
    assert_eq!(report.stopped_receipt_intents, 0); // Unified round already cleaned the stopped intent.
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
}

#[test]
fn reports_do_not_revoke_but_verified_exit_commits_stop_with_original_object() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.accept_control(object(4, 3, 8), &[]).unwrap();
    assert_eq!(revision(&s), 5);
    assert!(!s.message("one").unwrap().unwrap().policy_stopped);
    s.accept_control(
        object(3, 3, 9),
        &[ControlNeighbor {
            participant: [4; 16],
            link: Link::Up,
        }],
    )
    .unwrap();
    assert_eq!(revision(&s), 6);
    assert!(s.message("one").unwrap().unwrap().policy_stopped);
    assert_eq!(
        s.control_object(ACTIVITY, [9; 32]).unwrap().unwrap(),
        vec![1, 3, 3, 9]
    );
    let before = revision(&s);
    s.accept_control(object(3, 3, 9), &[]).unwrap();
    assert_eq!(revision(&s), before);
    let out = s
        .process_control_batch(
            ACTIVITY,
            clock(1000),
            vec![ControlEvent {
                object: [9; 32],
                neighbor: [4; 16],
                link: crate::retry::LinkEvent::Unchanged,
                signal: crate::retry::Signal::Continue,
                admission: crate::retry::Admission::Allow,
            }],
        )
        .unwrap();
    assert!(out[0].send);
}

#[test]
fn credential_replacement_never_reactivates_old_message_or_refills_retry() {
    for participant in [1, 2, 3, 4] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        s.schedule_forward("one", &credential_key(&test_credential(4)))
            .unwrap();
        assert!(
            s.advance_queue(
                "one",
                "data",
                &credential_key(&test_credential(4)),
                event(0)
            )
            .unwrap()
            .send
        );
        let before: String = s
            .conn
            .query_row("SELECT retry FROM queues", [], |r| r.get(0))
            .unwrap();
        let new = replace(&mut s, participant);
        assert!(s.message("one").unwrap().unwrap().policy_stopped);
        assert!(s.schedule_forward("one", &credential_key(&new)).is_err());
        let after: String = s
            .conn
            .query_row("SELECT retry FROM queues", [], |r| r.get(0))
            .unwrap();
        assert_eq!(before, after);
        drop(s);
        let mut s = w.reopen(1);
        let mut duplicate = relay("one");
        duplicate.expected_policy_revision = revision(&s);
        assert_eq!(s.receive(duplicate).unwrap_err().code, Code::Conflict);
    }
}

#[test]
fn previously_consumed_decision_cannot_pass_later_output_policy_check() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(super::tests::send("one", "a", 0)).unwrap();
    let prepared_revision = revision(&s);
    assert!(
        s.advance_queue("one", "data", super::tests::PEER_2, event(0))
            .unwrap()
            .send
    );
    s.validate_business_output("one", "data", super::tests::PEER_2, prepared_revision)
        .unwrap();
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    assert!(
        s.validate_business_output("one", "data", super::tests::PEER_2, prepared_revision)
            .is_err()
    );
    assert!(s.observe_custody("one", super::tests::PEER_2).is_err());
    assert!(!s.message("one").unwrap().unwrap().custody_observed);
}

#[test]
fn policy_storage_failure_quarantines_owner_and_commit_result_is_recovered() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        s.fault = Some(fault);
        assert!(
            s.block_control_binding(ACTIVITY, test_credential(3))
                .is_err()
        );
        assert!(s.is_quarantined());
        assert!(s.schedule_forward("one", super::tests::PEER_3).is_err());
        drop(s);
        let s = w.reopen(1);
        assert_eq!(
            s.control_binding_state(test_credential(3)).unwrap(),
            Some(if fault == TestFault::AfterCommit {
                BindingState::Blocked
            } else {
                BindingState::Active
            })
        );
        assert_eq!(
            s.message("one").unwrap().unwrap().policy_stopped,
            fault == TestFault::AfterCommit
        );
    }
}

#[test]
fn activity_stop_deadline_and_policy_counter_overflow_cannot_restore_outputs() {
    for action in ["stop", "deadline", "overflow"] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        s.schedule_forward("one", super::tests::PEER_3).unwrap();
        match action {
            "stop" => s.stop_control_activity(ACTIVITY).unwrap(),
            "deadline" => {
                s.shorten_control_activity(ACTIVITY, 500).unwrap();
                s.advance_clock(clock(500)).unwrap();
            }
            _ => {
                s.conn
                    .execute(
                        "UPDATE control_activity SET policy_revision=9223372036854775807",
                        [],
                    )
                    .unwrap();
                assert_eq!(
                    s.block_control_binding(ACTIVITY, test_credential(3))
                        .unwrap_err()
                        .code,
                    Code::Quota
                );
                assert!(s.is_quarantined());
            }
        }
        assert!(
            s.advance_queue(
                "one",
                "data",
                super::tests::PEER_3,
                event(if action == "deadline" { 500 } else { 0 })
            )
            .is_err()
        );
    }
}

#[test]
fn v5_messages_are_not_promoted_to_verified_policy_by_migration_or_duplicate() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("one")).unwrap();
    s.schedule_forward("one", super::tests::PEER_3).unwrap();
    super::tests::strip_v6(&s);
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    let mut s = Store::migrate_v5(&w.dir, Limits::default(), clock(1)).unwrap();
    assert!(s.message_core("one").unwrap().is_some());
    assert!(s.message("one").unwrap().unwrap().policy_stopped);
    assert_eq!(
        s.advance_queue("one", "data", super::tests::PEER_3, event(1))
            .unwrap_err()
            .code,
        Code::UnsupportedVersion
    );
    let mut duplicate = relay("one");
    duplicate.expected_policy_revision = 0;
    assert_eq!(
        s.receive(duplicate).unwrap_err().code,
        Code::UnsupportedVersion
    );
    let mut new = relay("new");
    new.expected_policy_revision = 0;
    assert_eq!(s.receive(new).unwrap_err().code, Code::Conflict);
    assert!(s.message("new").unwrap().is_none());
}

#[test]
fn policy_association_corruption_is_rejected_on_reopen() {
    for sql in [
        "UPDATE messages SET policy_revision=100",
        "UPDATE messages SET local_credential=zeroblob(32)",
        "UPDATE messages SET source_neighbor='unknown'",
        "UPDATE messages SET policy_revision=NULL",
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
            Code::StoreCorrupt
        );
    }
}

#[test]
fn stopped_receipt_cleanup_is_bounded_without_erasing_delivery_history() {
    let w = Workspace::new();
    let mut s = w.create();
    for i in 0..257 {
        s.receive(super::tests::destination(&format!("m{i}"), i))
            .unwrap();
    }
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    s.fault = Some(TestFault::BeforeCommit);
    assert!(s.maintain(s.current_clock()).is_err());
    assert_eq!(s.usage().unwrap().reserved_control_count, 257);
    s.fault = None;
    let report = s.maintain(s.current_clock()).unwrap();
    assert_eq!(report.stopped_receipt_intents, 256);
    assert!(report.more_due);
    let key: String = s
        .conn
        .query_row("SELECT message_key FROM receipt_intents", [], |r| r.get(0))
        .unwrap();
    assert!(s.receipt_intent(&key).is_err());
    let report = s.maintain(s.current_clock()).unwrap();
    assert_eq!(report.stopped_receipt_intents, 1);
    assert!(!report.more_due);
    assert_eq!(s.usage().unwrap().history_count, 257);
    assert_eq!(s.message("m0").unwrap().unwrap().state, "committed");
}

#[test]
fn business_policy_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_POLICY_TEST_STORE") else {
        return;
    };
    let fault = match std::env::var("RADISHLINK_POLICY_TEST_SIDE")
        .unwrap()
        .as_str()
    {
        "before" => TestFault::CrashBeforeCommit,
        "after" => TestFault::CrashAfterCommit,
        _ => panic!("side"),
    };
    let operation = std::env::var("RADISHLINK_POLICY_TEST_OPERATION").unwrap();
    if operation == "migration" {
        Store::open_version(
            Path::new(&dir),
            Limits::default(),
            clock(1),
            OpenMode::MigrateV5Fault(fault),
        )
        .unwrap();
    } else {
        let mut s = Store::open(Path::new(&dir), Limits::default(), clock(1)).unwrap();
        s.fault = Some(fault);
        match operation.as_str() {
            "block" => s
                .block_control_binding(ACTIVITY, test_credential(3))
                .unwrap(),
            "retire" => s.begin_control_exit(object(1, 1, 7).fields).unwrap(),
            "exit" => {
                s.accept_control(
                    object(3, 3, 8),
                    &[ControlNeighbor {
                        participant: [4; 16],
                        link: Link::Up,
                    }],
                )
                .unwrap();
            }
            "replace" => {
                let mut next = test_credential(3);
                next[31] = 2;
                s.activate_control_binding(ACTIVITY, next, &[3, 2]).unwrap();
            }
            _ => panic!("operation"),
        }
    }
    panic!("expected controlled process exit");
}

#[test]
fn process_exit_recovers_policy_marker_binding_object_and_revision_together() {
    for operation in ["migration", "block", "retire", "exit", "replace"] {
        for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
            let w = Workspace::new();
            let mut s = w.create();
            s.receive(relay("one")).unwrap();
            if operation == "migration" {
                super::tests::strip_v6(&s);
            }
            if operation == "replace" {
                let mut next = test_credential(3);
                next[31] = 2;
                s.stage_control_binding(
                    ACTIVITY,
                    ControlBinding {
                        participant: [3; 16],
                        credential: next,
                        generation: 2,
                        body: vec![3, 2],
                    },
                )
                .unwrap();
            }
            drop(s);
            let status = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::business_policy_tests::business_policy_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_POLICY_TEST_STORE", &w.dir)
                .env("RADISHLINK_POLICY_TEST_SIDE", side)
                .env("RADISHLINK_POLICY_TEST_OPERATION", operation)
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(exit));
            if operation == "migration" {
                let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
                assert_eq!(
                    conn.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                        .unwrap(),
                    if committed { 8 } else { 5 }
                );
                drop(conn);
            }
            let s = if operation == "migration" && !committed {
                Store::migrate_v5(&w.dir, Limits::default(), clock(2)).unwrap()
            } else {
                w.reopen(2)
            };
            assert_eq!(
                s.message("one").unwrap().unwrap().policy_stopped,
                committed || operation == "migration"
            );
            let stored_revision: i64 = s
                .conn
                .query_row("SELECT policy_revision FROM control_activity", [], |r| {
                    r.get(0)
                })
                .unwrap();
            assert_eq!(
                stored_revision,
                if operation == "migration" {
                    0
                } else if committed {
                    6
                } else {
                    5
                }
            );
            if operation == "exit" {
                assert_eq!(s.control_usage().unwrap().objects, u64::from(committed));
            }
            if operation == "retire" {
                assert_eq!(
                    s.control_exit_intent(ACTIVITY).unwrap().is_some(),
                    committed
                );
            }
        }
    }
}
