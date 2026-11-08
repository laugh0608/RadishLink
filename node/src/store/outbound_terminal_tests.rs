use super::outbound_cycle_tests::{data, input};
use super::outbound_tests::{add_control, batch};
use super::tests::{ACTIVITY, PEER_3, Workspace, binding, clock, test_credential};
use super::*;
use crate::retry::{Admission, LinkEvent, Reason, Signal};

fn register(s: &mut Store, peer: u8) -> ControlIngressChannel {
    s.register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(peer))
        .unwrap()
}

fn data_ack() -> OutboundTerminalAck {
    OutboundTerminalAck::Data {
        message: "q000".into(),
        binding: binding("q000").try_into().unwrap(),
    }
}

fn round(
    s: &mut Store,
    cycle: &mut OutboundCycle,
    now: i64,
    channel: OutboundChannel,
    link: LinkEvent,
) -> Result<OutboundCycleReport> {
    s.process_outbound_cycle_with_handoff(
        cycle,
        input(s, now, vec![]),
        |_| Ok(Batch { link, ..batch(now) }),
        |_| Some(channel),
    )
}

fn data_write(
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
            frame: OutboundFrame::Data {
                bytes: 64,
                remaining_ms: 500,
                hops: 0,
            },
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
fn late_custody_withdraws_partial_at_same_coordinate_then_commits_after_close() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let channel = register(&mut s, 3);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(
        &mut s,
        &mut cycle,
        1000,
        channel.binding(),
        LinkEvent::Unchanged,
    )
    .unwrap();
    assert_eq!(
        s.observe_custody("q000", PEER_3).unwrap_err().code,
        Code::Conflict
    );
    let first = s.next_outbound_handoff().unwrap();
    assert_eq!(
        data_write(&mut s, &first, 1000, |_, _| OutboundWrite::Written(8))
            .result
            .unwrap(),
        OutboundWriteProgress::Partial(8)
    );
    let continuation = s.next_outbound_handoff().unwrap();
    let revision = s.revision().unwrap();
    let charged = bucket(&s);
    assert_eq!(
        s.accept_outbound_terminal(&channel, data_ack(), clock(1000))
            .unwrap(),
        OutboundTerminalAdmission::Accepted {
            close: Some(channel.binding())
        }
    );
    assert!(s.next_outbound_handoff().is_none());
    let out = data_write(&mut s, &continuation, 1000, |_, _| {
        panic!("late custody must stop continuation")
    });
    assert_eq!(out.result.unwrap_err().code, Code::Conflict);
    assert_eq!(
        s.commit_outbound_terminal(clock(1000)).unwrap_err().code,
        Code::Busy
    );
    assert_eq!(
        round(
            &mut s,
            &mut cycle,
            1001,
            channel.binding(),
            LinkEvent::Unchanged
        )
        .err()
        .unwrap()
        .code,
        Code::Busy
    );
    assert_eq!(
        s.advance_queue("q000", "data", PEER_3, batch(1000))
            .unwrap_err()
            .code,
        Code::Busy
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert!(!s.message("q000").unwrap().unwrap().custody_observed);

    s.close_control_ingress_channel(&channel).unwrap();
    let replacement = register(&mut s, 3);
    s.commit_outbound_terminal(clock(1001)).unwrap();
    assert_eq!(s.revision().unwrap(), revision + 1);
    assert_eq!(bucket(&s), charged);
    let view = s.message("q000").unwrap().unwrap();
    assert!(view.custody_observed && view.payload_present);
    assert_eq!(view.state, "stored");
    assert_eq!(
        s.accept_outbound_terminal(&replacement, data_ack(), clock(1001))
            .unwrap(),
        OutboundTerminalAdmission::AlreadyTerminal
    );
    let report = round(
        &mut s,
        &mut cycle,
        1002,
        replacement.binding(),
        LinkEvent::Unchanged,
    )
    .unwrap();
    assert!(
        matches!(&report.outbound.decisions[0], OutboundDecision::Queue(_, decision) if !decision.send && decision.reason == Reason::Paused)
    );
}

#[test]
fn control_ack_persists_pause_for_final_attempt_despite_old_batch_busy() {
    let w = Workspace::new();
    let mut s = w.create();
    add_control(&mut s, 4, 5, 10);
    let channel = register(&mut s, 2);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let pause = ControlEvent {
        object: [10; 32],
        neighbor: [2; 16],
        link: LinkEvent::Unchanged,
        signal: Signal::Pause,
        admission: Admission::Allow,
    };
    for (now, link) in [
        (1800001, LinkEvent::Down),
        (1801000, LinkEvent::Up),
        (1801001, LinkEvent::Down),
    ] {
        s.process_control_batch(
            ACTIVITY,
            clock(now),
            vec![ControlEvent {
                link,
                signal: Signal::Continue,
                ..pause
            }],
        )
        .unwrap();
    }
    let now = 1861000;
    let report = round(&mut s, &mut cycle, now, channel.binding(), LinkEvent::Up).unwrap();
    assert!(
        matches!(&report.outbound.decisions[0], OutboundDecision::Control(d) if d.send && d.progress.terminal)
    );
    let request = s.next_outbound_handoff().unwrap();
    assert_eq!(
        s.process_control_batch(ACTIVITY, clock(now), vec![pause])
            .err()
            .unwrap()
            .code,
        Code::Busy
    );
    let charged = bucket(&s);
    let counters = s.control_progress([10; 32], [2; 16]).unwrap().unwrap();
    assert_eq!(
        s.accept_outbound_terminal(
            &channel,
            OutboundTerminalAck::Control { object: [10; 32] },
            clock(now)
        )
        .unwrap(),
        OutboundTerminalAdmission::Accepted { close: None }
    );
    assert_eq!(
        s.commit_outbound_terminal(clock(now)).unwrap_err().code,
        Code::Busy
    );
    let out = s.advance_outbound_handoff(
        &request,
        OutboundHandoffInput {
            clock: clock(now),
            channel: Some(channel.binding()),
            frame: OutboundFrame::Control { bytes: 32 },
        },
        |_, _| panic!("accepted terminal must withdraw the last attempt"),
    );
    assert_eq!(out.result.unwrap_err().code, Code::Conflict);
    s.commit_outbound_terminal(clock(now + 1)).unwrap();
    assert_eq!(
        s.control_progress([10; 32], [2; 16]).unwrap().unwrap(),
        counters
    );
    assert_eq!(bucket(&s), charged);
    let event: String = s
        .conn
        .query_row(
            "SELECT last_event FROM current_control_neighbors",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Batch>(&event).unwrap().signal,
        Signal::Pause
    );
    assert!(
        round(
            &mut s,
            &mut cycle,
            now + 2,
            channel.binding(),
            LinkEvent::Unchanged
        )
        .unwrap()
        .outbound
        .decisions
        .is_empty()
    );
}

#[test]
fn invalid_reference_or_stale_instance_does_not_withdraw_or_charge() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let old = register(&mut s, 3);
    s.close_control_ingress_channel(&old).unwrap();
    let channel = register(&mut s, 3);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(
        &mut s,
        &mut cycle,
        1000,
        channel.binding(),
        LinkEvent::Unchanged,
    )
    .unwrap();
    let revision = s.revision().unwrap();
    for (source, ack) in [
        (&old, data_ack()),
        (
            &channel,
            OutboundTerminalAck::Data {
                message: "q000".into(),
                binding: [7; 32],
            },
        ),
        (&channel, OutboundTerminalAck::Control { object: [9; 32] }),
    ] {
        assert_eq!(
            s.accept_outbound_terminal(source, ack, clock(1000))
                .unwrap_err()
                .code,
            Code::Conflict
        );
    }
    assert_eq!(s.revision().unwrap(), revision);
    let request = s.next_outbound_handoff().unwrap();
    assert_eq!(
        data_write(&mut s, &request, 1000, |_, left| OutboundWrite::Written(
            left
        ))
        .result
        .unwrap(),
        OutboundWriteProgress::Complete
    );
}

