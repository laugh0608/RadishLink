use super::super::tests::frame;
use super::*;
use crate::store::{
    outbound_cycle_tests::data,
    outbound_tests::add_control,
    tests::{ACTIVITY, Workspace, binding, clock, test_credential},
};
use std::io::Read;

fn open(s: &mut Store, peer: u8, now: i64) -> ControlIngressChannel {
    let channel = s
        .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(peer))
        .unwrap();
    s.open_inbound_stream(&channel, &clock(now)).unwrap();
    channel
}

fn read_frame(
    s: &mut Store,
    channel: &ControlIngressChannel,
    now: i64,
    bytes: &[u8],
) -> InboundFrame {
    s.mark_inbound_ready(channel).unwrap();
    let wire = frame(bytes);
    let mut reader = wire.as_slice();
    for _ in 0..1 + bytes.len().div_ceil(READ_CHUNK_BYTES) {
        let step = s.poll_inbound(
            &clock(now),
            |source, buf| {
                assert_eq!(source, channel.binding());
                reader.read(buf)
            },
            || Ok(clock(now)),
            |_, _| true,
        );
        assert!(step.closing.is_empty());
        if let InboundReadProgress::Frame(frame) = step.result.unwrap() {
            assert!(reader.is_empty());
            let blocked = s.poll_inbound(
                &clock(now),
                |source, _| {
                    assert_eq!(source, channel.binding());
                    Err(io::ErrorKind::WouldBlock.into())
                },
                || Ok(clock(now)),
                |_, _| panic!("no frame expected"),
            );
            assert!(blocked.closing.is_empty());
            assert!(matches!(
                blocked.result.unwrap(),
                InboundReadProgress::Pending
            ));
            return frame;
        }
    }
    panic!("complete frame expected")
}

fn receipt() -> DecodedInbound {
    DecodedInbound::Receipt { cose: 4..6 }
}

fn no_payload(_: OutboundChannel, _: InboundPayload<'_>) -> Result<()> {
    panic!("no payload expected")
}

#[test]
fn inbound_dispatch_charges_original_backing_to_each_payload_lane() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = open(&mut s, 2, 0);
    let revision = s.revision().unwrap();
    let data_bytes = b"__core__mls";
    let receipt_bytes = b"____rc";
    let decode_data = || DecodedInbound::Data {
        core: 2..6,
        mls: 8..11,
    };
    let first = read_frame(&mut s, &channel, 0, data_bytes);
    let data_credit = first.body.capacity();
    let credit = || InboundPayloadCredit {
        data: data_credit - 1,
        receipt: usize::MAX,
    };
    assert_eq!(
        s.dispatch_inbound_frame(
            first,
            |_| Ok(decode_data()),
            || Ok(clock(0)),
            credit(),
            no_payload
        )
        .unwrap(),
        InboundDispatch::PayloadFull
    );
    let second = read_frame(&mut s, &channel, 0, receipt_bytes);
    let receipt_credit = second.body.capacity();
    let receipt_ptr = second.body()[4..].as_ptr();
    assert_eq!(
        s.dispatch_inbound_frame(
            second,
            |_| Ok(receipt()),
            || Ok(clock(0)),
            InboundPayloadCredit {
                data: 0,
                receipt: receipt_credit
            },
            |source, payload| {
                let InboundPayload::Receipt { cose } = payload else {
                    panic!("receipt expected")
                };
                assert_eq!(source, channel.binding());
                assert_eq!(cose, b"rc");
                assert_eq!(cose.as_ptr(), receipt_ptr);
                Ok(())
            },
        )
        .unwrap(),
        InboundDispatch::Payload
    );
    let third = read_frame(&mut s, &channel, 0, receipt_bytes);
    assert_eq!(
        s.dispatch_inbound_frame(
            third,
            |_| Ok(receipt()),
            || Ok(clock(0)),
            InboundPayloadCredit {
                data: usize::MAX,
                receipt: receipt_credit - 1
            },
            no_payload,
        )
        .unwrap(),
        InboundDispatch::PayloadFull
    );
    let fourth = read_frame(&mut s, &channel, 0, data_bytes);
    let core_ptr = fourth.body()[2..].as_ptr();
    let mls_ptr = fourth.body()[8..].as_ptr();
    assert_eq!(
        s.dispatch_inbound_frame(
            fourth,
            |_| Ok(decode_data()),
            || Ok(clock(0)),
            InboundPayloadCredit {
                data: data_credit,
                receipt: 0
            },
            |_, payload| {
                let InboundPayload::Data { core, mls } = payload else {
                    panic!("data expected")
                };
                assert_eq!((core, mls), (b"core".as_slice(), b"mls".as_slice()));
                assert_eq!((core.as_ptr(), mls.as_ptr()), (core_ptr, mls_ptr));
                Ok(())
            },
        )
        .unwrap(),
        InboundDispatch::Payload
    );
    assert_eq!(s.control_ingress_usage().waiting, 0);
    assert!(s.outbound_acks.is_empty() && s.outbound_terminal.is_none());
    assert_eq!(s.revision().unwrap(), revision);
}

