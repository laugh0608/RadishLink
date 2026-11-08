use super::outbound_cycle_tests::{ack, ack_budget, data, input};
use super::outbound_tests::{add_control, batch, object, prepare_receipt};
use super::tests::{ACTIVITY, PEER_3, Workspace, clock, test_credential};
use super::*;
use crate::retry::{Admission, LinkEvent, Signal};

const DATA: OutboundFrame = OutboundFrame::Data {
    bytes: 64,
    remaining_ms: 500,
    hops: 0,
};
const CONTROL: OutboundFrame = OutboundFrame::Control { bytes: 32 };
const ACK: OutboundFrame = OutboundFrame::Control { bytes: 127 };

fn channel(peer: u8) -> OutboundChannel {
    OutboundChannel {
        instance: u64::from(peer),
        local: [1; 16],
        local_credential: test_credential(1),
        peer: [peer; 16],
        peer_credential: test_credential(peer),
    }
}

fn binding(event: &OutboundEvent) -> Option<OutboundChannel> {
    Some(match event {
        OutboundEvent::Queue(event) if event.queue.neighbor == PEER_3 => channel(3),
        _ => channel(2),
    })
}

fn round(
    s: &mut Store,
    cycle: &mut OutboundCycle,
    now: i64,
    acknowledgements: Vec<OutboundAck>,
) -> Result<OutboundCycleReport> {
    s.process_outbound_cycle_with_handoff(
        cycle,
        input(s, now, acknowledgements),
        |_| Ok(batch(now)),
        binding,
    )
}

fn frame_for(request: &OutboundHandoffRequest) -> OutboundFrame {
    match &request.responsibility {
        OutboundResponsibility::Queue(key) if key.kind == QueueKind::Data => DATA,
        OutboundResponsibility::DataAck(..) | OutboundResponsibility::ControlAck(..) => ACK,
        _ => CONTROL,
    }
}

fn step(
    s: &mut Store,
    request: &OutboundHandoffRequest,
    now: i64,
    write: impl FnOnce(usize, usize) -> OutboundWrite,
) -> OutboundHandoffStep {
    s.advance_outbound_handoff(
        request,
        OutboundHandoffInput {
            clock: clock(now),
            channel: Some(request.channel),
            frame: frame_for(request),
        },
        write,
    )
}

