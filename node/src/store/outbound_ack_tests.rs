use super::outbound_cycle_tests::input;
use super::outbound_tests::{batch, object};
use super::tests::{ACTIVITY, Workspace, clock, destination, relay, test_credential};
use super::*;
use ControlIngressAdmission as Ingress;
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

fn control_source(s: &Store, object: ObjectRef) -> Option<Vec<u8>> {
    s.conn
        .query_row(
            "SELECT ack_source_credential FROM control_objects WHERE reference=?1",
            [object.as_slice()],
            |row| row.get(0),
        )
        .unwrap()
}

fn strip_v10(s: &Store) {
    s.conn
        .execute_batch(
            "DROP TRIGGER control_ack_source_immutable;
         ALTER TABLE control_objects DROP COLUMN ack_source_credential;
         PRAGMA user_version=9;",
        )
        .unwrap();
}

fn accept_control_on_channel(
    s: &mut Store,
    channel: &ControlIngressChannel,
    control: PreparedControl,
    peers: &[u8],
) -> Result<(ControlVerificationCompletion, Ack)> {
    assert_eq!(
        s.queue_control_candidate_on_channel(channel, &control.cose)?,
        (Ingress::Queued, Ack::NotEligible)
    );
    let job = s.next_control_verification()?.job.unwrap();
    let neighbors: Vec<_> = peers
        .iter()
        .map(|peer| ControlNeighbor {
            participant: [*peer; 16],
            link: Link::Down,
        })
        .collect();
    s.complete_control_verification_with_ack(
        job,
        ControlVerificationOutcome::Verified(Box::new(control)),
        &neighbors,
    )
}

#[test]
fn control_ack_recovers_only_for_original_credential_after_reopen_and_reconnect() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    // The actual upstream forwarded an exit issued by a different participant.
    assert_eq!(
        accept_control_on_channel(&mut s, &source, object(4, 4, 10), &[2, 3])
            .unwrap()
            .1,
        Ack::Queued
    );
    assert_eq!(
        control_source(&s, [10; 32]),
        Some(test_credential(2).to_vec())
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    assert_eq!(round(&mut s, &mut cycle, 2000).unwrap().ack_inputs, 1);
    let request = s.next_outbound_handoff().unwrap();
    assert_eq!(request.channel, source.binding());
    let step = s.advance_outbound_handoff(
        &request,
        OutboundHandoffInput {
            clock: clock(2000),
            channel: Some(source.binding()),
            frame: OutboundFrame::Control { bytes: 127 },
        },
        |_, remaining| OutboundWrite::Written(remaining),
    );
    assert_eq!(step.result.unwrap(), OutboundWriteProgress::Complete);
    drop(s);

    let mut s = w.reopen(2001);
    assert!(s.outbound_acks.is_empty());
    assert!(s.next_outbound_handoff().is_none());
    let other = register(&mut s, 3);
    let original = register(&mut s, 2);
    s.advance_clock(clock(4001)).unwrap();
    let known = Ingress::Known([10; 32]);
    assert_eq!(
        s.queue_control_candidate_on_channel(&other, &[10]).unwrap(),
        (known, Ack::NotEligible)
    );
    assert_eq!(
        s.queue_control_candidate_on_channel(&original, &[10])
            .unwrap(),
        (known, Ack::Queued)
    );
    s.close_control_ingress_channel(&original).unwrap();
    let replacement = register(&mut s, 2);
    assert_ne!(replacement.binding(), original.binding());
    assert!(s.outbound_acks.is_empty());
    assert_eq!(
        s.queue_control_candidate_on_channel(&original, &[10])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(
        s.queue_control_candidate_on_channel(&replacement, &[10])
            .unwrap(),
        (known, Ack::Queued)
    );
    assert_eq!(
        s.queue_control_candidate_on_channel(&replacement, &[10])
            .unwrap(),
        (Ingress::RateLimited, Ack::NotEligible)
    );
    assert_eq!(s.control_ingress_usage().waiting, 0);
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        1
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    assert_eq!(round(&mut s, &mut cycle, 4001).unwrap().ack_inputs, 1);
    assert_eq!(
        s.next_outbound_handoff().unwrap().channel,
        replacement.binding()
    );
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        2
    );
}

