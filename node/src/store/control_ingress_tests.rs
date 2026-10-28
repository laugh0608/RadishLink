use super::tests::{ACTIVITY, Workspace, clock, relay, test_credential};
use super::*;
use ControlIngressAdmission as Admission;

fn verified(object: PreparedControl) -> ControlVerificationOutcome {
    ControlVerificationOutcome::Verified(Box::new(object))
}
fn queue(s: &mut Store, peer: u8, body: &[u8]) -> Result<Admission> {
    s.queue_control_candidate(ACTIVITY, test_credential(peer), body)
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
fn job(s: &mut Store) -> ControlVerificationJob {
    let p = s.next_control_verification().unwrap();
    assert!(p.discarded.is_empty());
    p.job.unwrap()
}
fn lease(s: &mut Store, peer: u8, body: &[u8]) -> ControlVerificationJob {
    assert_eq!(queue(s, peer, body).unwrap(), Admission::Queued);
    job(s)
}
fn fill(s: &mut Store) {
    for round in 1..=4 {
        s.advance_clock(clock(round * 1000)).unwrap();
        for peer in 2..=5 {
            let mut bytes = vec![peer; 512];
            bytes[0] = round as u8;
            assert_eq!(queue(s, peer, &bytes).unwrap(), Admission::Queued);
        }
    }
}
#[test]
fn empty_start_fractional_refill_per_peer_and_global_bursts_are_enforced() {
    let w = Workspace::new();
    let mut s = w.create();
    assert_eq!(queue(&mut s, 2, b"a").unwrap(), Admission::RateLimited);
    s.advance_clock(clock(999)).unwrap();
    assert_eq!(queue(&mut s, 2, b"a").unwrap(), Admission::RateLimited);
    s.advance_clock(clock(1000)).unwrap();
    for peer in 2..=5 {
        assert_eq!(queue(&mut s, peer, &[peer]).unwrap(), Admission::Queued);
    }
    assert_eq!(queue(&mut s, 2, b"again").unwrap(), Admission::RateLimited);
    let w2 = Workspace::new();
    let mut s = w2.create();
    s.advance_clock(clock(2000)).unwrap();
    for body in [b"a", b"b"] {
        assert_eq!(queue(&mut s, 2, body).unwrap(), Admission::Queued);
    }
    assert_eq!(queue(&mut s, 2, b"c").unwrap(), Admission::RateLimited);
    for body in [b"a", b"b"] {
        assert_eq!(queue(&mut s, 3, body).unwrap(), Admission::Queued);
    }
    assert_eq!(queue(&mut s, 4, b"c").unwrap(), Admission::RateLimited);
    s.advance_clock(clock(2249)).unwrap();
    assert_eq!(queue(&mut s, 4, b"c").unwrap(), Admission::RateLimited);
    s.advance_clock(clock(2250)).unwrap();
    assert_eq!(queue(&mut s, 4, b"c").unwrap(), Admission::Queued);
}
#[test]
fn all_sixteen_waiting_or_leased_objects_count_and_full_queue_does_not_refund() {
    let w = Workspace::new();
    let mut s = w.create();
    fill(&mut s);
    assert_eq!(
        s.control_ingress_usage(),
        ControlIngressUsage {
            waiting: 16,
            verifying: 0,
            object_bytes: 8192,
            peer_buckets: 4
        }
    );
    let mut jobs: Vec<_> = (0..16).map(|_| job(&mut s)).collect();
    assert!(s.next_control_verification().unwrap().job.is_none());
    assert_eq!(s.control_ingress_usage().verifying, 16);
    s.advance_clock(clock(5000)).unwrap();
    let revision = s.revision().unwrap();
    assert_eq!(queue(&mut s, 2, b"full").unwrap(), Admission::QueueFull);
    s.cancel_control_verification(jobs.pop().unwrap()).unwrap();
    assert_eq!(
        queue(&mut s, 2, b"no-refund").unwrap(),
        Admission::RateLimited
    );
    assert_eq!(s.revision().unwrap(), revision);
    s.advance_clock(clock(6000)).unwrap();
    assert_eq!(queue(&mut s, 2, b"later").unwrap(), Admission::Queued);
    assert_eq!(
        s.control_ingress_usage().waiting + s.control_ingress_usage().verifying,
        16
    );
    for job in jobs {
        s.cancel_control_verification(job).unwrap();
    }
}
#[test]
fn unknown_pending_local_and_wrong_activity_are_rejected_before_any_rate_slot() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
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
    for (activity, neighbor) in [
        ([9; 32], test_credential(2)),
        (ACTIVITY, test_credential(1)),
        (ACTIVITY, [9; 32]),
        (ACTIVITY, pending),
    ] {
        assert_eq!(
            s.queue_control_candidate(activity, neighbor, b"untrusted")
                .unwrap_err()
                .code,
            Code::Conflict
        );
    }
    assert_eq!(s.control_ingress_usage().peer_buckets, 0);
    assert_eq!(queue(&mut s, 2, b"valid").unwrap(), Admission::Queued);
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    assert_eq!(
        queue(&mut s, 2, b"blocked").unwrap_err().code,
        Code::Conflict
    );
    assert_eq!(s.control_ingress_usage().peer_buckets, 1);
}
#[test]
fn malformed_and_oversized_candidates_do_not_allocate_or_write_unverified_bytes() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
    let before = fs::read(w.dir.join("node.sqlite3")).unwrap();
    let revision = s.revision().unwrap();
    for bytes in [&[][..], &[7; 513][..]] {
        assert_eq!(
            queue(&mut s, 2, bytes).unwrap_err().code,
            Code::InvalidInput
        );
    }
    assert_eq!(s.control_ingress_usage().object_bytes, 0);
    assert_eq!(queue(&mut s, 2, &[7; 512]).unwrap(), Admission::Queued);
    assert_eq!(s.control_ingress_usage().object_bytes, 512);
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(fs::read(w.dir.join("node.sqlite3")).unwrap(), before);
    assert_eq!(s.control_usage().unwrap().objects, 0);
    assert_eq!(s.usage().unwrap().evidence_count, 0);
}
#[test]
fn duplicate_pending_and_verified_cache_still_consume_rate_and_do_not_spawn_work() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
    assert_eq!(queue(&mut s, 2, b"same").unwrap(), Admission::Queued);
    assert_eq!(
        queue(&mut s, 2, b"same").unwrap(),
        Admission::AlreadyPending
    );
    assert_eq!(queue(&mut s, 2, b"same").unwrap(), Admission::RateLimited);
    assert_eq!(queue(&mut s, 3, b"same").unwrap(), Admission::Queued);
    assert_eq!(s.control_ingress_usage().waiting, 2);
    s.accept_control(object(4, 3, 7), &[]).unwrap();
    s.advance_clock(clock(4000)).unwrap();
    let revision = s.revision().unwrap();
    assert_eq!(queue(&mut s, 2, &[7]).unwrap(), Admission::Known([7; 32]));
    assert_eq!(queue(&mut s, 2, &[7]).unwrap(), Admission::Known([7; 32]));
    assert_eq!(queue(&mut s, 2, &[7]).unwrap(), Admission::RateLimited);
    assert_eq!(queue(&mut s, 3, &[7, 0]).unwrap(), Admission::Queued);
    assert_eq!(s.control_usage().unwrap().objects, 1);
    assert_eq!(s.revision().unwrap(), revision);
    s.block_control_binding(ACTIVITY, test_credential(4))
        .unwrap();
    assert_eq!(queue(&mut s, 3, &[7]).unwrap_err().code, Code::Conflict);
}
#[test]
fn fifo_rejection_and_exact_completion_bind_original_bytes_and_activity() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
    queue(&mut s, 2, &[7]).unwrap();
    queue(&mut s, 2, &[8]).unwrap();
    let first = job(&mut s);
    assert_eq!(first.cose(), &[7]);
    assert_eq!(first.neighbor(), test_credential(2));
    assert_eq!(first.activity(), ACTIVITY);
    assert_eq!(first.policy_revision(), 5);
    assert_eq!(
        s.complete_control_verification(first, ControlVerificationOutcome::Rejected, &[])
            .unwrap(),
        ControlVerificationCompletion::Rejected
    );
    let second = job(&mut s);
    assert_eq!(second.cose(), &[8]);
    assert_eq!(
        s.complete_control_verification(second, verified(object(4, 3, 9)), &[])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    s.advance_clock(clock(3000)).unwrap();
    let pending = lease(&mut s, 2, &[7]);
    let mut different = object(4, 3, 7);
    different.fields.activity = [9; 32];
    assert_eq!(
        s.complete_control_verification(pending, verified(different), &[])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(s.control_ingress_usage().verifying, 0);
    assert_eq!(s.control_usage().unwrap().objects, 0);
}
#[test]
fn policy_changes_expiry_and_retiring_refuse_waiting_and_inflight_work() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
    let running = lease(&mut s, 2, &[7]);
    queue(&mut s, 3, &[8]).unwrap();
    s.block_control_binding(ACTIVITY, test_credential(5))
        .unwrap();
    let poll = s.next_control_verification().unwrap();
    assert!(poll.job.is_none());
    assert_eq!(poll.discarded.len(), 1);
    assert_eq!(poll.discarded[0].code, Code::Conflict);
    assert_eq!(s.control_ingress_usage().verifying, 1);
    assert_eq!(
        s.complete_control_verification(running, verified(object(4, 3, 7)), &[])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    s.advance_clock(clock(3000)).unwrap();
    queue(&mut s, 2, &[9]).unwrap();
    s.shorten_control_activity(ACTIVITY, 3100).unwrap();
    s.advance_clock(clock(3100)).unwrap();
    let poll = s.next_control_verification().unwrap();
    assert_eq!(poll.discarded[0].code, Code::Expired);
    assert!(poll.job.is_none());
    assert_eq!(queue(&mut s, 2, &[9]).unwrap_err().code, Code::Expired);
    let w2 = Workspace::new();
    let mut s = w2.create();
    s.advance_clock(clock(2000)).unwrap();
    s.begin_control_exit(object(1, 1, 9).fields).unwrap();
    assert_eq!(queue(&mut s, 2, &[7]).unwrap_err().code, Code::Conflict);
}
#[test]
fn owner_block_remains_available_at_full_queue_and_received_exit_stops_business_atomically() {
    let w = Workspace::new();
    let mut s = w.create();
    fill(&mut s);
    s.block_control_binding(ACTIVITY, test_credential(5))
        .unwrap();
    assert_eq!(s.control_ingress_usage().waiting, 16);
    assert_eq!(s.next_control_verification().unwrap().discarded.len(), 16);
    let w2 = Workspace::new();
    let mut s = w2.create();
    s.receive(relay("one")).unwrap();
    s.advance_clock(clock(1000)).unwrap();
    let pending = lease(&mut s, 4, &[7]);
    assert_eq!(
        s.complete_control_verification(
            pending,
            verified(object(2, 2, 7)),
            &[ControlNeighbor {
                participant: [3; 16],
                link: Link::Up
            }]
        )
        .unwrap(),
        ControlVerificationCompletion::Accepted(ControlAdmission::Inserted([7; 32]))
    );
    assert!(s.message("one").unwrap().unwrap().policy_stopped);
    assert_eq!(
        s.control_binding(&test_credential(2), &[2; 16]).unwrap(),
        BindingState::Blocked
    );
    assert_eq!(
        s.control_progress([7; 32], [3; 16])
            .unwrap()
            .unwrap()
            .ack_attempts,
        0
    );
    s.advance_clock(clock(2000)).unwrap();
    assert_eq!(queue(&mut s, 4, &[7]).unwrap(), Admission::Known([7; 32]));
}
#[test]
fn credential_replacement_does_not_refill_neighbor_bucket() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
    queue(&mut s, 2, b"a").unwrap();
    queue(&mut s, 2, b"b").unwrap();
    let mut next = test_credential(2);
    next[31] = 2;
    s.stage_control_binding(
        ACTIVITY,
        ControlBinding {
            participant: [2; 16],
            credential: next,
            generation: 2,
            body: vec![2, 2],
        },
    )
    .unwrap();
    s.activate_control_binding(ACTIVITY, next, &[2, 2]).unwrap();
    assert_eq!(
        s.queue_control_candidate(ACTIVITY, next, b"c").unwrap(),
        Admission::RateLimited
    );
    assert_eq!(s.control_ingress_usage().peer_buckets, 1);
    assert_eq!(s.next_control_verification().unwrap().discarded.len(), 2);
    s.advance_clock(clock(3000)).unwrap();
    assert_eq!(
        s.queue_control_candidate(ACTIVITY, next, b"c").unwrap(),
        Admission::Queued
    );
}
#[test]
fn reopen_starts_empty_and_foreign_job_cannot_match_reused_sequence() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(2000)).unwrap();
    let old = lease(&mut s, 2, &[7]);
    drop(s);
    let mut s = w.reopen(2000);
    assert_eq!(s.control_ingress_usage().waiting, 0);
    assert_eq!(queue(&mut s, 2, &[7]).unwrap(), Admission::RateLimited);
    s.advance_clock(clock(2999)).unwrap();
    assert_eq!(queue(&mut s, 2, &[7]).unwrap(), Admission::RateLimited);
    s.advance_clock(clock(3000)).unwrap();
    let new = lease(&mut s, 2, &[7]);
    assert_eq!(
        s.complete_control_verification(old, verified(object(4, 3, 7)), &[])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(s.control_ingress_usage().verifying, 1);
    assert_eq!(
        s.complete_control_verification(new, verified(object(4, 3, 7)), &[])
            .unwrap(),
        ControlVerificationCompletion::Accepted(ControlAdmission::Inserted([7; 32]))
    );
}
#[test]
fn clock_uncertainty_stops_dispatch_completion_and_admission_but_allows_cancel() {
    for regression in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        s.advance_clock(clock(2000)).unwrap();
        let pending = lease(&mut s, 2, &[7]);
        let mut bad = clock(if regression { 1999 } else { 2000 });
        if !regression {
            bad.boot = "other".into();
        }
        assert_eq!(s.advance_clock(bad).unwrap_err().code, Code::TimeUncertain);
        assert_eq!(
            s.next_control_verification().err().unwrap().code,
            Code::TimeUncertain
        );
        assert_eq!(
            queue(&mut s, 2, &[8]).unwrap_err().code,
            Code::TimeUncertain
        );
        s.cancel_control_verification(pending).unwrap();
        assert_eq!(s.control_ingress_usage().verifying, 0);
    }
}
#[test]
fn verified_commit_failure_releases_lease_without_refund_or_partial_policy() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.advance_clock(clock(1000)).unwrap();
        let pending = lease(&mut s, 4, &[7]);
        s.fault = Some(fault);
        assert_eq!(
            s.complete_control_verification(pending, verified(object(2, 2, 7)), &[])
                .unwrap_err()
                .code,
            if fault == TestFault::BeforeCommit {
                Code::StoreUnavailable
            } else {
                Code::OutcomeUnknown
            }
        );
        assert!(s.is_quarantined());
        assert_eq!(s.control_ingress_usage().verifying, 0);
        drop(s);
        let mut s = w.reopen(1000);
        assert_eq!(
            s.control_usage().unwrap().objects,
            if fault == TestFault::BeforeCommit {
                0
            } else {
                1
            }
        );
        assert_eq!(
            s.control_binding(&test_credential(2), &[2; 16]).unwrap(),
            if fault == TestFault::BeforeCommit {
                BindingState::Active
            } else {
                BindingState::Blocked
            }
        );
        assert_eq!(queue(&mut s, 4, &[8]).unwrap(), Admission::RateLimited);
    }
}