fn bucket(s: &Store) -> (i64, i64) {
    s.conn
        .query_row("SELECT frames,bytes FROM control_output_rate", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .unwrap()
}

#[test]
fn closing_withdraws_partial_output_and_fences_future_binding() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let source = s
        .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(2))
        .unwrap();
    let mut cycle = s.start_outbound_cycle().unwrap();
    let at = input(&s, 1000, vec![ack()]);
    s.process_outbound_cycle_with_handoff(
        &mut cycle,
        at,
        |_| Ok(batch(1000)),
        |event| match event {
            OutboundEvent::DataAck { .. } => Some(source.binding()),
            _ => binding(event),
        },
    )
    .unwrap();
    let first = s.next_outbound_handoff().unwrap();
    assert_eq!(first.channel, source.binding());
    assert_eq!(
        step(&mut s, &first, 1000, |_, _| OutboundWrite::Written(8))
            .result
            .unwrap(),
        OutboundWriteProgress::Partial(8)
    );
    let continuation = s.next_outbound_handoff().unwrap();
    let revision = s.revision().unwrap();
    let charged = (bucket(&s), ack_budget(&s));

    s.begin_control_ingress_channel_close(&source).unwrap();
    assert_eq!(
        step(&mut s, &continuation, 1000, |_, _| panic!(
            "closing must stop the partial frame"
        ))
        .result
        .unwrap_err()
        .code,
        Code::Conflict
    );
    let unrelated = s.next_outbound_handoff().unwrap();
    assert_eq!(unrelated.channel, channel(3));
    assert_eq!(
        step(&mut s, &unrelated, 1000, |_, left| OutboundWrite::Written(
            left
        ))
        .result
        .unwrap(),
        OutboundWriteProgress::Complete
    );
    let bind_old = |store: &mut Store, cycle: &mut OutboundCycle| {
        store
            .process_outbound_cycle_with_handoff(
                cycle,
                input(store, 1001, vec![ack()]),
                |_| Ok(batch(1001)),
                |_| Some(source.binding()),
            )
            .err()
            .unwrap()
    };
    assert_eq!(
        bind_old(&mut s, &mut cycle).operation,
        "control ingress channel closing"
    );
    s.close_control_ingress_channel(&source).unwrap();
    let replacement = s
        .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(2))
        .unwrap();
    assert_ne!(source.binding(), replacement.binding());
    assert_eq!(
        bind_old(&mut s, &mut cycle).operation,
        "control ingress channel instance changed"
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!((bucket(&s), ack_budget(&s)), charged);
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn all_five_paths_use_committed_decisions_and_charge_only_once() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    prepare_receipt(&mut s, "receipt", 32);
    add_control(&mut s, 4, 5, 10);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let report = round(
        &mut s,
        &mut cycle,
        1000,
        vec![
            ack(),
            OutboundAck::Control {
                object: [10; 32],
                neighbor: [2; 16],
            },
        ],
    )
    .unwrap();
    let outputs: Vec<_> = report
        .outbound
        .decisions
        .iter()
        .filter_map(OutboundDecision::output)
        .collect();
    assert_eq!(outputs.len(), 5);
    let charged = (
        bucket(&s),
        ack_budget(&s),
        s.control_progress([10; 32], [2; 16]).unwrap(),
    );
    let policy = s.business_policy_revision(ACTIVITY).unwrap();
    s.advance_clock(clock(1001)).unwrap();
    let revision = s.revision().unwrap();
    assert_eq!(s.business_policy_revision(ACTIVITY).unwrap(), policy);
    assert!(revision > report.cutoff_revision + 1 && policy != report.cutoff_revision);
    for expected in outputs {
        let request = s.next_outbound_handoff().unwrap();
        assert_eq!(request.responsibility, expected);
        let out = step(&mut s, &request, 1001, |offset, left| {
            assert_eq!(offset, 0);
            OutboundWrite::Written(left)
        });
        assert_eq!(out.result.unwrap(), OutboundWriteProgress::Complete);
        assert_eq!(out.close, None);
        let duplicate = step(&mut s, &request, 1001, |_, _| {
            panic!("must not write twice")
        });
        assert_eq!(duplicate.result.unwrap_err().code, Code::Conflict);
    }
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!(
        (
            bucket(&s),
            ack_budget(&s),
            s.control_progress([10; 32], [2; 16]).unwrap()
        ),
        charged
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert!(!s.message("q000").unwrap().unwrap().custody_observed);
}

#[test]
fn missing_binding_and_negative_decision_cannot_create_a_handoff() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let at = input(&s, 1000, vec![]);
    let report = s
        .process_outbound_cycle_with_handoff(&mut cycle, at, |_| Ok(batch(1000)), |_| None)
        .unwrap();
    assert!(report.outbound.decisions[0].output().is_some());
    assert!(s.next_outbound_handoff().is_none());
    let report = round(&mut s, &mut cycle, 1001, vec![]).unwrap();
    assert!(report.outbound.decisions[0].output().is_none());
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn conflicting_duplicate_ack_bindings_reject_before_any_charge() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let bad = input(
        &s,
        1000,
        vec![OutboundAck::Data {
            message: "x".repeat(65),
            neighbor: PEER_3.into(),
        }],
    );
    let err = s
        .process_outbound_cycle_with_handoff(
            &mut cycle,
            bad,
            |_| Ok(batch(1000)),
            |_| panic!("invalid reference must be rejected before capturing any bindings"),
        )
        .err()
        .unwrap();
    assert_eq!(err.code, Code::InvalidInput);
    let at = input(&s, 1000, vec![ack(), ack()]);
    let revision = at.expected_revision;
    let mut instance = 10;
    let err = s
        .process_outbound_cycle_with_handoff(
            &mut cycle,
            at,
            |_| Ok(batch(1000)),
            |_| {
                instance += 1;
                Some(OutboundChannel {
                    instance,
                    ..channel(2)
                })
            },
        )
        .err()
        .unwrap();
    assert_eq!(err.code, Code::Conflict);
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(ack_budget(&s), "[]");
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn failed_and_unknown_commit_never_publish_or_recover_a_handoff() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        let mut cycle = s.start_outbound_cycle().unwrap();
        s.fault = Some(fault);
        let err = round(&mut s, &mut cycle, 1000, vec![ack()]).err().unwrap();
        let unknown = fault == TestFault::AfterCommit;
        assert_eq!(
            err.code,
            if unknown {
                Code::OutcomeUnknown
            } else {
                Code::StoreUnavailable
            }
        );
        assert!(s.next_outbound_handoff().is_none());
        assert_eq!(s.is_quarantined(), unknown);
        drop(s);
        let s = w.reopen(1001);
        let slots: Vec<serde_json::Value> = serde_json::from_str(&ack_budget(&s)).unwrap();
        assert_eq!(slots.len(), usize::from(unknown));
        assert!(s.next_outbound_handoff().is_none());
    }
}

