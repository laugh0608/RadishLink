use super::outbound_tests::{add_control, batch, object, prepare_receipt};
use super::tests::{ACTIVITY, PEER_2, PEER_3, Workspace, clock, relay, test_credential};
use super::*;
use crate::retry::{Admission, LinkEvent, Reason, Signal};

pub(super) fn input(s: &Store, now: i64, acknowledgements: Vec<OutboundAck>) -> OutboundCycleInput {
    OutboundCycleInput {
        clock: clock(now),
        expected_revision: s.revision().unwrap(),
        acknowledgements,
    }
}
pub(super) fn data(s: &mut Store, count: usize) {
    for n in 0..count {
        let key = format!("q{n:03}");
        s.receive(relay(&key)).unwrap();
        s.schedule_forward(&key, PEER_3).unwrap();
    }
}
pub(super) fn keys(report: &OutboundCycleReport) -> Vec<String> {
    report
        .outbound
        .decisions
        .iter()
        .filter_map(|d| match d {
            OutboundDecision::Queue(k, _) if k.kind == QueueKind::Data => Some(k.message.clone()),
            _ => None,
        })
        .collect()
}
pub(super) fn ack() -> OutboundAck {
    OutboundAck::Data {
        message: "q000".into(),
        neighbor: PEER_2.into(),
    }
}
pub(super) fn ack_budget(s: &Store) -> String {
    s.conn
        .query_row(
            "SELECT data_ack_budget FROM messages WHERE key='q000'",
            [],
            |r| r.get(0),
        )
        .unwrap()
}

#[test]
fn bounded_steps_visit_data_tail_without_control_work_starving_it() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 130);
    for n in 0..33 {
        prepare_receipt(&mut s, &format!("r{n:03}"), 100);
    }
    let mut cycle = s.start_outbound_cycle().unwrap();
    let mut visited = Vec::new();
    let mut ordinary = Vec::new();
    for n in 0..9 {
        let now = 1000 + n;
        let i = input(&s, now, vec![]);
        let r = s
            .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(now)))
            .unwrap();
        assert!(r.data_candidates <= 16 && r.ordinary_candidates <= 16);
        assert!(r.outbound.decisions.len() <= 128);
        visited.extend(keys(&r));
        ordinary.extend(r.outbound.decisions.iter().filter_map(|d| match d {
            OutboundDecision::Queue(k, _) if k.kind == QueueKind::Evidence => {
                Some(k.message.clone())
            }
            _ => None,
        }));
        assert_eq!(r.data_complete, n == 8);
    }
    assert_eq!(
        visited,
        (0..130).map(|n| format!("q{n:03}")).collect::<Vec<_>>()
    );
    for n in 0..33 {
        assert!(ordinary.contains(&format!("r{n:03}")));
    }
    assert_eq!(s.schema_version().unwrap(), 9);
}

#[test]
fn mixed_cycle_prioritizes_all_exits_and_keeps_data_outside_control_tokens() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    prepare_receipt(&mut s, "r0", 100);
    prepare_receipt(&mut s, "r1", 100);
    add_control(&mut s, 3, 5, 10);
    add_control(&mut s, 4, 4, 20);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let i = input(
        &s,
        1000,
        vec![
            ack(),
            OutboundAck::Control {
                object: [10; 32],
                neighbor: [2; 16],
            },
        ],
    );
    let r = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
        .unwrap();
    assert_eq!(
        (
            r.exit_candidates,
            r.ordinary_candidates,
            r.data_candidates,
            r.ack_inputs
        ),
        (1, 3, 1, 2)
    );
    assert!(matches!(
        &r.outbound.decisions[0],
        OutboundDecision::Control(d) if d.object==[20;32] && d.send
    ));
    let controls =
        r.outbound
            .decisions
            .iter()
            .filter(|d| match d {
                OutboundDecision::Queue(k, d) => k.kind == QueueKind::Evidence && d.send,
                OutboundDecision::Control(d) => d.send,
                OutboundDecision::DataAck { send, .. }
                | OutboundDecision::ControlAck { send, .. } => *send,
            })
            .count();
    assert_eq!(controls, 4);
    assert!(
        r.outbound
            .decisions
            .iter()
            .any(|d| matches!(d,OutboundDecision::Queue(k,d) if k.kind==QueueKind::Data && d.send))
    );
}

#[test]
fn ack_input_is_bounded_explicit_and_deduplicated_by_the_original_batch() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let revision = s.revision().unwrap();
    let i = input(&s, 1000, (0..17).map(|_| ack()).collect());
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!(
            "oversized input must reject before observation"
        ))
        .err()
        .unwrap()
        .code,
        Code::InvalidInput
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(ack_budget(&s), "[]");
    let i = input(&s, 1000, (0..16).map(|_| ack()).collect());
    let r = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
        .unwrap();
    assert_eq!(r.ack_inputs, 16);
    assert_eq!(
        r.outbound
            .decisions
            .iter()
            .filter(|d| matches!(d, OutboundDecision::DataAck { send: true, .. }))
            .count(),
        1
    );
    let slots: serde_json::Value = serde_json::from_str(&ack_budget(&s)).unwrap();
    assert_eq!(slots[0]["attempts"], 1);
}

