use super::tests::{ACTIVITY, PEER_2, Workspace, clock, destination, relay, send, test_credential};
use super::*;
use crate::retry::{Admission, LinkEvent, Reason, Signal};

fn batch(now: i64) -> Batch {
    Batch {
        now_ms: now,
        link: LinkEvent::Unchanged,
        signal: Signal::Continue,
        admission: Admission::Allow,
    }
}
fn receipt(key: &str, now: i64) -> OutboundEvent {
    OutboundEvent::Queue(QueueEvent {
        queue: QueueKey {
            message: key.into(),
            kind: QueueKind::Evidence,
            neighbor: PEER_2.into(),
        },
        batch: batch(now),
    })
}
fn ack(key: &str) -> OutboundEvent {
    OutboundEvent::DataAck {
        message: key.into(),
        neighbor: PEER_2.into(),
    }
}
fn security_revision(s: &Store) -> i64 {
    s.conn
        .query_row(
            "SELECT revision FROM security_states WHERE session='session'",
            [],
            |r| r.get(0),
        )
        .optional()
        .unwrap()
        .unwrap_or(0)
}
fn prepare_receipt(s: &mut Store, key: &str, bytes: usize) {
    let mut incoming = destination(key, security_revision(s));
    incoming.expected_policy_revision = s.business_policy_revision(ACTIVITY).unwrap();
    s.receive(incoming).unwrap();
    let i = s.receipt_intent(key).unwrap().unwrap();
    s.finalize_receipt(key, &i.body, &vec![8; bytes], i.policy_revision)
        .unwrap();
}
fn object(issuer: u8, target: u8, id: u8) -> PreparedControl {
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
            operation: [id; 16],
            reason: 0,
            reference: [id; 32],
            payload: vec![id],
        },
        cose: vec![id],
    }
}
fn control(id: u8) -> OutboundEvent {
    OutboundEvent::Control(ControlEvent {
        object: [id; 32],
        neighbor: [2; 16],
        link: LinkEvent::Unchanged,
        signal: Signal::Continue,
        admission: Admission::Allow,
    })
}
fn add_control(s: &mut Store, issuer: u8, target: u8, id: u8) {
    s.accept_control(
        object(issuer, target, id),
        &[ControlNeighbor {
            participant: [2; 16],
            link: Link::Up,
        }],
    )
    .unwrap();
}
fn sent(report: &OutboundReport) -> usize {
    report
        .decisions
        .iter()
        .filter(|d| match d {
            OutboundDecision::Queue(_, d) => d.send,
            OutboundDecision::Control(d) => d.send,
            OutboundDecision::DataAck { send, .. } | OutboundDecision::ControlAck { send, .. } => {
                *send
            }
        })
        .count()
}
fn ack_sends(report: &OutboundReport) -> Vec<String> {
    report
        .decisions
        .iter()
        .filter_map(|d| match d {
            OutboundDecision::DataAck {
                message,
                send: true,
                ..
            } => Some(message.clone()),
            _ => None,
        })
        .collect()
}
fn budget(s: &Store, key: &str) -> String {
    s.conn
        .query_row(
            "SELECT data_ack_budget FROM messages WHERE key=?1",
            [key],
            |r| r.get(0),
        )
        .unwrap()
}
fn rate(s: &Store) -> (i64, i64, Option<String>) {
    s.conn
        .query_row(
            "SELECT frames,bytes,ordinary_cursor FROM control_output_rate WHERE id=1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap()
}

#[test]
fn all_control_kinds_share_frames_with_exit_first_and_data_independent() {
    let w = Workspace::new();
    let mut s = w.create();
    prepare_receipt(&mut s, "proof", 512);
    s.receive(destination("ack", security_revision(&s)))
        .unwrap();
    s.create_action_scope("ui").unwrap();
    s.submit(send("origin", "action", security_revision(&s)))
        .unwrap();
    s.advance_clock(clock(1000)).unwrap();
    add_control(&mut s, 4, 3, 7);
    add_control(&mut s, 5, 5, 8);
    let report = s
        .process_outbound_batch(
            clock(1000),
            vec![
                ack("ack"),
                receipt("proof", 1000),
                control(7),
                control(8),
                OutboundEvent::ControlAck {
                    object: [7; 32],
                    neighbor: [2; 16],
                },
                OutboundEvent::Queue(QueueEvent {
                    queue: QueueKey {
                        message: "origin".into(),
                        kind: QueueKind::Data,
                        neighbor: PEER_2.into(),
                    },
                    batch: batch(1000),
                }),
            ],
        )
        .unwrap();
    assert!(
        matches!(&report.decisions[0],OutboundDecision::Control(d) if d.object==[8;32] && d.send)
    );
    assert_eq!(sent(&report), 5); // Four controls and an independent data attempt.
    assert!(
        report
            .decisions
            .iter()
            .any(|d| matches!(d, OutboundDecision::ControlAck { send: false, .. }))
    );
    assert_eq!(rate(&s).0, 0);
    assert_eq!(rate(&s).1, 8192000 - (522 * 3 + 127) * 1000);
    assert!(!s.consume_control_ack(ACTIVITY, [7; 32], [2; 16]).unwrap());
}

#[test]
fn byte_limit_denial_consumes_receipt_retry_and_does_not_charge_idle_or_duplicates() {
    let w = Workspace::new();
    let mut s = w.create();
    prepare_receipt(&mut s, "a", 4096);
    prepare_receipt(&mut s, "b", 4096);
    let r = s
        .process_outbound_batch(clock(1000), vec![receipt("b", 1000), receipt("a", 1000)])
        .unwrap();
    assert_eq!(sent(&r), 1);
    assert!(r.decisions.iter().any(|d|matches!(d,OutboundDecision::Queue(k,d) if k.message=="b" && !d.send && d.reason==Reason::Quota && d.consumed==3)));
    assert_eq!(rate(&s).0, 3000);
    assert_eq!(rate(&s).1, (8192 - 4106) * 1000);
    let before = rate(&s);
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(1000), vec![receipt("a", 1000), receipt("b", 1000)])
                .unwrap()
        ),
        0
    );
    assert_eq!(rate(&s), before);
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(1001), vec![receipt("a", 1001), receipt("b", 1001)])
                .unwrap()
        ),
        0
    );
    assert_eq!(rate(&s), before); // No candidate send means no charge/refill write.
}