fn control(
    s: &mut Store,
    channel: &ControlIngressChannel,
    now: i64,
    id: u8,
) -> Result<InboundDispatch> {
    let frame = read_frame(
        s,
        channel,
        now,
        &[0x83, 1, 2, 0x42, id, channel.binding().peer[0]],
    );
    s.dispatch_inbound_frame(
        frame,
        |_| Ok(DecodedInbound::Control { cose: 4..6 }),
        || Ok(clock(now)),
        InboundPayloadCredit::default(),
        no_payload,
    )
}

#[test]
fn inbound_dispatch_reuses_control_queue_and_keeps_full_drop_charged() {
    use ControlIngressAdmission::{QueueFull, Queued, RateLimited};
    let w = Workspace::new();
    let mut s = w.create();
    let channels: Vec<_> = (2..=5).map(|peer| open(&mut s, peer, 0)).collect();
    let revision = s.revision().unwrap();
    let outcome = |admission| InboundDispatch::Control {
        admission,
        ack: OutboundAckAdmission::NotEligible,
    };
    assert_eq!(
        control(&mut s, &channels[0], 1, 1).unwrap(),
        outcome(RateLimited)
    );
    assert_eq!(s.control_ingress_usage().waiting, 0);
    for round in 1..=4 {
        let now = round * 1000;
        for channel in &channels {
            assert_eq!(
                control(&mut s, channel, now, round as u8).unwrap(),
                outcome(Queued)
            );
        }
    }
    assert_eq!(s.control_ingress_usage().waiting, MAX_PENDING_CONTROLS);
    assert_eq!(
        control(&mut s, &channels[0], 5000, 5).unwrap(),
        outcome(QueueFull)
    );
    assert_eq!(
        control(&mut s, &channels[0], 5000, 6).unwrap(),
        outcome(RateLimited)
    );

    let frame = read_frame(&mut s, &channels[0], 5000, b"____rc");
    assert_eq!(
        s.dispatch_inbound_frame(
            frame,
            |_| Ok(receipt()),
            || Ok(clock(5000)),
            InboundPayloadCredit {
                data: 0,
                receipt: 6
            },
            |_, payload| {
                assert!(matches!(payload, InboundPayload::Receipt { cose: b"rc" }));
                Ok(())
            },
        )
        .unwrap(),
        InboundDispatch::Payload
    );
    let job = s.next_control_verification().unwrap().job.unwrap();
    assert_eq!(job.channel(), Some(channels[0].binding()));
    assert_eq!(job.cose(), &[1, 2]);
    s.cancel_control_verification(job).unwrap();
    assert_eq!(s.control_ingress_usage().waiting, MAX_PENDING_CONTROLS - 1);
    assert!(s.outbound_acks.is_empty());
    assert_eq!(s.current_clock(), clock(0));
    assert_eq!(s.revision().unwrap(), revision);
}

#[test]
fn inbound_dispatch_charges_post_decode_time_and_shares_it_with_legacy_admission() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = open(&mut s, 2, 0);
    let revision = s.revision().unwrap();
    let frame = read_frame(&mut s, &channel, 999, &[0x83, 1, 2, 0x41, 7]);
    assert_eq!(
        s.queue_control_candidate(ACTIVITY, test_credential(2), &[8])
            .unwrap(),
        ControlIngressAdmission::RateLimited
    );
    assert_eq!(
        s.dispatch_inbound_frame(
            frame,
            |_| Ok(DecodedInbound::Control { cose: 4..5 }),
            || Ok(clock(1000)),
            InboundPayloadCredit::default(),
            no_payload,
        )
        .unwrap(),
        InboundDispatch::Control {
            admission: ControlIngressAdmission::Queued,
            ack: OutboundAckAdmission::NotEligible,
        },
    );
    assert_eq!(
        s.queue_control_candidate(ACTIVITY, test_credential(2), &[8])
            .unwrap(),
        ControlIngressAdmission::RateLimited
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert_eq!(s.current_clock(), clock(0));
    assert_eq!(
        s.advance_clock(clock(999)).unwrap_err().code,
        Code::TimeUncertain
    );
    assert!(s.is_time_uncertain());
    assert_eq!(s.revision().unwrap(), revision);
}