#[test]
fn control_known_does_not_infer_source_from_legacy_later_neighbor_or_key_rotation() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.accept_control(object(5, 4, 11), &[]).unwrap();
    s.schedule_control_neighbor(
        ACTIVITY,
        [11; 32],
        ControlNeighbor {
            participant: [2; 16],
            link: Link::Down,
        },
    )
    .unwrap();
    s.advance_clock(clock(2000)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[11])
            .unwrap(),
        (Ingress::Known([11; 32]), Ack::NotEligible)
    );
    assert_eq!(control_source(&s, [11; 32]), None);
    assert_eq!(
        accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2])
            .unwrap()
            .1,
        Ack::Queued
    );
    s.close_control_ingress_channel(&source).unwrap();
    let rotated = [22; 32];
    s.stage_control_binding(
        ACTIVITY,
        ControlBinding {
            participant: [2; 16],
            credential: rotated,
            generation: 2,
            body: vec![22],
        },
    )
    .unwrap();
    s.activate_control_binding(ACTIVITY, rotated, &[22])
        .unwrap();
    let replacement = s
        .register_control_ingress_channel(ACTIVITY, test_credential(1), rotated)
        .unwrap();
    s.advance_clock(clock(3000)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&replacement, &[10])
            .unwrap(),
        (Ingress::Known([10; 32]), Ack::NotEligible)
    );
    assert_eq!(
        control_source(&s, [10; 32]),
        Some(test_credential(2).to_vec())
    );
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn control_ack_tenth_attempt_hands_off_but_reopen_cannot_restore_allowance() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    assert_eq!(
        accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2])
            .unwrap()
            .1,
        Ack::Queued
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    for attempt in 1..=10 {
        let now = i64::from(attempt + 1) * 1000;
        s.advance_clock(clock(now)).unwrap();
        assert_eq!(
            s.queue_control_candidate_on_channel(&source, &[10])
                .unwrap(),
            (Ingress::Known([10; 32]), Ack::Queued)
        );
        assert_eq!(round(&mut s, &mut cycle, now).unwrap().ack_inputs, 1);
        assert_eq!(
            s.control_progress([10; 32], [2; 16])
                .unwrap()
                .unwrap()
                .ack_attempts,
            attempt
        );
        let request = s.next_outbound_handoff().unwrap();
        let step = s.advance_outbound_handoff(
            &request,
            OutboundHandoffInput {
                clock: clock(now),
                channel: Some(source.binding()),
                frame: OutboundFrame::Control { bytes: 127 },
            },
            |_, remaining| OutboundWrite::Written(remaining),
        );
        assert_eq!(step.result.unwrap(), OutboundWriteProgress::Complete);
    }
    drop(s);
    let mut s = w.reopen(11001);
    let source = register(&mut s, 2);
    s.advance_clock(clock(12001)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[10])
            .unwrap(),
        (Ingress::Known([10; 32]), Ack::NotEligible)
    );
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        10
    );
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn stopped_v9_migration_preserves_control_rows_without_inventing_source() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    assert_eq!(
        accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2])
            .unwrap()
            .1,
        Ack::Queued
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    assert_eq!(round(&mut s, &mut cycle, 2000).unwrap().ack_inputs, 1);
    s.cancel_outbound_handoff();
    s.close_control_ingress_channel(&source).unwrap();
    s.stop_control_activity(ACTIVITY).unwrap();
    let usage = s.control_usage().unwrap();
    let progress = s.control_progress([10; 32], [2; 16]).unwrap().unwrap();
    assert_eq!(progress.ack_attempts, 1);
    strip_v10(&s);
    drop(s);

    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(2001))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    assert_eq!(
        Store::open_version(
            &w.dir,
            Limits::default(),
            clock(2001),
            OpenMode::MigrateV9Fault(TestFault::BeforeCommit)
        )
        .err()
        .unwrap()
        .code,
        Code::StoreUnavailable
    );
    {
        let old = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        assert_eq!(
            old.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                .unwrap(),
            9
        );
        assert!(
            old.prepare("SELECT ack_source_credential FROM control_objects")
                .is_err()
        );
    }
    let s = Store::migrate_v9(&w.dir, Limits::default(), clock(2001)).unwrap();
    assert_eq!(s.schema_version().unwrap(), SCHEMA_VERSION);
    assert_eq!(control_source(&s, [10; 32]), None);
    assert_eq!(s.control_usage().unwrap(), usage);
    assert_eq!(
        s.control_progress([10; 32], [2; 16]).unwrap().unwrap(),
        progress
    );
    assert!(s.outbound_acks.is_empty());
    assert_eq!(
        s.conn
            .query_row(
                "SELECT body FROM control_objects WHERE reference=?1",
                [[10; 32].as_slice()],
                |r| r.get::<_, Vec<u8>>(0)
            )
            .unwrap(),
        [10]
    );
    assert!(
        s.conn
            .execute(
                "UPDATE control_objects SET ack_source_credential=?1",
                [test_credential(2).as_slice()],
            )
            .is_err()
    );
}