#[test]
fn persisted_round_robin_wraps_across_reopen_and_empty_bucket() {
    let w = Workspace::new();
    let mut s = w.create();
    for i in 0..5 {
        s.receive(destination(&format!("m{i}"), i)).unwrap();
    }
    let events = || (0..5).rev().map(|i| ack(&format!("m{i}"))).collect();
    assert_eq!(
        ack_sends(&s.process_outbound_batch(clock(1000), events()).unwrap()),
        ["m0", "m1", "m2", "m3"]
    );
    assert_eq!(
        ack_sends(&s.process_outbound_batch(clock(1250), events()).unwrap()),
        ["m4"]
    );
    assert_eq!(
        ack_sends(&s.process_outbound_batch(clock(1500), events()).unwrap()),
        ["m0"]
    );
    let cursor = rate(&s).2;
    drop(s);
    let mut s = w.reopen(1500);
    assert_eq!(rate(&s), (0, 0, cursor));
    assert_eq!(
        sent(&s.process_outbound_batch(clock(1500), events()).unwrap()),
        0
    );
    assert_eq!(
        ack_sends(&s.process_outbound_batch(clock(1750), events()).unwrap()),
        ["m1"]
    );
}

#[test]
fn data_ack_merges_duplicates_caps_ten_and_preserves_counts_across_reopen() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(1000), vec![ack("one"), ack("one")])
                .unwrap()
        ),
        1
    );
    for i in 1..10 {
        assert_eq!(
            sent(
                &s.process_outbound_batch(clock(1000 + i * 250), vec![ack("one")])
                    .unwrap()
            ),
            1
        );
    }
    let saved = budget(&s, "one");
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(3500), vec![ack("one")])
                .unwrap()
        ),
        0
    );
    drop(s);
    let mut s = w.reopen(3500);
    assert_eq!(saved, budget(&s, "one"));
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(4000), vec![ack("one")])
                .unwrap()
        ),
        0
    );
    assert_eq!(saved, budget(&s, "one"));
}