fn link_ack(
    activity: ActivityId,
    peer: u8,
    credential: CredentialRef,
    target: OutboundTerminalAck,
) -> DecodedInbound {
    DecodedInbound::LinkAck {
        activity,
        custodian: [peer; 16],
        credential,
        target,
    }
}

#[test]
fn inbound_dispatch_checks_link_ack_source_before_the_existing_terminal_slot() {
    let w = Workspace::new();
    let mut s = w.create();
    data(&mut s, 1);
    let channel = open(&mut s, 3, 0);
    let data_ack = || OutboundTerminalAck::Data {
        message: "q000".into(),
        binding: binding("q000").try_into().unwrap(),
    };
    let revision = s.revision().unwrap();
    let mut send = |activity, peer, credential, size| {
        let frame = read_frame(&mut s, &channel, 1000, &vec![1; size]);
        s.dispatch_inbound_frame(
            frame,
            |_| Ok(link_ack(activity, peer, credential, data_ack())),
            || Ok(clock(1000)),
            InboundPayloadCredit::default(),
            no_payload,
        )
    };
    assert_eq!(
        send(ACTIVITY, 3, test_credential(3), LINK_ACK_BODY - 1)
            .unwrap_err()
            .code,
        Code::InvalidInput
    );
    for (activity, peer, credential) in [
        ([9; 32], 3, test_credential(3)),
        (ACTIVITY, 4, test_credential(3)),
        (ACTIVITY, 3, test_credential(4)),
    ] {
        assert_eq!(
            send(activity, peer, credential, LINK_ACK_BODY)
                .unwrap_err()
                .operation,
            "inbound LinkAck source binding"
        );
    }
    assert_eq!(
        send(ACTIVITY, 3, test_credential(3), LINK_ACK_BODY).unwrap(),
        InboundDispatch::LinkAck(OutboundTerminalAdmission::Accepted { close: None })
    );
    assert_eq!(
        send(ACTIVITY, 3, test_credential(3), LINK_ACK_BODY)
            .unwrap_err()
            .code,
        Code::Busy
    );
    assert_eq!(s.revision().unwrap(), revision);
    assert!(!s.message("q000").unwrap().unwrap().custody_observed);
    assert!(s.outbound_acks.is_empty());
    s.commit_outbound_terminal(clock(1001)).unwrap();
    let saved = s.message("q000").unwrap().unwrap();
    assert!(saved.custody_observed && saved.payload_present);
}