#[test]
fn v9_migration_rejects_active_activity_and_cross_boot() {
    for (stopped, expected) in [(false, Code::Conflict), (true, Code::TimeUncertain)] {
        let w = Workspace::new();
        let mut s = w.create();
        let mut sample = clock(1);
        if stopped {
            s.stop_control_activity(ACTIVITY).unwrap();
            sample.boot = "other-boot".into();
        }
        strip_v10(&s);
        drop(s);
        assert_eq!(
            Store::migrate_v9(&w.dir, Limits::default(), sample)
                .err()
                .unwrap()
                .code,
            expected
        );
        let old = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        assert_eq!(
            old.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
                .unwrap(),
            9
        );
    }
}

#[test]
fn control_ack_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_CONTROL_ACK_TEST_STORE") else {
        return;
    };
    let mut s = Store::open(Path::new(&dir), Limits::default(), clock(0)).unwrap();
    let source = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    s.fault = Some(
        match std::env::var("RADISHLINK_CONTROL_ACK_TEST_SIDE")
            .unwrap()
            .as_str()
        {
            "before" => TestFault::CrashBeforeCommit,
            "after" => TestFault::CrashAfterCommit,
            _ => panic!("invalid synthetic side"),
        },
    );
    accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2]).unwrap();
    panic!("expected controlled process exit");
}

#[test]
fn control_ack_process_exit_recovers_whole_acceptance_and_source() {
    for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
        let w = Workspace::new();
        drop(w.create());
        let status = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "store::outbound_ack_tests::control_ack_crash_child",
                "--nocapture",
            ])
            .env("RADISHLINK_CONTROL_ACK_TEST_STORE", &w.dir)
            .env("RADISHLINK_CONTROL_ACK_TEST_SIDE", side)
            .status()
            .unwrap();
        assert_eq!(status.code(), Some(exit));
        let mut s = w.reopen(1001);
        assert!(s.outbound_acks.is_empty());
        assert_eq!(
            s.control_progress([10; 32], [2; 16]).unwrap().is_some(),
            committed
        );
        if committed {
            assert_eq!(
                control_source(&s, [10; 32]),
                Some(test_credential(2).to_vec())
            );
        }
        let source = register(&mut s, 2);
        s.advance_clock(clock(2001)).unwrap();
        assert_eq!(
            s.queue_control_candidate_on_channel(&source, &[10])
                .unwrap(),
            if committed {
                (Ingress::Known([10; 32]), Ack::Queued)
            } else {
                (Ingress::Queued, Ack::NotEligible)
            }
        );
    }
}