#[test]
fn data_ack_unknown_origin_deadline_revocation_and_lost_payload_never_create_authority() {
    let w = Workspace::new();
    let mut s = w.create();
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(1000), vec![ack("unknown")])
                .unwrap()
        ),
        0
    );
    s.create_action_scope("ui").unwrap();
    s.submit(send("origin", "action", security_revision(&s)))
        .unwrap();
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(1000), vec![ack("origin")])
                .unwrap()
        ),
        0
    );
    s.receive(relay("relay")).unwrap();
    let version = s.business_policy_revision(ACTIVITY).unwrap();
    s.finish_delivery(
        "relay",
        &super::tests::binding("relay"),
        Some((PEER_2, b"proof")),
        version,
    )
    .unwrap();
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(1000), vec![ack("relay")])
                .unwrap()
        ),
        0
    );
    s.receive(destination("dest", security_revision(&s)))
        .unwrap();
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    assert_eq!(
        s.process_outbound_batch(clock(1000), vec![ack("dest")])
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert_eq!(budget(&s, "dest"), "[]");
}

#[test]
fn mixed_round_failure_rolls_back_clock_counters_cursor_and_retry() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("one", 0)).unwrap();
        let before = budget(&s, "one");
        s.fault = Some(fault);
        let e = s
            .process_outbound_batch(clock(1000), vec![ack("one")])
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
        drop(s);
        let s = w.reopen(1000);
        assert_eq!(
            budget(&s, "one") == before,
            fault == TestFault::BeforeCommit
        );
        assert_eq!(rate(&s).2.is_some(), fault == TestFault::AfterCommit);
        assert_eq!(rate(&s).0, 0);
    }
}