#[test]
fn ingress_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_INGRESS_TEST_STORE") else {
        return;
    };
    let mut s = Store::open(Path::new(&dir), Limits::default(), clock(0)).unwrap();
    s.advance_clock(clock(1000)).unwrap();
    let pending = lease(&mut s, 4, &[7]);
    match std::env::var("RADISHLINK_INGRESS_TEST_SIDE")
        .unwrap()
        .as_str()
    {
        "queued" => std::process::exit(73),
        "before" => s.fault = Some(TestFault::CrashBeforeCommit),
        "after" => s.fault = Some(TestFault::CrashAfterCommit),
        _ => panic!("invalid side"),
    }
    s.complete_control_verification(
        pending,
        verified(object(2, 2, 7)),
        &[ControlNeighbor {
            participant: [3; 16],
            link: Link::Up,
        }],
    )
    .unwrap();
    panic!("expected controlled exit");
}
#[test]
fn process_exit_discards_unverified_memory_and_recovers_atomic_verified_effects() {
    for (side, exit, committed) in [
        ("queued", 73, false),
        ("before", 71, false),
        ("after", 72, true),
    ] {
        let w = Workspace::new();
        let s = w.create();
        drop(s);
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "store::control_ingress_tests::ingress_crash_child",
                "--nocapture",
            ])
            .env("RADISHLINK_INGRESS_TEST_STORE", &w.dir)
            .env("RADISHLINK_INGRESS_TEST_SIDE", side)
            .status()
            .unwrap();
        assert_eq!(result.code(), Some(exit));
        let mut s = w.reopen(1000);
        assert_eq!(s.control_usage().unwrap().objects, u64::from(committed));
        assert_eq!(
            s.control_binding(&test_credential(2), &[2; 16]).unwrap(),
            if committed {
                BindingState::Blocked
            } else {
                BindingState::Active
            }
        );
        assert_eq!(
            s.control_ingress_usage(),
            ControlIngressUsage {
                waiting: 0,
                verifying: 0,
                object_bytes: 0,
                peer_buckets: 0
            }
        );
        assert_eq!(queue(&mut s, 4, &[8]).unwrap(), Admission::RateLimited);
        assert_eq!(
            s.business_policy_revision(ACTIVITY).unwrap(),
            if committed { 6 } else { 5 }
        );
        assert_eq!(
            s.control_progress([7; 32], [3; 16]).unwrap().is_some(),
            committed
        );
    }
}
