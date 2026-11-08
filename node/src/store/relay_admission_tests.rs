use super::outbound_cycle_tests::input;
use super::outbound_tests::batch;
use super::tests::{
    ACTIVITY, PEER_2, PEER_3, Workspace, clock, prepare_business, relay, test_credential,
};
use super::*;
use OutboundAckAdmission as Ack;

fn register(store: &mut Store, peer: u8) -> ControlIngressChannel {
    store
        .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(peer))
        .unwrap()
}

fn forward(store: &Store, key: &str) -> Option<(String, u8, RetryState)> {
    let row: Option<(String, u8, String)> = store
        .conn
        .query_row(
            "SELECT neighbor,hops,retry FROM queues WHERE message_key=?1 AND kind='data'",
            [key],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .unwrap();
    row.map(|(neighbor, hops, retry)| (neighbor, hops, serde_json::from_str(&retry).unwrap()))
}

#[test]
fn relay_commit_binds_ack_to_source_and_restores_forward_without_replaying_ack() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    let (view, ack) = s
        .receive_relay_on_channel(&source, relay("one"), test_credential(3))
        .unwrap();
    assert_eq!(ack, Ack::Queued);
    assert_eq!(view.source_neighbor.as_deref(), Some(PEER_2));
    assert!(view.payload_present);
    assert!(s.history(0, 10).unwrap().is_empty());
    assert_eq!(s.usage().unwrap().reserved_control_bytes, 4096);
    let (neighbor, hops, retry) = forward(&s, "one").unwrap();
    assert_eq!(
        (neighbor.as_str(), hops, retry.deadline_ms()),
        (PEER_3, 0, 10000)
    );

    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = s
        .process_outbound_cycle_with_handoff(
            &mut cycle,
            input(&s, 1000, vec![]),
            |_| Ok(batch(1000)),
            |_| None,
        )
        .unwrap();
    assert_eq!(report.ack_inputs, 1);
    assert!(report.outbound.decisions.iter().any(|decision| matches!(
        decision, OutboundDecision::DataAck { message, neighbor, send: true }
            if message == "one" && neighbor == PEER_2
    )));
    let request = s.next_outbound_handoff().unwrap();
    assert_eq!(request.channel, source.binding());
    let written = s.advance_outbound_handoff(
        &request,
        OutboundHandoffInput {
            clock: clock(1000),
            channel: Some(source.binding()),
            frame: OutboundFrame::Control { bytes: 127 },
        },
        |offset, remaining| {
            assert_eq!((offset, remaining), (0, 127));
            OutboundWrite::Written(remaining)
        },
    );
    assert_eq!(written.result.unwrap(), OutboundWriteProgress::Complete);
    let saved = forward(&s, "one").unwrap();
    assert_ne!(saved.2, retry);
    drop(s);

    let mut s = w.reopen(1001);
    assert_eq!(forward(&s, "one").unwrap(), saved);
    let replacement = register(&mut s, 2);
    let mut duplicate = relay("one");
    duplicate.message.deadline_ms = 5000;
    assert_eq!(
        s.receive_relay_on_channel(&replacement, duplicate, test_credential(3))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    let mut shortened = saved.2.clone();
    shortened.constrain_deadline(5000).unwrap();
    assert_eq!(forward(&s, "one").unwrap().2, shortened);
    assert_eq!(
        s.receive_relay_on_channel(&replacement, relay("one"), test_credential(3))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert_eq!(forward(&s, "one").unwrap().2, shortened);
    assert_eq!(s.message_remaining_ms("one").unwrap(), 3999);
    assert!(s.outbound_acks.is_empty());
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn relay_requires_current_ingress_final_destination_and_nonzero_hop() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    let alternate = register(&mut s, 4);
    for (channel, hop) in [(&alternate, 3), (&source, 2), (&source, 4)] {
        assert_eq!(
            s.receive_relay_on_channel(channel, relay("one"), test_credential(hop))
                .unwrap_err()
                .code,
            Code::Conflict
        );
    }
    let mut back_to_sender = relay("one");
    back_to_sender.neighbor = PEER_3.into();
    let destination = register(&mut s, 3);
    assert_eq!(
        s.receive_relay_on_channel(&destination, back_to_sender, test_credential(3))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let mut zero = relay("one");
    zero.remaining_hops = 0;
    assert_eq!(
        s.receive_relay_on_channel(&source, zero, test_credential(3))
            .unwrap_err()
            .code,
        Code::InvalidInput
    );
    s.close_control_ingress_channel(&source).unwrap();
    let current = register(&mut s, 2);
    assert_eq!(
        s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert!(s.message("one").unwrap().is_none());
    assert!(s.outbound_acks.is_empty());
    s.receive_relay_on_channel(&current, relay("one"), test_credential(3))
        .unwrap();

    let mut changed_source = relay("one");
    changed_source.neighbor = credential_key(&test_credential(4));
    changed_source.message.deadline_ms = 9000;
    assert_eq!(
        s.receive_relay_on_channel(&alternate, changed_source, test_credential(3))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(s.message_remaining_ms("one").unwrap(), 10000);
    assert_eq!(s.outbound_acks.len(), 1);
}

#[test]
fn relay_ack_requires_durable_forward_and_original_source_even_for_explicit_input() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.receive(relay("legacy")).unwrap();
    assert_eq!(
        s.receive_relay_on_channel(&source, relay("legacy"), test_credential(3))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert!(forward(&s, "legacy").is_none());
    s.receive(relay("scheduled")).unwrap();
    s.schedule_forward("scheduled", PEER_3).unwrap();
    for (now, message, neighbor) in [(1000, "legacy", PEER_2), (2000, "scheduled", PEER_3)] {
        let report = s
            .process_outbound_batch(
                clock(now),
                vec![OutboundEvent::DataAck {
                    message: message.into(),
                    neighbor: neighbor.into(),
                }],
            )
            .unwrap();
        assert!(matches!(
            report.decisions.as_slice(),
            [OutboundDecision::DataAck { send: false, .. }]
        ));
    }
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn relay_record_limit_rolls_back_all_rows_but_ack_queue_full_keeps_commit() {
    let w = Workspace::new();
    let limits = Limits {
        record_count: CONTROL_RESERVED_RECORDS + 2,
        ..Limits::default()
    };
    let mut s = Store::create(&w.dir, limits.clone(), clock(0)).unwrap();
    prepare_business(&mut s);
    let source = register(&mut s, 2);
    let revision = s.revision().unwrap();
    assert_eq!(
        s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
            .unwrap_err()
            .code,
        Code::Quota
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert!(s.message("one").unwrap().is_none());
    assert!(forward(&s, "one").is_none());
    assert_eq!(s.usage().unwrap().reserved_control_count, 0);
    assert!(s.outbound_acks.is_empty());
    drop(s);
    let mut s = Store::open(&w.dir, limits, clock(1)).unwrap();
    // The original two records fit when no forwarding row is included.
    let baseline = s.usage().unwrap().records;
    s.receive(relay("one")).unwrap();
    assert_eq!(s.usage().unwrap().records, baseline + 2);

    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    for index in 0..=MAX_CYCLE_ACKS {
        let key = format!("relay{index:02}");
        let (view, ack) = s
            .receive_relay_on_channel(&source, relay(&key), test_credential(3))
            .unwrap();
        assert_eq!(
            ack,
            if index == MAX_CYCLE_ACKS {
                Ack::Full
            } else {
                Ack::Queued
            }
        );
        assert!(view.payload_present);
        assert!(forward(&s, &key).is_some());
    }
    assert_eq!(
        s.usage().unwrap().reserved_control_count,
        MAX_CYCLE_ACKS as u64 + 1
    );
    assert_eq!(s.outbound_acks.len(), MAX_CYCLE_ACKS);
}

#[test]
fn relay_ack_is_withdrawn_at_expiry_revocation_or_channel_close() {
    for (mode, now) in [("expired", 10000), ("revoked", 1000), ("closed", 1000)] {
        let w = Workspace::new();
        let mut s = w.create();
        let source = register(&mut s, 2);
        s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
            .unwrap();
        match mode {
            "revoked" => {
                s.block_control_binding(ACTIVITY, test_credential(3))
                    .unwrap();
                let mut new = relay("two");
                new.expected_policy_revision = s.business_policy_revision(ACTIVITY).unwrap();
                assert_eq!(
                    s.receive_relay_on_channel(&source, new, test_credential(3))
                        .unwrap_err()
                        .code,
                    Code::Conflict
                );
                assert!(s.message("two").unwrap().is_none());
            }
            "closed" => s.close_control_ingress_channel(&source).unwrap(),
            _ => {}
        }
        let mut cycle = s.start_outbound_cycle().unwrap();
        let report = s
            .process_outbound_cycle_with_handoff(
                &mut cycle,
                input(&s, now, vec![]),
                |_| Ok(batch(now)),
                |_| None,
            )
            .unwrap();
        assert_eq!(report.ack_inputs, 0, "{mode}");
        if mode != "closed" {
            assert_eq!(report.discarded_queued_acks.len(), 1, "{mode}");
        }
        assert!(s.outbound_acks.is_empty());
        assert!(s.next_outbound_handoff().is_none());
        if mode == "expired" {
            let mut late = relay("one");
            late.message.deadline_ms = 10001;
            assert!(
                s.receive_relay_on_channel(&source, late, test_credential(3))
                    .is_err()
            );
        }
    }
}

#[test]
fn relay_transaction_failure_never_publishes_ack() {
    for (fault, error) in [
        (TestFault::BeforeCommit, Code::StoreUnavailable),
        (TestFault::AfterCommit, Code::OutcomeUnknown),
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        let source = register(&mut s, 2);
        s.fault = Some(fault);
        assert_eq!(
            s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
                .unwrap_err()
                .code,
            error
        );
        assert!(s.outbound_acks.is_empty());
        assert_eq!(s.is_quarantined(), fault == TestFault::AfterCommit);
        drop(s);
        let s = w.reopen(1);
        let committed = fault == TestFault::AfterCommit;
        assert_eq!(s.message("one").unwrap().is_some(), committed);
        assert_eq!(forward(&s, "one").is_some(), committed);
        assert_eq!(
            s.usage().unwrap().reserved_control_count,
            u64::from(committed)
        );
        assert!(s.outbound_acks.is_empty());
    }
}

#[test]
fn relay_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_RELAY_TEST_STORE") else {
        return;
    };
    let mut s = Store::open(Path::new(&dir), Limits::default(), clock(0)).unwrap();
    let source = register(&mut s, 2);
    s.fault = Some(
        match std::env::var("RADISHLINK_RELAY_TEST_SIDE")
            .unwrap()
            .as_str()
        {
            "before" => TestFault::CrashBeforeCommit,
            "after" => TestFault::CrashAfterCommit,
            _ => panic!("invalid synthetic side"),
        },
    );
    s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
        .unwrap();
    panic!("expected controlled process exit");
}

#[test]
fn relay_process_exit_reopens_with_either_all_or_none_of_the_responsibility() {
    for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
        let w = Workspace::new();
        drop(w.create());
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "store::relay_admission_tests::relay_crash_child",
                "--nocapture",
            ])
            .env("RADISHLINK_RELAY_TEST_STORE", &w.dir)
            .env("RADISHLINK_RELAY_TEST_SIDE", side)
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(exit));
        let mut s = w.reopen(1);
        let view = s.message("one").unwrap();
        assert_eq!(
            view.as_ref()
                .is_some_and(|m| m.payload_present && m.source_neighbor.as_deref() == Some(PEER_2)),
            committed
        );
        assert_eq!(
            forward(&s, "one").as_ref().map(|(neighbor, hops, retry)| (
                neighbor.as_str(),
                *hops,
                retry.deadline_ms()
            )),
            committed.then_some((PEER_3, 0, 10000))
        );
        assert_eq!(
            s.usage().unwrap().reserved_control_count,
            u64::from(committed)
        );
        assert!(s.outbound_acks.is_empty());
        let source = register(&mut s, 2);
        assert_eq!(
            s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
                .unwrap()
                .1,
            if committed {
                Ack::NotEligible
            } else {
                Ack::Queued
            }
        );
        if committed {
            let mut cycle = s.start_outbound_cycle().unwrap();
            let report = s
                .process_outbound_cycle(&mut cycle, input(&s, 1000, vec![]), |_| Ok(batch(1000)))
                .unwrap();
            assert_eq!(report.ack_inputs, 0);
            assert!(matches!(
                report.outbound.decisions.as_slice(),
                [OutboundDecision::Queue(key, decision)]
                    if key.message == "one" && key.neighbor == PEER_3 && decision.send
            ));
        }
    }
}
