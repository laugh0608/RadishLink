use super::clock_domain_tests::{isolation, new_clock, next};
use super::outbound_tests::{add_control, batch, prepare_receipt};
use super::tests::{ACTIVITY, PEER_3, Workspace, clock, relay};
use super::*;
use crate::retry::{Admission, LinkEvent, Signal};

#[test]
fn multiple_pages_reach_tail_and_feed_the_existing_atomic_dispatcher() {
    let w = Workspace::new();
    let mut s = w.create();
    for n in 0..130 {
        let key = format!("q{n:03}");
        s.receive(relay(&key)).unwrap();
        s.schedule_forward(&key, PEER_3).unwrap();
    }
    let revision = s.revision().unwrap();
    let mut scan = s.start_outbound_scan(OutboundLane::Data).unwrap();
    let first = s.scan_outbound_page(&mut scan).unwrap();
    assert_eq!(first.candidates.len(), 128);
    assert!(!first.complete);
    assert_eq!(first.revision, revision);
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(s.current_clock().monotonic_ms, 0);
    s.receive(relay("a-new")).unwrap();
    s.schedule_forward("a-new", PEER_3).unwrap(); // behind the current keyset position
    let mut keys = Vec::new();
    let mut sends = 0;
    let mut page = first;
    loop {
        let complete = page.complete;
        let events = page
            .candidates
            .into_iter()
            .map(|c| {
                let OutboundCandidate::Queue(queue) = c else {
                    panic!("data scan returned a control object")
                };
                keys.push(queue.message.clone());
                QueueEvent {
                    queue,
                    batch: batch(250),
                }
            })
            .collect();
        sends += s
            .process_queue_batch(clock(250), events)
            .unwrap()
            .decisions
            .iter()
            .filter(|(_, d)| d.send)
            .count();
        if complete {
            break;
        }
        // Dispatch changes the revision; the position is a traversal fact, not an old permit.
        page = s.scan_outbound_page(&mut scan).unwrap();
        assert_eq!(page.candidates.len(), 2);
        assert!(page.revision > revision);
    }
    assert_eq!(
        keys,
        (0..130).map(|n| format!("q{n:03}")).collect::<Vec<_>>()
    );
    assert_eq!(sends, 130);
    assert_eq!(
        s.scan_outbound_page(&mut scan).err().unwrap().code,
        Code::Conflict
    );
    let mut next = s.start_outbound_scan(OutboundLane::Data).unwrap();
    let page = s.scan_outbound_page(&mut next).unwrap();
    assert!(matches!(&page.candidates[0], OutboundCandidate::Queue(q) if q.message=="a-new"));
}

#[test]
fn lanes_keep_exits_receipts_reports_and_data_distinct_without_inventing_acks() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("data")).unwrap();
    s.schedule_forward("data", PEER_3).unwrap();
    prepare_receipt(&mut s, "a", 100);
    prepare_receipt(&mut s, "b", 100);
    add_control(&mut s, 3, 5, 0); // all-zero object ID is legal, not a pagination sentinel
    add_control(&mut s, 2, 3, 10);
    add_control(&mut s, 4, 4, 20);
    let revision = s.revision().unwrap();
    let rate: (i64, i64) = s
        .conn
        .query_row("SELECT frames,bytes FROM control_output_rate", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .unwrap();
    for (lane, expected) in [
        (
            OutboundLane::Exit,
            vec![OutboundCandidate::Control {
                object: [20; 32],
                neighbor: [2; 16],
            }],
        ),
        (
            OutboundLane::OrdinaryControl,
            vec![
                OutboundCandidate::Queue(QueueKey {
                    message: "a".into(),
                    kind: QueueKind::Evidence,
                    neighbor: super::tests::PEER_2.into(),
                }),
                OutboundCandidate::Queue(QueueKey {
                    message: "b".into(),
                    kind: QueueKind::Evidence,
                    neighbor: super::tests::PEER_2.into(),
                }),
                OutboundCandidate::Control {
                    object: [0; 32],
                    neighbor: [2; 16],
                },
                OutboundCandidate::Control {
                    object: [10; 32],
                    neighbor: [2; 16],
                },
            ],
        ),
    ] {
        let mut scan = s.start_outbound_scan(lane).unwrap();
        let page = s.scan_outbound_page(&mut scan).unwrap();
        assert_eq!(page.candidates, expected);
        assert!(page.complete);
        assert_eq!(page.domain, INITIAL_CLOCK_DOMAIN);
        assert_eq!(page.activity, ACTIVITY);
        assert_eq!(page.lane, lane);
    }
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(
        s.conn
            .query_row("SELECT frames,bytes FROM control_output_rate", [], |r| Ok(
                (r.get(0)?, r.get(1)?)
            ))
            .unwrap(),
        rate
    );
    assert_eq!(s.schema_version().unwrap(), SCHEMA_VERSION);
}