#[test]
fn revision_coordinate_and_observation_cutoffs_reject_without_advancing_position() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 17);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let mut i = input(&s, 250, vec![]);
    i.expected_revision -= 1;
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("stale cutoff"))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    let revision = s.revision().unwrap();
    let i = input(&s, 250, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| Ok(batch(251)))
            .err()
            .unwrap()
            .code,
        Code::InvalidInput
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(s.current_clock().monotonic_ms, 0);
    let i = input(&s, 250, vec![]);
    let first = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(250)))
        .unwrap();
    assert_eq!(
        keys(&first),
        (0..16).map(|n| format!("q{n:03}")).collect::<Vec<_>>()
    );
    let i = input(&s, 250, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!(
            "late input cannot reopen a coordinate"
        ))
        .err()
        .unwrap()
        .code,
        Code::Conflict
    );
    let i = input(&s, 251, vec![]);
    let second = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(251)))
        .unwrap();
    assert_eq!(keys(&second), vec!["q016"]);
}

#[test]
fn preparation_and_write_failures_preserve_all_positions_and_original_errors() {
    for phase in ["read", "observe", "write"] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 17);
        let mut cycle = s.start_outbound_cycle().unwrap();
        let revision = s.revision().unwrap();
        if phase == "read" {
            s.conn
                .execute_batch("CREATE TEMP VIEW queues AS SELECT * FROM missing_cycle_source;")
                .unwrap();
        }
        if phase == "write" {
            s.conn.execute_batch("CREATE TRIGGER fail_cycle BEFORE UPDATE ON queues BEGIN SELECT RAISE(FAIL,'synthetic cycle write'); END;").unwrap();
        }
        let i = input(&s, 250, vec![]);
        let err = s
            .process_outbound_cycle(&mut cycle, i, |c| {
                if phase == "observe"
                    && matches!(c,OutboundCandidate::Queue(k) if k.message=="q008")
                {
                    return Err(Error::new(Code::Busy, "synthetic observation unavailable"));
                }
                Ok(batch(250))
            })
            .err()
            .unwrap();
        assert_eq!(
            err.code,
            if phase == "observe" {
                Code::Busy
            } else {
                Code::StoreUnavailable
            }
        );
        assert_eq!(s.revision().unwrap(), revision);
        if phase == "read" {
            s.conn.execute_batch("DROP VIEW temp.queues;").unwrap();
        }
        if phase == "write" {
            s.conn.execute_batch("DROP TRIGGER fail_cycle;").unwrap();
        }
        let i = input(&s, 250, vec![]);
        let r = s
            .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(250)))
            .unwrap();
        assert_eq!(
            keys(&r),
            (0..16).map(|n| format!("q{n:03}")).collect::<Vec<_>>()
        );
        assert!(
            r.outbound
                .decisions
                .iter()
                .all(|d| matches!(d,OutboundDecision::Queue(_,d) if d.send))
        );
    }
}

#[test]
fn verified_exit_between_steps_is_committed_before_the_next_cycle() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 17);
    for n in 0..5 {
        prepare_receipt(&mut s, &format!("r{n}"), 100);
    }
    let mut cycle = s.start_outbound_cycle().unwrap();
    let i = input(&s, 1000, vec![]);
    s.process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
        .unwrap();
    let object = object(4, 4, 20);
    assert_eq!(
        s.queue_control_candidate(ACTIVITY, test_credential(2), &object.cose)
            .unwrap(),
        ControlIngressAdmission::Queued
    );
    let job = s.next_control_verification().unwrap().job.unwrap();
    s.complete_control_verification(
        job,
        ControlVerificationOutcome::Verified(Box::new(object)),
        &[ControlNeighbor {
            participant: [2; 16],
            link: Link::Up,
        }],
    )
    .unwrap();
    let i = input(&s, 2000, vec![]);
    let r = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(2000)))
        .unwrap();
    assert_eq!(r.exit_candidates, 1);
    assert!(matches!(
        &r.outbound.decisions[0],
        OutboundDecision::Control(d) if d.object==[20;32] && d.send
    ));
    assert_eq!(keys(&r), vec!["q016"]);
}

#[test]
fn deadline_cleanup_and_local_stop_never_reuse_old_decisions() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 17);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let i = input(&s, 10000, vec![]);
    let r = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(10000)))
        .unwrap();
    assert!(
        r.outbound.decisions.iter().all(
            |d| matches!(d,OutboundDecision::Queue(_,d) if !d.send && d.reason==Reason::Expired)
        )
    );
    assert_eq!(r.outbound.maintenance.expired_payloads, 17);
    s.stop_control_activity(ACTIVITY).unwrap();
    let revision = s.revision().unwrap();
    let i = input(&s, 10001, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("stopped activity"))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert_eq!(s.revision().unwrap(), revision);
}

