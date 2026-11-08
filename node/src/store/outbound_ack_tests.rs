use super::outbound_cycle_tests::input;
use super::outbound_tests::{batch, object};
use super::tests::{ACTIVITY, Workspace, clock, destination, relay, test_credential};
use super::*;
use OutboundAckAdmission as Ack;

fn register(s: &mut Store, peer: u8) -> ControlIngressChannel {
    s.register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(peer))
        .unwrap()
}

fn round(s: &mut Store, cycle: &mut OutboundCycle, now: i64) -> Result<OutboundCycleReport> {
    s.process_outbound_cycle_with_handoff(
        cycle,
        input(s, now, vec![]),
        |_| Ok(batch(now)),
        |event| match event {
            OutboundEvent::DataAck { .. } | OutboundEvent::ControlAck { .. } => {
                panic!("managed ACKs must use their recorded instance")
            }
            _ => None,
        },
    )
}

fn data_attempts(s: &Store, key: &str) -> String {
    s.conn
        .query_row(
            "SELECT data_ack_budget FROM messages WHERE key=?1",
            [key],
            |row| row.get(0),
        )
        .unwrap()
}

#[test]
fn destination_ack_merges_retransmission_and_binds_each_reply_to_its_instance() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = register(&mut s, 2);
    let wrong = register(&mut s, 3);
    let err = s
        .receive_destination_on_channel(&wrong, destination("one", 0))
        .unwrap_err();
    assert_eq!(err.code, Code::Conflict);
    assert!(s.message("one").unwrap().is_none());
    assert_eq!(
        s.receive_destination_on_channel(&channel, relay("relay"))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let (view, ack) = s
        .receive_destination_on_channel(&channel, destination("one", 0))
        .unwrap();
    assert!(view.receipt_intent_pending);
    assert_eq!(ack, Ack::Queued);
    assert_eq!(
        s.receive_destination_on_channel(&channel, destination("one", 0))
            .unwrap()
            .1,
        Ack::Queued
    );
    s.receive(destination("legacy", 1)).unwrap();
    assert_eq!(s.outbound_acks.len(), 1);
    assert_eq!(data_attempts(&s, "one"), "[]");

    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = round(&mut s, &mut cycle, 1000).unwrap();
    assert_eq!(report.ack_inputs, 1);
    assert!(report.discarded_queued_acks.is_empty());
    assert!(
        matches!(&report.outbound.decisions[..], [OutboundDecision::DataAck { message, send: true, .. }] if message == "one")
    );
    assert!(s.outbound_acks.is_empty());
    let request = s.next_outbound_handoff().unwrap();
    assert_eq!(request.channel, channel.binding());
    s.close_control_ingress_channel(&channel).unwrap();
    let replacement = register(&mut s, 2);
    assert_ne!(request.channel, replacement.binding());
    let step = s.advance_outbound_handoff(
        &request,
        OutboundHandoffInput {
            clock: clock(1000),
            channel: Some(request.channel),
            frame: OutboundFrame::Control { bytes: 127 },
        },
        |_, _| panic!("closed original channel cannot write even if supplied as current"),
    );
    assert_eq!(step.result.unwrap_err().code, Code::Conflict);
    assert_eq!(step.close, Some(channel.binding()));
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&data_attempts(&s, "one")).unwrap()[0]["attempts"],
        1
    );
    assert_eq!(data_attempts(&s, "legacy"), "[]");
    assert!(s.outbound_acks.is_empty());
    assert_eq!(
        s.receive_destination_on_channel(&channel, destination("one", 1))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(
        s.receive_destination_on_channel(&replacement, destination("one", 1))
            .unwrap()
            .1,
        Ack::Queued
    );
    assert_eq!(round(&mut s, &mut cycle, 1250).unwrap().ack_inputs, 1);
    assert_eq!(
        s.next_outbound_handoff().unwrap().channel,
        replacement.binding()
    );
}

