use super::outbound_cycle_tests::{data, input};
use super::outbound_tests::{batch, object};
use super::tests::{ACTIVITY, Workspace, clock, destination, test_credential};
use super::*;
use std::error::Error as _;

fn register(s: &mut Store, peer: u8) -> ControlIngressChannel {
    s.register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(peer))
        .unwrap()
}

fn start_partial(s: &mut Store, channel: OutboundChannel) -> OutboundHandoffRequest {
    let mut cycle = s.start_outbound_cycle().unwrap();
    s.process_outbound_cycle_with_handoff(
        &mut cycle,
        input(s, 2000, vec![]),
        |_| Ok(batch(2000)),
        |_| Some(channel),
    )
    .unwrap();
    let first = s.next_outbound_handoff().unwrap();
    let step = s.advance_outbound_handoff(
        &first,
        OutboundHandoffInput {
            clock: clock(2000),
            channel: Some(channel),
            frame: OutboundFrame::Data {
                bytes: 64,
                remaining_ms: 500,
                hops: 0,
            },
        },
        |_, _| OutboundWrite::Written(8),
    );
    assert_eq!(step.result.unwrap(), OutboundWriteProgress::Partial(8));
    s.next_outbound_handoff().unwrap()
}

#[test]
fn stopping_withdraws_output_and_waiting_work_but_retains_the_lease_and_join_cause() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let ingress = register(&mut s, 2);
    let sending = register(&mut s, 3);
    let continuation = start_partial(&mut s, sending.binding());
    s.receive_destination_on_channel(&ingress, destination("receipt", 0))
        .unwrap();
    assert_eq!(s.outbound_acks.len(), 1);
    s.queue_control_candidate_on_channel(&ingress, &[7])
        .unwrap();
    let running = s.next_control_verification().unwrap().job.unwrap();
    s.queue_control_candidate_on_channel(&ingress, &[8])
        .unwrap();
    assert_eq!(s.control_ingress_usage().waiting, 1);
    let revision = s.revision().unwrap();

    let plan = s.begin_owner_shutdown();
    assert_eq!(plan.channels, vec![ingress.binding(), sending.binding()]);
    assert_eq!(plan.interrupted_output, Some(sending.binding()));
    assert_eq!(
        s.begin_owner_shutdown().interrupted_output,
        plan.interrupted_output
    );
    assert!(s.outbound_acks.is_empty());
    assert!(s.next_outbound_handoff().is_none());
    assert_eq!(s.control_ingress_usage().waiting, 0);
    assert_eq!(s.control_ingress_usage().verifying, 1);
    assert_eq!(
        s.queue_control_candidate_on_channel(&ingress, &[9])
            .unwrap_err()
            .code,
        Code::Stopped
    );
    assert_eq!(
        s.next_control_verification().err().unwrap().code,
        Code::Stopped
    );
    assert_eq!(
        s.register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(4))
            .err()
            .unwrap()
            .code,
        Code::Stopped
    );
    let step = s.advance_outbound_handoff(
        &continuation,
        OutboundHandoffInput {
            clock: clock(2000),
            channel: Some(sending.binding()),
            frame: OutboundFrame::Data {
                bytes: 64,
                remaining_ms: 500,
                hops: 0,
            },
        },
        |_, _| panic!("stopping owner must not continue a partial frame"),
    );
    assert_eq!(step.result.unwrap_err().code, Code::Conflict);
    assert_eq!(
        s.finish_owner_shutdown(Ok(())).unwrap_err().operation,
        "owner shutdown channels remain"
    );

    s.close_control_ingress_channel(&sending).unwrap();
    assert!(s.begin_owner_shutdown().interrupted_output.is_none());
    let outcome = ControlVerificationOutcome::Verified(Box::new(object(4, 5, 7)));
    assert_eq!(
        s.complete_control_verification_with_ack(running, outcome, &[])
            .unwrap_err()
            .code,
        Code::Stopped
    );
    assert_eq!(s.control_ingress_usage().verifying, 0);
    assert_eq!(s.control_usage().unwrap().objects, 0);
    s.close_control_ingress_channel(&ingress).unwrap();
    let err = s
        .finish_owner_shutdown(Err(Error::source_error(
            Code::Stopped,
            "synthetic verifier Join failed",
            std::io::Error::from_raw_os_error(5),
        )))
        .unwrap_err();
    assert_eq!(err.operation, "synthetic verifier Join failed");
    assert_eq!(
        err.source()
            .unwrap()
            .downcast_ref::<std::io::Error>()
            .unwrap()
            .raw_os_error(),
        Some(5)
    );
    assert_eq!(
        s.preflight_activity_switch().err().unwrap().code,
        Code::Stopped
    );
    assert_eq!(
        s.establish_clock_domain(NewClockDomainActivity {
            source: INITIAL_CLOCK_DOMAIN,
            isolated_revision: 1,
            reference: "synthetic-shutdown".into(),
            domain: [8; 32],
            sequence: 2,
            boot: "other".into(),
            activity: [8; 32],
            local_participant: [9; 16],
            started_ms: 0,
            deadline_ms: 1000,
        })
        .err()
        .unwrap()
        .code,
        Code::Stopped
    );
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(2000))
            .err()
            .unwrap()
            .code,
        Code::Busy
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert!(
        s.message("receipt")
            .unwrap()
            .unwrap()
            .receipt_intent_pending
    );
    s.finish_owner_shutdown(Ok(())).unwrap();
    s.close().unwrap();
    w.reopen(2000).close().unwrap();
}

#[test]
fn unregistered_partial_needs_exact_close_and_leases_block_join_confirmation() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let channel = OutboundChannel {
        instance: 4,
        local: [1; 16],
        local_credential: test_credential(1),
        peer: [3; 16],
        peer_credential: test_credential(3),
    };
    start_partial(&mut s, channel);
    s.queue_control_candidate(ACTIVITY, test_credential(2), &[7])
        .unwrap();
    let running = s.next_control_verification().unwrap().job.unwrap();
    let plan = s.begin_owner_shutdown();
    assert!(plan.channels.is_empty());
    assert_eq!(plan.interrupted_output, Some(channel));
    assert_eq!(
        s.confirm_owner_output_closed(OutboundChannel {
            instance: 5,
            ..channel
        })
        .unwrap_err()
        .code,
        Code::Conflict
    );
    assert_eq!(
        s.finish_owner_shutdown(Ok(())).unwrap_err().operation,
        "owner shutdown channels remain"
    );
    s.confirm_owner_output_closed(channel).unwrap();
    assert_eq!(
        s.finish_owner_shutdown(Ok(())).unwrap_err().operation,
        "owner shutdown verification tasks remain"
    );
    s.cancel_control_verification(running).unwrap();
    s.finish_owner_shutdown(Ok(())).unwrap();
    s.close().unwrap();
}