#[test]
fn empty_step_uses_original_maintenance_and_observations_keep_stop_precedence() {
    let w = Workspace::new();
    let mut s = w.create();
    let mut cycle = s.start_outbound_cycle().unwrap();
    let revision = s.revision().unwrap();
    let i = input(&s, 250, vec![]);
    let r = s
        .process_outbound_cycle(&mut cycle, i, |_| {
            panic!("empty candidates have no default observations")
        })
        .unwrap();
    assert!(r.outbound.decisions.is_empty() && r.data_complete && r.ordinary_complete);
    assert_eq!(s.current_clock().monotonic_ms, 250);
    assert_eq!(s.revision().unwrap(), revision + 1);
    data(&mut s, 1);
    let merged = Batch {
        signal: Signal::Pause,
        ..batch(1000)
    }
    .merge(Batch {
        signal: Signal::Stop,
        link: LinkEvent::Down,
        admission: Admission::Quota,
        ..batch(1000)
    })
    .unwrap();
    let i = input(&s, 1000, vec![]);
    let r = s
        .process_outbound_cycle(&mut cycle, i, |_| Ok(merged))
        .unwrap();
    assert!(matches!(
        r.outbound.decisions[0],
        OutboundDecision::Queue(
            _,
            Decision {
                reason: Reason::Stopped,
                send: false,
                ..
            }
        )
    ));
    assert!(!s.message("q000").unwrap().unwrap().custody_observed);
    assert_eq!(ack_budget(&s), "[]");
}

#[test]
fn cycle_positions_reject_other_owners_same_boot_activity_switches_and_new_domains() {
    use super::clock_domain_tests::{isolation, new_clock, next};
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let mut cycle = s.start_outbound_cycle().unwrap();
    let other = Workspace::new();
    let mut other_store = other.create();
    let i = input(&other_store, 250, vec![]);
    assert_eq!(
        other_store
            .process_outbound_cycle(&mut cycle, i, |_| panic!("wrong owner"))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    s.stop_control_activity(ACTIVITY).unwrap();
    let p = s.preflight_activity_switch().unwrap();
    s.switch_control_activity(ActivitySwitch {
        previous_activity: ACTIVITY,
        expected_policy_revision: p.previous.policy_revision,
        activity: [9; 32],
        local_participant: [9; 16],
        deadline_ms: 10000,
    })
    .unwrap();
    let i = input(&s, 250, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("wrong activity"))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    drop(s);
    let mut s = w.reopen(1);
    let i = input(&s, 250, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("reopened owner"))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    let mut cycle = s.start_outbound_cycle().unwrap();
    drop(s);
    let c = new_clock("boot-b", 0, 200000);
    let mut s = Store::open(&w.dir, Limits::default(), c.clone()).unwrap();
    let i = OutboundCycleInput {
        clock: c.clone(),
        expected_revision: s.revision().unwrap(),
        acknowledgements: vec![],
    };
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("cold quarantine"))
            .err()
            .unwrap()
            .code,
        Code::TimeUncertain
    );
    let r = isolation(&s, "cycle-isolate");
    s.isolate_clock_domain(r).unwrap();
    let r = next(&s, 2);
    s.establish_clock_domain(r).unwrap();
    let i = OutboundCycleInput {
        clock: c,
        expected_revision: s.revision().unwrap(),
        acknowledgements: vec![],
    };
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("old domain"))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    assert!(s.message("q000").unwrap().unwrap().payload_present);
}

#[test]
fn oversized_exit_source_is_rejected_instead_of_truncated_before_ordinary_work() {
    let w = Workspace::new();
    let mut s = w.create();
    add_control(&mut s, 4, 4, 20);
    let mut cycle = s.start_outbound_cycle().unwrap();
    // A corrupt query source, not a claim that 81 exit responsibilities are valid D16 state.
    s.conn.execute_batch("CREATE TEMP VIEW control_neighbors AS WITH RECURSIVE copies(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM copies WHERE x<81) SELECT n.* FROM main.control_neighbors n CROSS JOIN copies;").unwrap();
    let revision = s.revision().unwrap();
    let i = input(&s, 1000, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| panic!("incomplete exit set"))
            .err()
            .unwrap()
            .code,
        Code::StoreCorrupt
    );
    assert_eq!(s.revision().unwrap(), revision);
    s.conn
        .execute_batch("DROP VIEW temp.control_neighbors;")
        .unwrap();
    let i = input(&s, 1000, vec![]);
    assert_eq!(
        s.process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
            .unwrap()
            .exit_candidates,
        1
    );
}