#[test]
fn migration_requires_v6_and_does_not_invent_ack_allowance() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("old", 0)).unwrap();
    super::tests::strip_v7(&s);
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    assert_eq!(
        Store::migrate_v5(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    let mut s = Store::migrate_v6(&w.dir, Limits::default(), clock(1000)).unwrap();
    assert_eq!(
        s.process_outbound_batch(clock(1000), vec![ack("old")])
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert!(s.message("old").unwrap().unwrap().policy_stopped);
    assert!(
        s.conn
            .query_row(
                "SELECT data_ack_budget FROM messages WHERE key='old'",
                [],
                |r| r.get::<_, Option<String>>(0)
            )
            .unwrap()
            .is_none()
    );
}

#[test]
fn bounded_batches_conflicts_and_invalid_clock_leave_no_partial_charge() {
    let w = Workspace::new();
    let mut s = w.create();
    prepare_receipt(&mut s, "one", 512);
    let before = rate(&s);
    let rev = s.revision().unwrap();
    assert_eq!(
        s.process_outbound_batch(clock(1000), (0..129).map(|_| ack("one")).collect())
            .err()
            .unwrap()
            .code,
        Code::InvalidInput
    );
    let conflicting = OutboundEvent::Queue(QueueEvent {
        queue: QueueKey {
            message: "one".into(),
            kind: QueueKind::Evidence,
            neighbor: PEER_2.into(),
        },
        batch: Batch {
            link: LinkEvent::Down,
            ..batch(1000)
        },
    });
    let up = OutboundEvent::Queue(QueueEvent {
        queue: QueueKey {
            message: "one".into(),
            kind: QueueKind::Evidence,
            neighbor: PEER_2.into(),
        },
        batch: Batch {
            link: LinkEvent::Up,
            ..batch(1000)
        },
    });
    assert_eq!(
        s.process_outbound_batch(clock(1000), vec![up, conflicting, ack("one")])
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert_eq!(rate(&s), before);
    assert_eq!(s.revision().unwrap(), rev);
    assert_eq!(
        s.process_outbound_batch(clock(1000), vec![receipt("one", 999)])
            .err()
            .unwrap()
            .code,
        Code::InvalidInput
    );
    let mut other_boot = clock(1000);
    other_boot.boot = "different-boot".into();
    assert_eq!(
        s.process_outbound_batch(other_boot, vec![ack("one")])
            .err()
            .unwrap()
            .code,
        Code::TimeUncertain
    );
    assert!(s.is_time_uncertain());
    assert_eq!(rate(&s), before);
}

#[test]
fn data_ack_has_four_fixed_participant_slots_and_rejects_expiry_and_local_channel() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    let events = (2..=5)
        .map(|n| OutboundEvent::DataAck {
            message: "one".into(),
            neighbor: credential_key(&test_credential(n)),
        })
        .collect();
    assert_eq!(
        sent(&s.process_outbound_batch(clock(1000), events).unwrap()),
        4
    );
    let slots: serde_json::Value = serde_json::from_str(&budget(&s, "one")).unwrap();
    assert_eq!(slots.as_array().unwrap().len(), 4);
    assert_eq!(
        s.process_outbound_batch(
            clock(2000),
            vec![OutboundEvent::DataAck {
                message: "one".into(),
                neighbor: credential_key(&test_credential(1))
            }]
        )
        .err()
        .unwrap()
        .code,
        Code::Conflict
    );
    let saved = budget(&s, "one");
    assert_eq!(
        s.process_outbound_batch(clock(10000), vec![ack("one")])
            .err()
            .unwrap()
            .code,
        Code::Expired
    );
    assert_eq!(budget(&s, "one"), saved);
}

#[test]
fn migration_fault_and_corrupt_ack_or_cursor_are_rejected() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("one", 0)).unwrap();
        super::tests::strip_v7(&s);
        drop(s);
        assert_eq!(
            Store::open_version(
                &w.dir,
                Limits::default(),
                clock(1),
                OpenMode::MigrateV6Fault(fault)
            )
            .err()
            .unwrap()
            .code,
            if fault == TestFault::BeforeCommit {
                Code::StoreUnavailable
            } else {
                Code::OutcomeUnknown
            }
        );
        let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        assert_eq!(
            conn.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                .unwrap(),
            if fault == TestFault::BeforeCommit {
                6
            } else {
                8
            }
        );
    }
    for corrupt in [
        "UPDATE messages SET data_ack_budget='[{}]'",
        "UPDATE messages SET data_ack_budget='null'",
        "UPDATE control_output_rate SET ordinary_cursor='{}'",
        "UPDATE control_output_rate SET exit_cursor='{\"Queue\":{\"message\":\"one\",\"kind\":\"Data\",\"neighbor\":\"bad\"}}'",
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(destination("one", 0)).unwrap();
        s.conn.execute_batch(corrupt).unwrap();
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
fn fractional_refill_and_legacy_single_receipt_cannot_bypass_shared_bucket() {
    let w = Workspace::new();
    let mut s = w.create();
    prepare_receipt(&mut s, "one", 512);
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(249), vec![ack("one")])
                .unwrap()
        ),
        0
    );
    assert_eq!(
        sent(
            &s.process_outbound_batch(clock(250), vec![ack("one")])
                .unwrap()
        ),
        1
    );
    let d = s
        .advance_queue("one", "evidence", PEER_2, batch(250))
        .unwrap();
    assert!(!d.send && d.reason == Reason::Quota && d.consumed == 2);
    s.advance_clock(clock(750)).unwrap();
    assert!(
        s.advance_queue("one", "evidence", PEER_2, batch(750))
            .unwrap()
            .send
    );
    assert!(rate(&s).2.unwrap().contains("Evidence"));
}