#[test]
fn short_write_continues_once_at_confirmed_offset() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(&mut s, &mut cycle, 1000, vec![]).unwrap();
    let first = s.next_outbound_handoff().unwrap();
    let out = step(&mut s, &first, 1001, |offset, left| {
        assert_eq!((offset, left), (0, 64));
        OutboundWrite::Written(10)
    });
    assert_eq!(out.result.unwrap(), OutboundWriteProgress::Partial(10));
    assert!(out.close.is_none());
    let err = step(&mut s, &first, 1001, |_, _| panic!("stale offset"))
        .result
        .unwrap_err();
    assert_eq!(err.code, Code::Conflict);
    assert_eq!(
        round(&mut s, &mut cycle, 1002, vec![]).err().unwrap().code,
        Code::Busy
    );
    assert_eq!(
        s.advance_queue("q000", "data", PEER_3, batch(1000))
            .unwrap_err()
            .code,
        Code::Busy
    );
    let continuation = s.next_outbound_handoff().unwrap();
    let out = step(&mut s, &continuation, 1002, |offset, left| {
        assert_eq!((offset, left), (10, 54));
        OutboundWrite::Written(left)
    });
    assert_eq!(out.result.unwrap(), OutboundWriteProgress::Complete);
    assert!(out.close.is_none());
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn revocation_after_a_short_write_closes_the_original_instance_without_refund() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(&mut s, &mut cycle, 1000, vec![ack()]).unwrap();
    let request = s.next_outbound_handoff().unwrap();
    assert!(matches!(
        request.responsibility,
        OutboundResponsibility::DataAck(..)
    ));
    let charged = (bucket(&s), ack_budget(&s));
    assert_eq!(
        step(&mut s, &request, 1000, |_, _| OutboundWrite::Written(12))
            .result
            .unwrap(),
        OutboundWriteProgress::Partial(12)
    );
    let request = s.next_outbound_handoff().unwrap();
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    let out = step(&mut s, &request, 1001, |_, _| panic!("revoked bytes"));
    assert_eq!(out.result.unwrap_err().code, Code::Conflict);
    assert_eq!(out.close, Some(channel(2)));
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!((bucket(&s), ack_budget(&s)), charged);
}

#[test]
fn same_credential_reconnect_cannot_take_an_old_item() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(&mut s, &mut cycle, 1000, vec![]).unwrap();
    let request = s.next_outbound_handoff().unwrap();
    let out = s.advance_outbound_handoff(
        &request,
        OutboundHandoffInput {
            clock: clock(1001),
            channel: Some(OutboundChannel {
                instance: 9,
                ..channel(3)
            }),
            frame: DATA,
        },
        |_, _| panic!("old attempt cannot move to new channel"),
    );
    assert_eq!(out.result.unwrap_err().code, Code::Conflict);
    assert_eq!(out.close, Some(channel(3)));
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn custody_and_original_deadline_are_rechecked_after_commit() {
    for (now, custody, expected) in [(1001, true, Code::Conflict), (10000, false, Code::Expired)] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        let mut cycle = s.start_outbound_cycle().unwrap();
        round(&mut s, &mut cycle, 1000, vec![]).unwrap();
        if custody {
            s.advance_clock(clock(now)).unwrap();
            s.observe_custody("q000", PEER_3).unwrap();
        }
        let request = s.next_outbound_handoff().unwrap();
        let out = step(&mut s, &request, now, |_, _| {
            panic!("no valid data responsibility")
        });
        assert_eq!(out.result.unwrap_err().code, expected);
        assert!(out.close.is_none());
    }
}