#[test]
fn destination_recovers_lost_ack_on_same_boot_reopen_without_reapplying_delivery() {
    for finalized in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        let source = register(&mut s, 2);
        s.receive_destination_on_channel(&source, destination("one", 0))
            .unwrap();
        let mut cycle = s.start_outbound_cycle().unwrap();
        assert_eq!(round(&mut s, &mut cycle, 1000).unwrap().ack_inputs, 1);
        let request = s.next_outbound_handoff().unwrap();
        let output = s.advance_outbound_handoff(
            &request,
            OutboundHandoffInput {
                clock: clock(1000),
                channel: Some(source.binding()),
                frame: OutboundFrame::Control { bytes: 127 },
            },
            |_, remaining| OutboundWrite::Written(remaining),
        );
        assert_eq!(output.result.unwrap(), OutboundWriteProgress::Complete);
        // The upstream misses the ACK. Receipt work may advance independently.
        if finalized {
            s.finalize_receipt("one", b"synthetic intent", b"synthetic proof", 5)
                .unwrap();
        }
        let spent = data_attempts(&s, "one");
        drop(s);

        let mut s = w.reopen(1001);
        assert!(s.outbound_acks.is_empty());
        assert!(s.next_outbound_handoff().is_none());
        assert_eq!(data_attempts(&s, "one"), spent);
        let replacement = register(&mut s, 2);
        let revision = s.revision().unwrap();
        let (view, ack) = s
            .receive_destination_on_channel(&replacement, destination("one", 1))
            .unwrap();
        assert_eq!(ack, Ack::Queued);
        assert_eq!(s.revision().unwrap(), revision);
        assert_eq!(s.history(0, 10).unwrap().len(), 1);
        assert_eq!(view.receipt_intent_pending, !finalized);
        assert_eq!(view.evidence_pending, finalized);
        assert_eq!(data_attempts(&s, "one"), spent);

        let mut cycle = s.start_outbound_cycle().unwrap();
        assert_eq!(round(&mut s, &mut cycle, 2001).unwrap().ack_inputs, 1);
        let request = s.next_outbound_handoff().unwrap();
        assert_eq!(request.channel, replacement.binding());
        let output = s.advance_outbound_handoff(
            &request,
            OutboundHandoffInput {
                clock: clock(2001),
                channel: Some(replacement.binding()),
                frame: OutboundFrame::Control { bytes: 127 },
            },
            |offset, remaining| {
                assert_eq!((offset, remaining), (0, 127));
                OutboundWrite::Written(remaining)
            },
        );
        assert_eq!(output.result.unwrap(), OutboundWriteProgress::Complete);
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&data_attempts(&s, "one")).unwrap()[0]["attempts"],
            2
        );
    }
}