#[test]
fn failed_and_unknown_terminal_commits_keep_fence_and_reopen_only_durable_result() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        let channel = register(&mut s, 3);
        let mut cycle = s.start_outbound_cycle().unwrap();
        round(
            &mut s,
            &mut cycle,
            1000,
            channel.binding(),
            LinkEvent::Unchanged,
        )
        .unwrap();
        s.accept_outbound_terminal(&channel, data_ack(), clock(1000))
            .unwrap();
        assert_eq!(
            s.accept_outbound_terminal(&channel, data_ack(), clock(1000))
                .unwrap_err()
                .code,
            Code::Busy
        );
        let next = input(&s, 1002, vec![]);
        s.fault = Some(fault);
        let unknown = fault == TestFault::AfterCommit;
        let err = s.commit_outbound_terminal(clock(1001)).unwrap_err();
        assert_eq!(
            err.code,
            if unknown {
                Code::OutcomeUnknown
            } else {
                Code::StoreUnavailable
            }
        );
        assert!(s.next_outbound_handoff().is_none());
        assert_eq!(
            s.process_outbound_cycle(&mut cycle, next, |_| panic!("no scheduling while fenced"))
                .err()
                .unwrap()
                .code,
            if unknown {
                Code::OutcomeUnknown
            } else {
                Code::Busy
            }
        );
        if !unknown {
            assert!(!s.message("q000").unwrap().unwrap().custody_observed);
            s.fault = None;
            assert_eq!(
                s.commit_outbound_terminal(clock(1001)).unwrap_err().code,
                Code::Busy
            );
            s.commit_outbound_terminal(clock(1002)).unwrap();
        }
        drop(s);
        let mut s = w.reopen(1002);
        let view = s.message("q000").unwrap().unwrap();
        assert!(view.custody_observed && view.payload_present);
        assert_eq!(
            s.commit_outbound_terminal(clock(1003)).unwrap_err().code,
            Code::Conflict
        );
    }
}

#[test]
fn accepted_terminal_rechecks_original_credential_after_policy_change() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let channel = register(&mut s, 3);
    let mut cycle = s.start_outbound_cycle().unwrap();
    round(
        &mut s,
        &mut cycle,
        1000,
        channel.binding(),
        LinkEvent::Unchanged,
    )
    .unwrap();
    s.accept_outbound_terminal(&channel, data_ack(), clock(1000))
        .unwrap();
    s.block_control_binding(ACTIVITY, test_credential(3))
        .unwrap();
    let revision = s.revision().unwrap();
    assert_eq!(
        s.commit_outbound_terminal(clock(1001)).unwrap_err().code,
        Code::Conflict
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert!(!s.message("q000").unwrap().unwrap().custody_observed);
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!(
        round(
            &mut s,
            &mut cycle,
            1002,
            channel.binding(),
            LinkEvent::Unchanged
        )
        .err()
        .unwrap()
        .code,
        Code::Busy
    );
}