#[test]
fn frozen_encoded_lifetime_or_regressed_clock_stops_continuation() {
    for (now, expected) in [(9501, Code::Expired), (1000, Code::TimeUncertain)] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        let mut cycle = s.start_outbound_cycle().unwrap();
        round(&mut s, &mut cycle, 1000, vec![]).unwrap();
        let request = s.next_outbound_handoff().unwrap();
        step(&mut s, &request, 1001, |_, _| OutboundWrite::Written(1))
            .result
            .unwrap();
        let request = s.next_outbound_handoff().unwrap();
        let out = step(&mut s, &request, now, |_, _| {
            panic!("stale time must stop continuation")
        });
        assert_eq!(out.result.unwrap_err().code, expected);
        assert_eq!(out.close, Some(channel(3)));
        assert_eq!(s.is_time_uncertain(), expected == Code::TimeUncertain);
    }
}

#[test]
fn final_control_attempt_remains_eligible_unless_owner_withdraws_it() {
    for withdraw in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        add_control(&mut s, 4, 5, 10);
        let mut cycle = s.start_outbound_cycle().unwrap();
        for (now, link) in [
            (1800001, LinkEvent::Down),
            (1801000, LinkEvent::Up),
            (1801001, LinkEvent::Down),
        ] {
            s.process_control_batch(
                ACTIVITY,
                clock(now),
                vec![ControlEvent {
                    object: [10; 32],
                    neighbor: [2; 16],
                    link,
                    signal: Signal::Continue,
                    admission: Admission::Allow,
                }],
            )
            .unwrap();
        }
        let now = 1861000;
        let report = s
            .process_outbound_cycle_with_handoff(
                &mut cycle,
                input(&s, now, vec![]),
                |_| {
                    Ok(Batch {
                        link: LinkEvent::Up,
                        ..batch(now)
                    })
                },
                binding,
            )
            .unwrap();
        assert!(
            matches!(&report.outbound.decisions[0], OutboundDecision::Control(d) if d.send && d.progress.terminal)
        );
        let request = s.next_outbound_handoff().unwrap();
        if withdraw {
            assert!(
                s.withdraw_outbound_handoff(&request.responsibility)
                    .is_none()
            );
            let out = step(&mut s, &request, now, |_, _| {
                panic!("terminal input won ordering")
            });
            assert_eq!(out.result.unwrap_err().code, Code::Conflict);
        } else {
            assert_eq!(
                step(&mut s, &request, now, |_, left| OutboundWrite::Written(
                    left
                ))
                .result
                .unwrap(),
                OutboundWriteProgress::Complete
            );
        }
        assert!(s.next_outbound_handoff().is_none());
        assert_eq!(
            s.control_progress([10; 32], [2; 16])
                .unwrap()
                .unwrap()
                .attempts,
            2
        );
    }
}

#[test]
fn verified_local_exit_is_eligible_after_retirement_but_its_ack_is_not() {
    let w = Workspace::new();
    let mut s = w.create();
    let mut cycle = s.start_outbound_cycle().unwrap();
    s.begin_control_exit(object(1, 1, 10).fields).unwrap();
    round(&mut s, &mut cycle, 1, vec![]).unwrap();
    assert!(s.next_outbound_handoff().is_none());
    add_control(&mut s, 1, 1, 10);
    let report = round(
        &mut s,
        &mut cycle,
        1001,
        vec![OutboundAck::Control {
            object: [10; 32],
            neighbor: [2; 16],
        }],
    )
    .unwrap();
    assert!(
        report
            .outbound
            .decisions
            .iter()
            .any(|d| matches!(d, OutboundDecision::ControlAck { send: false, .. }))
    );
    let request = s.next_outbound_handoff().unwrap();
    assert!(matches!(
        request.responsibility,
        OutboundResponsibility::Control(..)
    ));
    assert_eq!(
        step(&mut s, &request, 1001, |_, left| OutboundWrite::Written(
            left
        ))
        .result
        .unwrap(),
        OutboundWriteProgress::Complete
    );
    assert!(s.next_outbound_handoff().is_none());
}