#[test]
fn destination_rejects_wrong_source_changed_ciphertext_and_marker_only_recovery() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    let other = register(&mut s, 3);
    s.receive_destination_on_channel(&source, destination("one", 0))
        .unwrap();
    s.close_control_ingress_channel(&source).unwrap();
    let replacement = register(&mut s, 2);

    let mut wrong_source = destination("one", 1);
    wrong_source.neighbor = credential_key(&test_credential(3));
    wrong_source.message.deadline_ms = 5000;
    assert_eq!(
        s.receive_destination_on_channel(&other, wrong_source)
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let mut wrong_payload = destination("one", 1);
    wrong_payload.message.payload.push(1);
    wrong_payload.message.deadline_ms = 5000;
    assert_eq!(
        s.receive_destination_on_channel(&replacement, wrong_payload)
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(s.message_remaining_ms("one").unwrap(), 10000);
    assert!(s.outbound_acks.is_empty());

    // Isolate the durable evidence gate from the normal cleanup deadline.
    s.conn
        .execute(
            "UPDATE messages SET state='delivered',payload=NULL WHERE key='one'",
            [],
        )
        .unwrap();
    let mut marker_only = destination("one", 1);
    marker_only.message.payload.push(1);
    marker_only.message.deadline_ms = 5000;
    assert_eq!(
        s.receive_destination_on_channel(&replacement, marker_only)
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert_eq!(s.message_remaining_ms("one").unwrap(), 10000);
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn destination_rejects_recovery_without_committed_receipt_work() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.receive_destination_on_channel(&source, destination("one", 0))
        .unwrap();
    s.close_control_ingress_channel(&source).unwrap();
    let replacement = register(&mut s, 2);
    // Remove the responsibility in the fixture to exercise the proof gate itself.
    s.conn
        .execute("DELETE FROM receipt_intents WHERE message_key='one'", [])
        .unwrap();
    assert_eq!(
        s.receive_destination_on_channel(&replacement, destination("one", 1))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert!(s.outbound_acks.is_empty());
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
}

#[test]
fn destination_revocation_blocks_retransmissions_and_withdraws_recovered_ack() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.receive_destination_on_channel(&source, destination("one", 0))
        .unwrap();
    s.close_control_ingress_channel(&source).unwrap();
    let replacement = register(&mut s, 2);
    assert_eq!(
        s.receive_destination_on_channel(&replacement, destination("one", 1))
            .unwrap()
            .1,
        Ack::Queued
    );
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    let mut duplicate = destination("one", 1);
    duplicate.expected_policy_revision = s.business_policy_revision(ACTIVITY).unwrap();
    assert_eq!(
        s.receive_destination_on_channel(&replacement, duplicate)
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = round(&mut s, &mut cycle, 1000).unwrap();
    assert_eq!(report.ack_inputs, 0);
    assert_eq!(report.discarded_queued_acks.len(), 1);
    assert_eq!(report.discarded_queued_acks[0].code, Code::Conflict);
    assert_eq!(data_attempts(&s, "one"), "[]");
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!(s.history(0, 10).unwrap().len(), 1);
}

#[test]
fn destination_recovery_keeps_exhausted_ack_budget_across_reopen() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    let mut cycle = s.start_outbound_cycle().unwrap();
    for attempt in 0..10 {
        assert_eq!(
            s.receive_destination_on_channel(&source, destination("one", 0))
                .unwrap()
                .1,
            Ack::Queued
        );
        assert_eq!(
            round(&mut s, &mut cycle, 1000 + attempt * 250)
                .unwrap()
                .ack_inputs,
            1
        );
        assert!(s.next_outbound_handoff().is_some());
        s.cancel_outbound_handoff();
    }
    let spent = data_attempts(&s, "one");
    assert_eq!(
        serde_json::from_str::<serde_json::Value>(&spent).unwrap()[0]["attempts"],
        10
    );
    assert_eq!(
        s.receive_destination_on_channel(&source, destination("one", 0))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert!(s.outbound_acks.is_empty());
    drop(s);

    let mut s = w.reopen(3251);
    let replacement = register(&mut s, 2);
    assert_eq!(
        s.receive_destination_on_channel(&replacement, destination("one", 0))
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert!(s.outbound_acks.is_empty());
    assert_eq!(data_attempts(&s, "one"), spent);
}

#[test]
fn new_control_requires_original_neighbor_row_and_known_or_merged_does_not_queue() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = register(&mut s, 2);
    s.advance_clock(clock(2000)).unwrap();
    let new = object(4, 5, 10);
    assert_eq!(
        s.queue_control_candidate_on_channel(&channel, &new.cose)
            .unwrap(),
        ControlIngressAdmission::Queued
    );
    let job = s.next_control_verification().unwrap().job.unwrap();
    let neighbors = [ControlNeighbor {
        participant: [2; 16],
        link: Link::Down,
    }];
    assert_eq!(
        s.complete_control_verification_with_ack(
            job,
            ControlVerificationOutcome::Verified(Box::new(new)),
            &neighbors
        )
        .unwrap(),
        (
            ControlVerificationCompletion::Accepted(ControlAdmission::Inserted([10; 32])),
            Ack::Queued
        )
    );
    assert_eq!(
        s.queue_control_candidate_on_channel(&channel, &[10])
            .unwrap(),
        ControlIngressAdmission::Known([10; 32])
    );

    s.advance_clock(clock(3000)).unwrap();
    let mut duplicate = object(4, 5, 10);
    duplicate.cose = vec![10, 10];
    s.queue_control_candidate_on_channel(&channel, &duplicate.cose)
        .unwrap();
    let job = s.next_control_verification().unwrap().job.unwrap();
    assert_eq!(
        s.complete_control_verification_with_ack(
            job,
            ControlVerificationOutcome::Verified(Box::new(duplicate)),
            &neighbors
        )
        .unwrap(),
        (
            ControlVerificationCompletion::Accepted(ControlAdmission::Merged([10; 32])),
            Ack::NotEligible
        )
    );

    s.advance_clock(clock(4000)).unwrap();
    let no_neighbor = object(5, 4, 11);
    s.queue_control_candidate_on_channel(&channel, &no_neighbor.cose)
        .unwrap();
    let job = s.next_control_verification().unwrap().job.unwrap();
    assert_eq!(
        s.complete_control_verification_with_ack(
            job,
            ControlVerificationOutcome::Verified(Box::new(no_neighbor)),
            &[]
        )
        .unwrap(),
        (
            ControlVerificationCompletion::Accepted(ControlAdmission::Inserted([11; 32])),
            Ack::NotEligible
        )
    );

    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = round(&mut s, &mut cycle, 4000).unwrap();
    assert_eq!(report.ack_inputs, 1);
    assert!(report.outbound.decisions.iter().any(|d| matches!(d, OutboundDecision::ControlAck { object, send: true, .. } if *object == [10; 32])));
    let request = s.next_outbound_handoff().unwrap();
    assert_eq!(request.channel, channel.binding());
    let step = s.advance_outbound_handoff(
        &request,
        OutboundHandoffInput {
            clock: clock(4000),
            channel: Some(channel.binding()),
            frame: OutboundFrame::Control { bytes: 127 },
        },
        |offset, left| {
            assert_eq!(offset, 0);
            OutboundWrite::Written(left)
        },
    );
    assert_eq!(step.result.unwrap(), OutboundWriteProgress::Complete);
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        1
    );
    assert!(s.control_progress([11; 32], [2; 16]).unwrap().is_none());
}

#[test]
fn full_queue_preserves_seventeenth_receive_and_dispatches_once_at_existing_rate() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = register(&mut s, 2);
    for n in 0..=MAX_CYCLE_ACKS {
        let key = format!("d{n:02}");
        let (view, ack) = s
            .receive_destination_on_channel(&channel, destination(&key, n as i64))
            .unwrap();
        assert!(view.receipt_intent_pending);
        assert_eq!(
            ack,
            if n == MAX_CYCLE_ACKS {
                Ack::Full
            } else {
                Ack::Queued
            }
        );
    }
    assert_eq!(s.outbound_acks.len(), MAX_CYCLE_ACKS);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let explicit = input(&s, 1000, vec![super::outbound_cycle_tests::ack()]);
    assert_eq!(
        s.process_outbound_cycle_with_handoff(&mut cycle, explicit, |_| Ok(batch(1000)), |_| None)
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert_eq!(s.outbound_acks.len(), MAX_CYCLE_ACKS);
    let report = round(&mut s, &mut cycle, 1000).unwrap();
    assert_eq!(report.ack_inputs, MAX_CYCLE_ACKS);
    assert_eq!(
        report
            .outbound
            .decisions
            .iter()
            .filter(|d| matches!(d, OutboundDecision::DataAck { send: true, .. }))
            .count(),
        4
    );
    assert!(s.outbound_acks.is_empty());
    s.cancel_outbound_handoff();
    assert_eq!(round(&mut s, &mut cycle, 2000).unwrap().ack_inputs, 0);
    assert!(s.message("d16").unwrap().unwrap().receipt_intent_pending);
    assert_eq!(data_attempts(&s, "d16"), "[]");
}

#[test]
fn close_before_cutoff_discards_old_instance_and_expiry_discards_other_reply() {
    let w = Workspace::new();
    let mut s = w.create();
    let old = register(&mut s, 2);
    s.receive_destination_on_channel(&old, destination("closed", 0))
        .unwrap();
    s.close_control_ingress_channel(&old).unwrap();
    let replacement = register(&mut s, 2);
    assert!(s.outbound_acks.is_empty());
    s.receive_destination_on_channel(&replacement, destination("expired", 1))
        .unwrap();
    assert_eq!(s.outbound_acks.len(), 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = round(&mut s, &mut cycle, 10000).unwrap();
    assert_eq!(report.ack_inputs, 0);
    assert_eq!(report.discarded_queued_acks.len(), 1);
    assert_eq!(report.discarded_queued_acks[0].code, Code::Expired);
    assert!(s.outbound_acks.is_empty());
    assert_eq!(data_attempts(&s, "closed"), "[]");
    assert_eq!(data_attempts(&s, "expired"), "[]");
    assert_eq!(
        s.receive_destination_on_channel(&replacement, destination("expired", 1))
            .unwrap_err()
            .code,
        Code::Expired
    );
}

#[test]
fn queued_control_reply_is_rechecked_if_issuer_is_revoked_before_cutoff() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    let report = object(4, 5, 10);
    s.queue_control_candidate_on_channel(&channel, &report.cose)
        .unwrap();
    let job = s.next_control_verification().unwrap().job.unwrap();
    let (_, ack) = s
        .complete_control_verification_with_ack(
            job,
            ControlVerificationOutcome::Verified(Box::new(report)),
            &[ControlNeighbor {
                participant: [2; 16],
                link: Link::Down,
            }],
        )
        .unwrap();
    assert_eq!(ack, Ack::Queued);
    s.block_control_binding(ACTIVITY, test_credential(4))
        .unwrap();
    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = round(&mut s, &mut cycle, 1001).unwrap();
    assert_eq!(report.ack_inputs, 0);
    assert_eq!(report.discarded_queued_acks[0].code, Code::Conflict);
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        0
    );
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn rollback_keeps_original_slots_and_unknown_dispatch_discards_them() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        let channel = register(&mut s, 2);
        s.receive_destination_on_channel(&channel, destination("one", 0))
            .unwrap();
        let mut cycle = s.start_outbound_cycle().unwrap();
        let unknown = fault == TestFault::AfterCommit;
        s.fault = Some(fault);
        let err = round(&mut s, &mut cycle, 1000).err().unwrap();
        assert_eq!(
            err.code,
            if unknown {
                Code::OutcomeUnknown
            } else {
                Code::StoreUnavailable
            }
        );
        assert_eq!(s.outbound_acks.len(), usize::from(!unknown));
        assert!(s.next_outbound_handoff().is_none());
        if !unknown {
            assert_eq!(data_attempts(&s, "one"), "[]");
            s.fault = None;
            assert_eq!(round(&mut s, &mut cycle, 1001).unwrap().ack_inputs, 1);
        }
        drop(s);
        let s = w.reopen(1001);
        assert!(s.outbound_acks.is_empty());
        assert!(s.next_outbound_handoff().is_none());
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&data_attempts(&s, "one")).unwrap()[0]["attempts"],
            1
        );
    }
}

#[test]
fn failed_or_unknown_receive_does_not_create_a_reply() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        let channel = register(&mut s, 2);
        s.fault = Some(fault);
        let unknown = fault == TestFault::AfterCommit;
        let err = s
            .receive_destination_on_channel(&channel, destination("one", 0))
            .unwrap_err();
        assert_eq!(
            err.code,
            if unknown {
                Code::OutcomeUnknown
            } else {
                Code::StoreUnavailable
            }
        );
        assert!(s.outbound_acks.is_empty());
        drop(s);
        let mut s = w.reopen(0);
        assert_eq!(s.message("one").unwrap().is_some(), unknown);
        assert!(s.outbound_acks.is_empty());
        let replacement = register(&mut s, 2);
        assert_eq!(
            s.receive_destination_on_channel(&replacement, destination("one", 0))
                .unwrap()
                .1,
            Ack::Queued
        );
        assert_eq!(s.history(0, 10).unwrap().len(), 1);
    }
}