#[test]
fn outbound_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_OUTBOUND_TEST_STORE") else {
        return;
    };
    let fault = match std::env::var("RADISHLINK_OUTBOUND_TEST_SIDE")
        .unwrap()
        .as_str()
    {
        "before" => TestFault::CrashBeforeCommit,
        "after" => TestFault::CrashAfterCommit,
        _ => panic!("invalid side"),
    };
    if std::env::var("RADISHLINK_OUTBOUND_TEST_OPERATION").unwrap() == "migration" {
        Store::open_version(
            Path::new(&dir),
            Limits::default(),
            clock(1),
            OpenMode::MigrateV6Fault(fault),
        )
        .unwrap();
    } else {
        let mut s = Store::open(Path::new(&dir), Limits::default(), clock(0)).unwrap();
        s.fault = Some(fault);
        s.process_outbound_batch(
            clock(1000),
            vec![
                receipt("one", 1000),
                ack("one"),
                control(7),
                OutboundEvent::ControlAck {
                    object: [7; 32],
                    neighbor: [2; 16],
                },
            ],
        )
        .unwrap();
    }
    panic!("expected controlled exit");
}

#[test]
fn process_exit_recovers_all_mixed_charges_or_none_and_explicit_migration() {
    for operation in ["mixed", "migration"] {
        for (side, code, committed) in [("before", 71, false), ("after", 72, true)] {
            let w = Workspace::new();
            let mut s = w.create();
            prepare_receipt(&mut s, "one", 512);
            add_control(&mut s, 4, 3, 7);
            if operation == "migration" {
                super::tests::strip_v7(&s);
            }
            drop(s);
            let result = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::outbound_tests::outbound_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_OUTBOUND_TEST_STORE", &w.dir)
                .env("RADISHLINK_OUTBOUND_TEST_SIDE", side)
                .env("RADISHLINK_OUTBOUND_TEST_OPERATION", operation)
                .status()
                .unwrap();
            assert_eq!(result.code(), Some(code));
            let conn = Connection::open(w.dir.join("node.sqlite3")).unwrap();
            if operation == "migration" {
                assert_eq!(
                    conn.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                        .unwrap(),
                    if committed { 8 } else { 6 }
                );
            } else {
                let (frames, bytes, last, cursor): (i64, i64, i64, Option<String>) = conn
                    .query_row(
                        "SELECT frames,bytes,last_ms,ordinary_cursor FROM control_output_rate",
                        [],
                        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
                    )
                    .unwrap();
                assert_eq!(last, if committed { 1000 } else { 0 });
                assert_eq!(frames, 0);
                assert_eq!(
                    bytes,
                    if committed {
                        8192000 - (522 * 2 + 127 * 2) * 1000
                    } else {
                        0
                    }
                );
                assert_eq!(cursor.is_some(), committed);
                drop(conn);
                let s = w.reopen(1000);
                assert_eq!(budget(&s, "one") == "[]", !committed);
                let p = s.control_progress([7; 32], [2; 16]).unwrap().unwrap();
                assert_eq!(
                    (p.attempts, p.ack_attempts),
                    if committed { (1, 1) } else { (0, 0) }
                );
                let retry: String = s
                    .conn
                    .query_row(
                        "SELECT retry FROM queues WHERE message_key='one'",
                        [],
                        |r| r.get(0),
                    )
                    .unwrap();
                let value: serde_json::Value = serde_json::from_str(&retry).unwrap();
                assert_eq!(value["next_slot"], if committed { 3 } else { 0 });
            }
        }
    }
}

#[test]
fn ack_neighbor_credential_replacement_never_refunds_participant_budget() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(destination("one", 0)).unwrap();
    let old = credential_key(&test_credential(3));
    for i in 0..10 {
        assert_eq!(
            sent(
                &s.process_outbound_batch(
                    clock(1000 + i * 250),
                    vec![OutboundEvent::DataAck {
                        message: "one".into(),
                        neighbor: old.clone()
                    }]
                )
                .unwrap()
            ),
            1
        );
    }
    let saved = budget(&s, "one");
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
    s.activate_control_binding(ACTIVITY, next, &[3, 2]).unwrap();
    assert!(!s.message("one").unwrap().unwrap().policy_stopped);
    assert_eq!(
        sent(
            &s.process_outbound_batch(
                clock(4000),
                vec![OutboundEvent::DataAck {
                    message: "one".into(),
                    neighbor: credential_key(&next)
                }]
            )
            .unwrap()
        ),
        0
    );
    assert_eq!(budget(&s, "one"), saved);
}