#[test]
fn writer_not_ready_unknown_and_shutdown_have_distinct_close_results() {
    for case in [0, 1, 2, 3] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        let mut cycle = s.start_outbound_cycle().unwrap();
        round(&mut s, &mut cycle, 1000, vec![]).unwrap();
        let request = s.next_outbound_handoff().unwrap();
        match case {
            0 => {
                let out = step(&mut s, &request, 1000, |_, _| OutboundWrite::NotReady);
                assert_eq!(out.result.unwrap(), OutboundWriteProgress::Discarded);
                assert!(out.close.is_none());
            }
            1 => {
                let out = step(&mut s, &request, 1000, |_, _| {
                    OutboundWrite::Unknown(Error::new(Code::OutcomeUnknown, "synthetic writer"))
                });
                assert_eq!(out.result.unwrap_err().operation, "synthetic writer");
                assert_eq!(out.close, Some(channel(3)));
            }
            2 => {
                step(&mut s, &request, 1000, |_, _| OutboundWrite::Written(1))
                    .result
                    .unwrap();
                s.stop_control_activity(ACTIVITY).unwrap();
                assert_eq!(s.cancel_outbound_handoff(), Some(channel(3)));
                let out = step(&mut s, &request, 1001, |_, _| panic!("owner closed"));
                assert_eq!(out.result.unwrap_err().code, Code::Conflict);
            }
            _ => {
                step(&mut s, &request, 1000, |_, _| OutboundWrite::Written(1))
                    .result
                    .unwrap();
                let continuation = s.next_outbound_handoff().unwrap();
                let out = step(&mut s, &continuation, 1001, |_, _| {
                    OutboundWrite::Failed(Error::new(
                        Code::StoreUnavailable,
                        "synthetic short write failure",
                    ))
                });
                assert_eq!(
                    out.result.unwrap_err().operation,
                    "synthetic short write failure"
                );
                assert_eq!(out.close, Some(channel(3)));
            }
        }
        assert!(s.next_outbound_handoff().is_none());
    }
}

#[test]
fn unknown_policy_commit_closes_partial_and_reopen_rejects_old_request() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(&mut s, &mut cycle, 1000, vec![]).unwrap();
    let request = s.next_outbound_handoff().unwrap();
    step(&mut s, &request, 1000, |_, _| OutboundWrite::Written(1))
        .result
        .unwrap();
    let continuation = s.next_outbound_handoff().unwrap();
    s.fault = Some(TestFault::AfterCommit);
    let err = s
        .block_control_binding(ACTIVITY, test_credential(4))
        .unwrap_err();
    assert_eq!(err.code, Code::OutcomeUnknown);
    let out = step(&mut s, &continuation, 1001, |_, _| {
        panic!("quarantined owner cannot write")
    });
    assert_eq!(out.result.unwrap_err().code, Code::OutcomeUnknown);
    assert_eq!(out.close, Some(channel(3)));
    assert!(s.next_outbound_handoff().is_none());
    drop(s);

    let mut s = w.reopen(1001);
    let mut cycle = s.start_outbound_cycle().unwrap();
    // Reopen resets the shared bucket to empty. Give the new round one frame of refill.
    round(&mut s, &mut cycle, 1251, vec![ack()]).unwrap();
    let out = step(&mut s, &continuation, 1251, |_, _| {
        panic!("old owner cannot write")
    });
    assert_eq!(out.result.unwrap_err().code, Code::Conflict);
    let next = s.next_outbound_handoff().unwrap();
    assert!(matches!(
        next.responsibility,
        OutboundResponsibility::DataAck(..)
    ));
}

#[test]
fn utc_and_activity_cutoffs_apply_before_writing() {
    for utc in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        if !utc {
            s.shorten_control_activity(ACTIVITY, 1001).unwrap();
        }
        let mut cycle = s.start_outbound_cycle().unwrap();
        round(&mut s, &mut cycle, 1000, vec![]).unwrap();
        let request = s.next_outbound_handoff().unwrap();
        let mut sample = clock(1001);
        if utc {
            sample.trusted_utc = Some(crate::data::UtcInterval {
                lower_ms: 109999,
                upper_ms: 110000,
            });
        }
        let out = s.advance_outbound_handoff(
            &request,
            OutboundHandoffInput {
                clock: sample,
                channel: Some(channel(3)),
                frame: DATA,
            },
            |_, _| panic!("a deadline reached before the write"),
        );
        assert_eq!(out.result.unwrap_err().code, Code::Expired);
        assert!(out.close.is_none());
    }
}