#[test]
fn control_full_ack_queue_retains_source_for_recovery() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    for index in 0..MAX_CYCLE_ACKS {
        s.receive_destination_on_channel(
            &source,
            destination(&format!("d{index:02}"), index as i64),
        )
        .unwrap();
    }
    s.advance_clock(clock(2000)).unwrap();
    assert_eq!(
        accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2])
            .unwrap()
            .1,
        Ack::Full
    );
    assert_eq!(
        control_source(&s, [10; 32]),
        Some(test_credential(2).to_vec())
    );
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[10])
            .unwrap(),
        (Ingress::Known([10; 32]), Ack::Full)
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    assert_eq!(
        round(&mut s, &mut cycle, 2000).unwrap().ack_inputs,
        MAX_CYCLE_ACKS
    );
    s.cancel_outbound_handoff();
    s.advance_clock(clock(3000)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[10])
            .unwrap(),
        (Ingress::Known([10; 32]), Ack::Queued)
    );
    s.shorten_control_activity(ACTIVITY, 4000).unwrap();
    // Stop exactly at the activity boundary without handing off the queued reply.
    s.advance_clock(clock(4000)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[10])
            .unwrap_err()
            .code,
        Code::Expired
    );
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        0
    );
}

#[test]
fn direct_exit_does_not_record_ack_source_for_the_credential_it_blocks() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    assert_eq!(
        accept_control_on_channel(&mut s, &source, object(2, 2, 10), &[2, 3])
            .unwrap()
            .1,
        Ack::NotEligible
    );
    assert_eq!(control_source(&s, [10; 32]), None);
    s.advance_clock(clock(2000)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[10])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    let other = register(&mut s, 3);
    assert_eq!(
        s.queue_control_candidate_on_channel(&other, &[10]).unwrap(),
        (Ingress::Known([10; 32]), Ack::NotEligible)
    );
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn control_ack_source_and_object_commit_together_before_reopen_recovery() {
    for (fault, expected, committed) in [
        (TestFault::BeforeCommit, Code::StoreUnavailable, false),
        (TestFault::AfterCommit, Code::OutcomeUnknown, true),
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        let source = register(&mut s, 2);
        s.advance_clock(clock(1000)).unwrap();
        s.fault = Some(fault);
        assert_eq!(
            accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2])
                .unwrap_err()
                .code,
            expected
        );
        assert!(s.outbound_acks.is_empty());
        drop(s);
        let mut s = w.reopen(1001);
        assert!(s.outbound_acks.is_empty());
        assert_eq!(
            s.control_object(ACTIVITY, [10; 32]).unwrap().is_some(),
            committed
        );
        if committed {
            assert_eq!(
                control_source(&s, [10; 32]),
                Some(test_credential(2).to_vec())
            );
        }
        let replacement = register(&mut s, 2);
        s.advance_clock(clock(2001)).unwrap();
        assert_eq!(
            s.queue_control_candidate_on_channel(&replacement, &[10])
                .unwrap(),
            if committed {
                (Ingress::Known([10; 32]), Ack::Queued)
            } else {
                (Ingress::Queued, Ack::NotEligible)
            }
        );
    }
}

#[test]
fn ambiguous_control_bytes_cannot_offer_ack_to_the_original_source() {
    let w = Workspace::new();
    let mut s = w.create();
    let source = register(&mut s, 2);
    s.advance_clock(clock(1000)).unwrap();
    accept_control_on_channel(&mut s, &source, object(4, 5, 10), &[2]).unwrap();
    s.close_control_ingress_channel(&source).unwrap();
    let mut other = object(3, 5, 11);
    other.cose = vec![10];
    s.accept_control(other, &[]).unwrap();
    let source = register(&mut s, 2);
    s.advance_clock(clock(2000)).unwrap();
    assert_eq!(
        s.queue_control_candidate_on_channel(&source, &[10])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert!(s.outbound_acks.is_empty());
    assert_eq!(s.control_ingress_usage().waiting, 0);
    assert_eq!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        0
    );
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
            .unwrap()
            .0,
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
            .unwrap()
            .0,
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
