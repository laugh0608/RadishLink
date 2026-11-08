use super::*;
use crate::retry::Link;
use crate::store::{
    outbound_tests::object,
    tests::{ACTIVITY, Workspace, clock, test_credential},
};

fn dispatch(store: &mut Store) -> ControlVerificationDispatch {
    let poll = store.dispatch_control_verification().unwrap();
    assert!(poll.discarded.is_empty());
    poll.dispatch.unwrap()
}

#[test]
fn verification_dispatch_returns_when_all_original_slots_are_leased() {
    let workspace = Workspace::new();
    let mut store = workspace.create();
    for round in 1..=4 {
        store.advance_clock(clock(round * 1000)).unwrap();
        for peer in 2..=5 {
            assert_eq!(
                store
                    .queue_control_candidate(ACTIVITY, test_credential(peer), &[round as u8])
                    .unwrap(),
                ControlIngressAdmission::Queued
            );
        }
    }
    let mut tasks = (0..MAX_PENDING_CONTROLS).map(|_| dispatch(&mut store));
    let first = tasks.next().unwrap();
    let rest: Vec<_> = tasks.collect();
    assert_eq!(first.job().cose(), &[1]);
    assert!(
        store
            .dispatch_control_verification()
            .unwrap()
            .dispatch
            .is_none()
    );

    std::thread::scope(|scope| {
        scope
            .spawn(move || {
                let mut oversized = object(4, 5, 1);
                oversized.fields.payload.reserve(MAX_CONTROL_BYTES + 1);
                first
                    .return_result(ControlVerificationOutcome::Verified(Box::new(oversized)))
                    .unwrap();
                for task in rest {
                    task.return_result(ControlVerificationOutcome::Rejected)
                        .unwrap();
                }
            })
            .join()
            .unwrap();
    });

    assert_eq!(
        store.control_ingress_usage().verifying,
        MAX_PENDING_CONTROLS
    );
    assert_eq!(
        store.control_ingress_usage().object_bytes,
        MAX_PENDING_CONTROLS
    );
    assert_eq!(
        store
            .poll_control_verification_result(&[])
            .unwrap_err()
            .operation,
        "control verification result capacity"
    );
    assert_eq!(
        store.control_ingress_usage().verifying,
        MAX_PENDING_CONTROLS - 1
    );
    for _ in 1..MAX_PENDING_CONTROLS {
        assert_eq!(
            store.poll_control_verification_result(&[]).unwrap(),
            Some((
                ControlVerificationCompletion::Rejected,
                OutboundAckAdmission::NotEligible
            ))
        );
    }
    assert!(
        store
            .poll_control_verification_result(&[])
            .unwrap()
            .is_none()
    );
    assert_eq!(store.control_ingress_usage().object_bytes, 0);
    assert_eq!(store.control_usage().unwrap().objects, 0);
}

#[test]
fn verification_dispatch_keeps_a_late_result_bound_to_the_closed_instance() {
    let workspace = Workspace::new();
    let mut store = workspace.create();
    store.advance_clock(clock(2000)).unwrap();
    let register = |store: &mut Store| {
        store
            .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(2))
            .unwrap()
    };
    let original = register(&mut store);
    store
        .queue_control_candidate_on_channel(&original, &[7])
        .unwrap();
    let old_task = dispatch(&mut store);
    store
        .begin_control_ingress_channel_close(&original)
        .unwrap();
    store.close_control_ingress_channel(&original).unwrap();
    let replacement = register(&mut store);
    store
        .queue_control_candidate_on_channel(&replacement, &[7])
        .unwrap();
    let new_task = dispatch(&mut store);
    assert_eq!(new_task.job().channel(), Some(replacement.binding()));

    let revision = store.revision().unwrap();
    old_task
        .return_result(ControlVerificationOutcome::Verified(Box::new(object(
            4, 5, 7,
        ))))
        .unwrap();
    assert_eq!(
        store
            .poll_control_verification_result(&[])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(store.revision().unwrap(), revision);
    assert_eq!(store.control_ingress_usage().verifying, 1);
    assert!(store.outbound_acks.is_empty());

    new_task
        .return_result(ControlVerificationOutcome::Verified(Box::new(object(
            4, 5, 7,
        ))))
        .unwrap();
    let neighbor = ControlNeighbor {
        participant: [2; 16],
        link: Link::Up,
    };
    assert_eq!(
        store.poll_control_verification_result(&[neighbor]).unwrap(),
        Some((
            ControlVerificationCompletion::Accepted(ControlAdmission::Inserted([7; 32])),
            OutboundAckAdmission::Queued
        ))
    );
    assert_eq!(store.control_ingress_usage().verifying, 0);
    assert_eq!(store.revision().unwrap(), revision + 1);
}

#[test]
fn verification_dispatch_shutdown_waits_for_join_or_an_actual_return() {
    let workspace = Workspace::new();
    let mut store = workspace.create();
    store.advance_clock(clock(1000)).unwrap();
    for peer in 2..=5 {
        store
            .queue_control_candidate(ACTIVITY, test_credential(peer), &[peer])
            .unwrap();
    }
    let abandoned = dispatch(&mut store);
    let late = dispatch(&mut store);
    let connected = dispatch(&mut store);
    drop(abandoned);
    assert_eq!(
        store
            .poll_control_verification_result(&[])
            .unwrap_err()
            .operation,
        "control verification result sender disconnected"
    );
    let revision = store.revision().unwrap();
    store.begin_owner_shutdown();
    assert_eq!(store.control_ingress_usage().waiting, 0);
    assert_eq!(store.control_ingress_usage().verifying, 3);
    assert_eq!(
        store.dispatch_control_verification().err().unwrap().code,
        Code::Stopped
    );

    late.return_result(ControlVerificationOutcome::Verified(Box::new(object(
        4, 5, 3,
    ))))
    .unwrap();
    assert_eq!(
        store
            .poll_control_verification_result(&[])
            .unwrap_err()
            .operation,
        "store owner stopping"
    );
    assert_eq!(store.revision().unwrap(), revision);
    assert_eq!(store.control_ingress_usage().verifying, 2);
    assert_eq!(
        store
            .finish_owner_shutdown(Err(Error::new(Code::Stopped, "synthetic Join failed")))
            .unwrap_err()
            .operation,
        "synthetic Join failed"
    );
    assert_eq!(store.control_ingress_usage().verifying, 2);
    assert_eq!(
        store.finish_owner_shutdown(Ok(())).unwrap_err().operation,
        "owner shutdown verification tasks remain"
    );
    assert_eq!(store.control_ingress_usage().verifying, 1);
    connected
        .return_result(ControlVerificationOutcome::Rejected)
        .unwrap();
    store.finish_owner_shutdown(Ok(())).unwrap();
    assert_eq!(store.control_ingress_usage().verifying, 0);
    store.close().unwrap();
}