#[test]
fn owner_change_and_other_store_cannot_reuse_a_position() {
    let w = Workspace::new();
    let s = w.create();
    let mut scan = s.start_outbound_scan(OutboundLane::Data).unwrap();
    let other = Workspace::new();
    let other_store = other.create();
    assert_eq!(
        other_store
            .scan_outbound_page(&mut scan)
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    drop(s);
    let mut s = w.reopen(1);
    assert_eq!(
        s.scan_outbound_page(&mut scan).err().unwrap().code,
        Code::Conflict
    );
    s.receive(relay("old")).unwrap();
    s.schedule_forward("old", PEER_3).unwrap();
    let mut same_boot = s.start_outbound_scan(OutboundLane::Data).unwrap();
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
    assert_eq!(
        s.scan_outbound_page(&mut same_boot).err().unwrap().code,
        Code::Conflict
    );
    let mut current = s.start_outbound_scan(OutboundLane::Data).unwrap();
    assert!(
        s.scan_outbound_page(&mut current)
            .unwrap()
            .candidates
            .is_empty()
    );
    assert!(s.message("old").unwrap().unwrap().payload_present);
}

#[test]
fn domain_switch_rejects_old_position_and_excludes_frozen_responsibilities() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("old")).unwrap();
    s.schedule_forward("old", PEER_3).unwrap();
    let mut old_scan = s.start_outbound_scan(OutboundLane::Data).unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    assert_eq!(
        s.scan_outbound_page(&mut old_scan).err().unwrap().code,
        Code::TimeUncertain
    );
    let r = isolation(&s, "scan-isolation");
    s.isolate_clock_domain(r).unwrap();
    assert_eq!(
        s.start_outbound_scan(OutboundLane::Data)
            .err()
            .unwrap()
            .code,
        Code::TimeUncertain
    );
    let r = next(&s, 2);
    s.establish_clock_domain(r).unwrap();
    assert_eq!(
        s.scan_outbound_page(&mut old_scan).err().unwrap().code,
        Code::Conflict
    );
    let mut scan = s.start_outbound_scan(OutboundLane::Data).unwrap();
    let page = s.scan_outbound_page(&mut scan).unwrap();
    assert!(page.complete && page.candidates.is_empty());
    assert!(s.message("old").unwrap().unwrap().payload_present);
}

#[test]
fn discovered_reference_cannot_bypass_a_later_policy_change() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("data")).unwrap();
    s.schedule_forward("data", PEER_3).unwrap();
    let mut scan = s.start_outbound_scan(OutboundLane::Data).unwrap();
    let page = s.scan_outbound_page(&mut scan).unwrap();
    assert_eq!(page.candidates.len(), 1);
    s.stop_control_activity(ACTIVITY).unwrap();
    let OutboundCandidate::Queue(queue) = page.candidates.into_iter().next().unwrap() else {
        panic!("queue expected")
    };
    let revision = s.revision().unwrap();
    assert_eq!(
        s.process_queue_batch(
            clock(250),
            vec![QueueEvent {
                queue,
                batch: batch(250)
            }]
        )
        .err()
        .unwrap()
        .code,
        Code::Conflict
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(
        s.scan_outbound_page(&mut scan).err().unwrap().code,
        Code::Conflict
    );
}

#[test]
fn empty_lanes_and_terminal_control_are_explicit_and_read_only() {
    let w = Workspace::new();
    let mut s = w.create();
    for lane in [
        OutboundLane::Exit,
        OutboundLane::OrdinaryControl,
        OutboundLane::Data,
    ] {
        let mut scan = s.start_outbound_scan(lane).unwrap();
        let page = s.scan_outbound_page(&mut scan).unwrap();
        assert!(page.complete && page.candidates.is_empty());
    }
    add_control(&mut s, 3, 5, 10);
    s.process_control_batch(
        ACTIVITY,
        clock(1),
        vec![ControlEvent {
            object: [10; 32],
            neighbor: [2; 16],
            link: LinkEvent::Unchanged,
            signal: Signal::Stop,
            admission: Admission::Allow,
        }],
    )
    .unwrap();
    let revision = s.revision().unwrap();
    let mut scan = s
        .start_outbound_scan(OutboundLane::OrdinaryControl)
        .unwrap();
    assert!(
        s.scan_outbound_page(&mut scan)
            .unwrap()
            .candidates
            .is_empty()
    );
    assert_eq!(s.revision().unwrap(), revision);
}

#[test]
fn full_receipt_page_continues_into_report_keys_including_zero_id() {
    let w = Workspace::new();
    let mut s = w.create();
    for n in 0..128 {
        prepare_receipt(&mut s, &format!("r{n:03}"), 100);
    }
    add_control(&mut s, 3, 5, 0);
    let revision = s.revision().unwrap();
    let mut scan = s
        .start_outbound_scan(OutboundLane::OrdinaryControl)
        .unwrap();
    let first = s.scan_outbound_page(&mut scan).unwrap();
    assert_eq!(first.candidates.len(), 128);
    assert!(!first.complete);
    assert!(
        first
            .candidates
            .iter()
            .all(|c| matches!(c, OutboundCandidate::Queue(_)))
    );
    let second = s.scan_outbound_page(&mut scan).unwrap();
    assert_eq!(
        second.candidates,
        vec![OutboundCandidate::Control {
            object: [0; 32],
            neighbor: [2; 16]
        }]
    );
    assert!(second.complete);
    assert_eq!(s.revision().unwrap(), revision);
}

#[test]
fn partial_read_failure_preserves_position_without_skipping_prior_rows() {
    let w = Workspace::new();
    let mut s = w.create();
    prepare_receipt(&mut s, "b", 100);
    add_control(&mut s, 3, 5, 10);
    let mut scan = s
        .start_outbound_scan(OutboundLane::OrdinaryControl)
        .unwrap();
    s.conn
        .execute_batch("CREATE TEMP VIEW control_neighbors AS SELECT * FROM missing_scan_source;")
        .unwrap();
    assert_eq!(
        s.scan_outbound_page(&mut scan).err().unwrap().code,
        Code::StoreUnavailable
    );
    s.conn
        .execute_batch("DROP VIEW temp.control_neighbors;")
        .unwrap();
    let page = s.scan_outbound_page(&mut scan).unwrap();
    assert_eq!(page.candidates.len(), 2); // the receipt read before the failure was not skipped
    assert!(page.complete);
}