#[test]
fn inbound_dispatch_control_ack_uses_persisted_control_responsibility() {
    let w = Workspace::new();
    let mut s = w.create();
    add_control(&mut s, 4, 5, 10);
    let channel = open(&mut s, 2, 0);
    let mut send = |now, object| {
        let frame = read_frame(&mut s, &channel, now, &[0; LINK_ACK_BODY]);
        s.dispatch_inbound_frame(
            frame,
            |_| {
                Ok(link_ack(
                    ACTIVITY,
                    2,
                    test_credential(2),
                    OutboundTerminalAck::Control { object },
                ))
            },
            || Ok(clock(now)),
            InboundPayloadCredit::default(),
            no_payload,
        )
    };
    assert_eq!(send(1000, [9; 32]).unwrap_err().code, Code::Conflict);
    assert_eq!(
        send(1000, [10; 32]).unwrap(),
        InboundDispatch::LinkAck(OutboundTerminalAdmission::Accepted { close: None })
    );
    s.commit_outbound_terminal(clock(1001)).unwrap();
    assert!(
        s.control_progress([10; 32], [2; 16])
            .unwrap()
            .unwrap()
            .terminal
    );
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn inbound_dispatch_drops_invalid_decoder_result_and_can_process_next_frame() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = open(&mut s, 2, 0);
    let revision = s.revision().unwrap();
    for decoded in [
        Err(Error::new(
            Code::InvalidInput,
            "synthetic noncanonical frame",
        )),
        Ok(DecodedInbound::Data {
            core: 0..5,
            mls: 4..6,
        }),
        Ok(DecodedInbound::Control { cose: 4..7 }),
        Ok(DecodedInbound::Receipt { cose: 6..6 }),
    ] {
        let frame = read_frame(&mut s, &channel, 0, b"____rc");
        assert_eq!(
            s.dispatch_inbound_frame(
                frame,
                |_| decoded,
                || Ok(clock(0)),
                InboundPayloadCredit::default(),
                no_payload
            )
            .unwrap_err()
            .code,
            Code::InvalidInput
        );
    }
    let frame = read_frame(&mut s, &channel, 0, b"____rc");
    assert_eq!(
        s.dispatch_inbound_frame(
            frame,
            |_| Ok(receipt()),
            || Ok(clock(0)),
            InboundPayloadCredit {
                data: 0,
                receipt: 6
            },
            |_, _| Ok(())
        )
        .unwrap(),
        InboundDispatch::Payload
    );
    assert_eq!(s.control_ingress_usage().waiting, 0);
    assert!(s.outbound_acks.is_empty() && s.outbound_terminal.is_none());
    assert_eq!(s.revision().unwrap(), revision);
}

#[test]
fn inbound_dispatch_samples_after_decoding_the_original_frame() {
    let w = Workspace::new();
    let mut s = w.create();
    let channel = open(&mut s, 2, 0);
    s.shorten_control_activity(ACTIVITY, 10).unwrap();
    let frame = read_frame(&mut s, &channel, 9, b"____rc");
    let original = frame.body().as_ptr();
    let decoded = std::cell::Cell::new(false);
    let error = s
        .dispatch_inbound_frame(
            frame,
            |body| {
                assert_eq!(body.as_ptr(), original);
                decoded.set(true);
                Ok(receipt())
            },
            || {
                assert!(decoded.get());
                Ok(clock(10))
            },
            InboundPayloadCredit {
                data: 0,
                receipt: 6,
            },
            no_payload,
        )
        .unwrap_err();
    assert_eq!(error.code, Code::Expired);
    assert!(s.outbound_acks.is_empty());
}

#[test]
fn inbound_dispatch_rejects_late_frames_on_revocation_reconnect_and_owner_reopen() {
    let w = Workspace::new();
    let mut s = w.create();
    let old = open(&mut s, 2, 0);
    let before_close = read_frame(&mut s, &old, 0, b"____rc");
    let before_reconnect = read_frame(&mut s, &old, 0, b"____rc");
    let attempt = |s: &mut Store, frame| {
        s.dispatch_inbound_frame(
            frame,
            |_| Ok(receipt()),
            || Ok(clock(0)),
            InboundPayloadCredit {
                data: 0,
                receipt: 6,
            },
            no_payload,
        )
        .unwrap_err()
    };
    s.begin_control_ingress_channel_close(&old).unwrap();
    assert_eq!(
        attempt(&mut s, before_close).operation,
        "control ingress channel closing"
    );
    s.close_control_ingress_channel(&old).unwrap();
    let current = open(&mut s, 2, 0);
    assert_eq!(
        attempt(&mut s, before_reconnect).operation,
        "control ingress channel instance changed"
    );
    let before_revocation = read_frame(&mut s, &current, 0, b"____rc");
    s.block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    assert_eq!(
        attempt(&mut s, before_revocation).operation,
        "registered channel binding changed"
    );
    s.close_control_ingress_channel(&current).unwrap();
    s.close().unwrap();

    let mut s = w.reopen(0);
    let old = open(&mut s, 3, 0);
    let before_reopen = read_frame(&mut s, &old, 0, b"____rc");
    s.close_control_ingress_channel(&old).unwrap();
    s.close().unwrap();
    let mut s = w.reopen(0);
    let new = open(&mut s, 3, 0);
    assert_eq!(old.binding(), new.binding());
    assert_eq!(
        attempt(&mut s, before_reopen).operation,
        "control ingress channel owner changed"
    );
    assert!(s.outbound_acks.is_empty() && s.outbound_terminal.is_none());
}
