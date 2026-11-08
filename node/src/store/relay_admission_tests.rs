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

fn relay_round(store: &mut Store, cycle: &mut OutboundCycle, now: i64) -> OutboundCycleReport {
    store
        .process_outbound_cycle_with_handoff(
            cycle,
            input(store, now, vec![]),
            |_| Ok(batch(now)),
            |_| None,
        )
        .unwrap()
}

fn ack_attempts(store: &Store, key: &str) -> u8 {
    store
        .conn
        .query_row(
            "SELECT coalesce(json_extract(data_ack_budget,'$[0].attempts'),0) FROM messages WHERE key=?1",
            [key],
            |row| row.get(0),
        )
        .unwrap()
}

#[test]
fn relay_same_boot_reopen_recovers_lost_ack_only_after_fresh_retransmission() {
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
    let report = relay_round(&mut s, &mut cycle, 1000);
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
    // The first ACK was handed off locally but the upstream never received it.
    let saved = forward(&s, "one").unwrap();
    assert_ne!(saved.2, retry);
    drop(s);

    let mut s = w.reopen(1001);
    assert_eq!(forward(&s, "one").unwrap(), saved);
    assert_eq!(ack_attempts(&s, "one"), 1);
    assert!(s.outbound_acks.is_empty());
    assert!(s.next_outbound_handoff().is_none());
    let replacement = register(&mut s, 2);
    let mut duplicate = relay("one");
    duplicate.message.deadline_ms = 5000;
    assert_eq!(
        s.receive_relay_on_channel(&replacement, duplicate, test_credential(3))
            .unwrap()
            .1,
        Ack::Queued
    );
    let mut shortened = saved.2.clone();
    shortened.constrain_deadline(5000).unwrap();
    assert_eq!(forward(&s, "one").unwrap().2, shortened);
    assert_eq!(
        s.receive_relay_on_channel(&replacement, relay("one"), test_credential(3))
            .unwrap()
            .1,
        Ack::Queued
    );
    assert_eq!(forward(&s, "one").unwrap().2, shortened);
    assert_eq!(s.message_remaining_ms("one").unwrap(), 3999);
    assert_eq!(s.outbound_acks.len(), 1);
    assert_eq!(ack_attempts(&s, "one"), 1);
    assert!(s.next_outbound_handoff().is_none());
    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = relay_round(&mut s, &mut cycle, 2001);
    assert_eq!(report.ack_inputs, 1);
    assert_eq!(
        s.next_outbound_handoff().unwrap().channel,
        replacement.binding()
    );
    assert_eq!(ack_attempts(&s, "one"), 2);
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
fn relay_same_credential_reconnect_requires_fresh_matching_frame() {
    let w = Workspace::new();
    let mut s = w.create();
    let old = register(&mut s, 2);
    s.receive_relay_on_channel(&old, relay("one"), test_credential(3))
        .unwrap();
    s.close_control_ingress_channel(&old).unwrap();
    let replacement = register(&mut s, 2);
    assert_ne!(old.binding(), replacement.binding());
    assert!(s.outbound_acks.is_empty());
    assert_eq!(
        s.receive_relay_on_channel(&old, relay("one"), test_credential(3))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let mut changed = relay("one");
    changed.message.payload.push(0);
    assert_eq!(
        s.receive_relay_on_channel(&replacement, changed, test_credential(3))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert!(s.outbound_acks.is_empty());
    assert_eq!(
        s.receive_relay_on_channel(&replacement, relay("one"), test_credential(3))
            .unwrap()
            .1,
        Ack::Queued
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    assert_eq!(relay_round(&mut s, &mut cycle, 1000).ack_inputs, 1);
    assert_eq!(
        s.next_outbound_handoff().unwrap().channel,
        replacement.binding()
    );
}

#[test]
fn relay_recovery_stops_at_persisted_ack_limit_even_after_reopen() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    let mut cycle = s.start_outbound_cycle().unwrap();
    for attempt in 1..=10 {
        assert_eq!(
            s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
                .unwrap()
                .1,
            Ack::Queued
        );
        let now = 1000 + i64::from(attempt - 1) * 250;
        assert_eq!(relay_round(&mut s, &mut cycle, now).ack_inputs, 1);
        assert!(s.next_outbound_handoff().is_some());
        assert_eq!(ack_attempts(&s, "one"), attempt);
        s.cancel_outbound_handoff();
    }
    let saved = forward(&s, "one").unwrap();
    assert_eq!(
        s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert!(s.outbound_acks.is_empty());
    drop(s);

    let mut s = w.reopen(3251);
    let replacement = register(&mut s, 2);
    assert_eq!(
        s.receive_relay_on_channel(&replacement, relay("one"), test_credential(3))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert_eq!(ack_attempts(&s, "one"), 10);
    assert_eq!(forward(&s, "one").unwrap(), saved);
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
    let overflow = format!("relay{MAX_CYCLE_ACKS:02}");
    for (key, expected) in [(overflow.as_str(), Ack::Full), ("relay00", Ack::Queued)] {
        assert_eq!(
            s.receive_relay_on_channel(&source, relay(key), test_credential(3))
                .unwrap()
                .1,
            expected
        );
    }
    assert_eq!(s.outbound_acks.len(), MAX_CYCLE_ACKS);
    let mut cycle = s.start_outbound_cycle().unwrap();
    assert_eq!(
        relay_round(&mut s, &mut cycle, 1000).ack_inputs,
        MAX_CYCLE_ACKS
    );
    assert_eq!(ack_attempts(&s, &overflow), 0);
    assert_eq!(
        s.receive_relay_on_channel(&source, relay(&overflow), test_credential(3))
            .unwrap()
            .1,
        Ack::Queued
    );
}

#[test]
fn recovered_relay_ack_is_withdrawn_at_expiry_revocation_or_channel_close() {
    for (mode, now) in [
        ("expired", 10000),
        ("source revoked", 1000),
        ("destination revoked", 1000),
        ("closed", 1000),
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        let old = register(&mut s, 2);
        s.receive_relay_on_channel(&old, relay("one"), test_credential(3))
            .unwrap();
        s.close_control_ingress_channel(&old).unwrap();
        let source = register(&mut s, 2);
        assert_eq!(
            s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
                .unwrap()
                .1,
            Ack::Queued
        );
        match mode {
            "source revoked" | "destination revoked" => {
                let peer = if mode == "source revoked" { 2 } else { 3 };
                s.block_control_binding(ACTIVITY, test_credential(peer))
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
                let mut duplicate = relay("one");
                duplicate.expected_policy_revision = s.business_policy_revision(ACTIVITY).unwrap();
                assert_eq!(
                    s.receive_relay_on_channel(&source, duplicate, test_credential(3))
                        .unwrap_err()
                        .code,
                    Code::Conflict
                );
            }
            "closed" => s.close_control_ingress_channel(&source).unwrap(),
            _ => {}
        }
        let mut cycle = s.start_outbound_cycle().unwrap();
        let report = relay_round(&mut s, &mut cycle, now);
        assert_eq!(report.ack_inputs, 0, "{mode}");
        if mode != "closed" {
            assert_eq!(report.discarded_queued_acks.len(), 1, "{mode}");
        }
        assert!(s.outbound_acks.is_empty());
        assert!(s.next_outbound_handoff().is_none());
        assert_eq!(ack_attempts(&s, "one"), 0);
        if mode == "expired" {
            assert_eq!(
                s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
                    .unwrap_err()
                    .code,
                Code::Expired
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
fn relay_retransmission_that_changes_deadline_requires_known_commit_before_reply() {
    for (fault, error, deadline) in [
        (TestFault::BeforeCommit, Code::StoreUnavailable, 10000),
        (TestFault::AfterCommit, Code::OutcomeUnknown, 5000),
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        let old = register(&mut s, 2);
        s.receive_relay_on_channel(&old, relay("one"), test_credential(3))
            .unwrap();
        s.close_control_ingress_channel(&old).unwrap();
        let source = register(&mut s, 2);
        let mut duplicate = relay("one");
        duplicate.message.deadline_ms = 5000;
        s.fault = Some(fault);
        assert_eq!(
            s.receive_relay_on_channel(&source, duplicate, test_credential(3))
                .unwrap_err()
                .code,
            error
        );
        assert!(s.outbound_acks.is_empty());
        drop(s);

        let mut s = w.reopen(1);
        assert_eq!(s.message_remaining_ms("one").unwrap(), deadline - 1);
        assert!(s.outbound_acks.is_empty());
        let source = register(&mut s, 2);
        assert_eq!(
            s.receive_relay_on_channel(&source, relay("one"), test_credential(3))
                .unwrap()
                .1,
            Ack::Queued
        );
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
            Ack::Queued
        );
        if committed {
            let mut cycle = s.start_outbound_cycle().unwrap();
            let report = relay_round(&mut s, &mut cycle, 1000);
            assert_eq!(report.ack_inputs, 1);
            assert!(report.outbound.decisions.iter().any(|decision| matches!(
                decision, OutboundDecision::Queue(key, decision)
                    if key.message == "one" && key.neighbor == PEER_3 && decision.send
            )));
            assert_eq!(s.next_outbound_handoff().unwrap().channel, source.binding());
        }
    }
}
