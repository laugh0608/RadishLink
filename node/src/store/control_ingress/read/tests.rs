use super::*;
use crate::store::tests::{ACTIVITY, Workspace, clock, test_credential};
use std::io::Read;

fn register(store: &mut Store, peer: u8) -> ControlIngressChannel {
    store
        .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(peer))
        .unwrap()
}

fn open(store: &mut Store, peer: u8, now: i64) -> ControlIngressChannel {
    let handle = register(store, peer);
    store.open_inbound_stream(&handle, &clock(now)).unwrap();
    store.mark_inbound_ready(&handle).unwrap();
    handle
}

fn frame(bytes: &[u8]) -> Vec<u8> {
    let mut wire = (bytes.len() as u32).to_be_bytes().to_vec();
    wire.extend_from_slice(bytes);
    wire
}

fn no_read(store: &mut Store, now: i64) -> InboundReadStep {
    store.poll_inbound(
        &clock(now),
        |_, _| panic!("no read expected"),
        || panic!("no read clock expected"),
        |_, _| panic!("no frame expected"),
    )
}

fn prefix(store: &mut Store, bytes: [u8; 4], now: i64) -> InboundReadStep {
    store.poll_inbound(
        &clock(now),
        |_, buffer| {
            assert_eq!(buffer.len(), 4);
            buffer.copy_from_slice(&bytes);
            Ok(4)
        },
        || Ok(clock(now)),
        |_, _| panic!("no complete frame yet"),
    )
}

#[test]
fn inbound_read_credit_stops_at_each_prefix_body_chunk_and_frame() {
    let w = Workspace::new();
    let mut store = w.create();
    let handle = open(&mut store, 2, 0);
    let body = vec![7; crate::framing::MAX_BODY_BYTES];
    let mut wire = frame(&body);
    wire.extend(frame(b"next"));
    let mut reader = wire.as_slice();
    let revision = store.revision().unwrap();
    let mut delivered = Vec::new();
    let mut credits = vec![(4, 2), (2, 2)];
    credits.extend((0..15).map(|_| (4096, 4096)));
    credits.extend([(4092, 4092), (4, 4), (4, 4)]);
    for (credit, count) in credits {
        let step = store.poll_inbound(
            &clock(0),
            |channel, buf| {
                assert_eq!(channel, handle.binding());
                assert_eq!(buf.len(), credit);
                reader.read(&mut buf[..count])
            },
            || Ok(clock(0)),
            |_, capacity| {
                assert_eq!(capacity, if delivered.is_empty() { body.len() } else { 4 });
                true
            },
        );
        assert!(step.closing.is_empty());
        match step.result.unwrap() {
            InboundReadProgress::Pending => {}
            InboundReadProgress::Frame(result) => delivered.push(result),
            _ => panic!("expected read progress"),
        }
    }
    assert!(reader.is_empty());
    assert_eq!(delivered.len(), 2);
    assert_eq!(delivered[0].channel, handle.binding());
    assert_eq!(delivered[0].body, body);
    assert_eq!(delivered[1].body, b"next");
    assert_eq!(store.revision().unwrap(), revision);
    assert!(store.outbound_acks.is_empty());
}

#[test]
fn inbound_read_full_downstream_drops_one_frame_and_keeps_next_boundary() {
    let w = Workspace::new();
    let mut store = w.create();
    let handle = open(&mut store, 2, 0);
    let wire = [frame(b"lost"), frame(b"next")].concat();
    let mut reader = wire.as_slice();
    let revision = store.revision().unwrap();
    for (index, expected) in [None, None, None, Some(b"next")].into_iter().enumerate() {
        let step = store.poll_inbound(
            &clock(0),
            |_, buf| reader.read(buf),
            || Ok(clock(0)),
            |_, cap| {
                assert_eq!(cap, 4);
                index == 3
            },
        );
        let result = step.result.unwrap();
        match (index, result, expected) {
            (0 | 2, InboundReadProgress::Pending, None)
            | (1, InboundReadProgress::Discarded, None) => {}
            (3, InboundReadProgress::Frame(result), Some(expected)) => {
                assert_eq!(result.body, expected);
                assert_eq!(result.channel, handle.binding());
            }
            _ => panic!("unexpected inbound frame state"),
        }
        assert!(step.closing.is_empty());
        assert_eq!(reader.len(), wire.len() - (index + 1) * 4);
    }
    assert_eq!(store.revision().unwrap(), revision);
    assert!(store.outbound_acks.is_empty());
}

#[test]
fn inbound_would_block_and_read_crossing_deadline_do_not_extend_assembly() {
    for (during_read, deadline) in [(false, 10_000), (true, 10_000), (true, 10_001)] {
        let w = Workspace::new();
        let mut store = w.create();
        let handle = open(&mut store, 2, 0);
        assert!(matches!(
            prefix(&mut store, 1u32.to_be_bytes(), 0).result.unwrap(),
            InboundReadProgress::Pending
        ));
        let step = store.poll_inbound(
            &clock(9999),
            |_, buf| {
                assert_eq!(buf.len(), 1);
                Err(io::ErrorKind::WouldBlock.into())
            },
            || Ok(clock(9999)),
            |_, _| panic!("no frame after WouldBlock"),
        );
        assert!(step.closing.is_empty());
        assert!(matches!(
            no_read(&mut store, 9999).result.unwrap(),
            InboundReadProgress::Idle
        ));
        let step = if during_read {
            store.mark_inbound_ready(&handle).unwrap();
            store.poll_inbound(
                &clock(9999),
                |_, buf| {
                    buf[0] = 7;
                    Ok(1)
                },
                || Ok(clock(deadline)),
                |_, _| panic!("late frame cannot reserve"),
            )
        } else {
            no_read(&mut store, deadline)
        };
        assert_eq!(step.closing.len(), 1);
        assert_eq!(step.closing[0].0, handle.binding());
        assert_eq!(step.closing[0].1.code, Code::Expired);
        assert!(
            store
                .ingress
                .framing
                .as_ref()
                .unwrap()
                .ready_capacity(&handle.binding().peer)
                .is_none()
        );
        assert!(store.mark_inbound_ready(&handle).is_err());
    }
}

#[test]
fn inbound_eof_overshoot_and_invalid_prefix_fence_original_channel() {
    for (kind, expected) in [
        (0, "inbound stream EOF"),
        (1, "inbound read exceeds credit"),
        (2, "frame body length"),
        (3, "frame body length"),
    ] {
        let w = Workspace::new();
        let mut store = w.create();
        let handle = open(&mut store, 2, 0);
        if kind == 0 {
            prefix(&mut store, 1u32.to_be_bytes(), 0).result.unwrap();
        }
        let step = store.poll_inbound(
            &clock(1),
            |_, buf| match kind {
                0 => Ok(0),
                1 => Ok(buf.len() + 1),
                2 => {
                    buf.copy_from_slice(&0u32.to_be_bytes());
                    Ok(4)
                }
                _ => {
                    buf.copy_from_slice(&65_533u32.to_be_bytes());
                    Ok(4)
                }
            },
            || Ok(clock(1)),
            |_, _| panic!("invalid frame cannot reserve"),
        );
        assert_eq!(step.closing.len(), 1);
        assert_eq!(step.closing[0].0, handle.binding());
        assert_eq!(step.closing[0].1.operation, expected);
        assert_eq!(
            store.ingress.framing.as_ref().unwrap().buffered_capacity(),
            0
        );
        assert!(
            store
                .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(2))
                .is_err()
        );
        store.close_control_ingress_channel(&handle).unwrap();
        let replacement = open(&mut store, 2, 1);
        assert_ne!(handle.binding(), replacement.binding());
        assert!(store.mark_inbound_ready(&handle).is_err());
        assert!(store.close_control_ingress_channel(&handle).is_err());
        assert!(prefix(&mut store, 1u32.to_be_bytes(), 1).closing.is_empty());
    }
}

#[test]
fn inbound_round_robin_coalesces_ready_and_leaves_a_shutdown_checkpoint() {
    let w = Workspace::new();
    let mut store = w.create();
    let channels: Vec<_> = (2..=5).map(|peer| open(&mut store, peer, 0)).collect();
    for expected in [2, 3, 4, 5, 2, 3, 4, 5] {
        store.mark_inbound_ready(&channels[0]).unwrap();
        let step = store.poll_inbound(
            &clock(0),
            |channel, buf| {
                assert_eq!(channel.peer, [expected; 16]);
                buf[0] = 0;
                Ok(1)
            },
            || Ok(clock(0)),
            |_, _| panic!("no complete prefix"),
        );
        assert!(matches!(step.result.unwrap(), InboundReadProgress::Pending));
        assert!(step.closing.is_empty());
    }
    let step = no_read(&mut store, 10_000);
    assert_eq!(step.closing.len(), 4);
    assert!(
        step.closing
            .iter()
            .all(|(_, error)| error.code == Code::Expired)
    );
    for channel in &channels {
        store.close_control_ingress_channel(channel).unwrap();
    }
    let channels: Vec<_> = (2..=5).map(|peer| open(&mut store, peer, 10_000)).collect();
    assert_eq!(store.begin_owner_shutdown().channels.len(), 4);
    assert!(store.ingress.framing.is_none());
    assert_eq!(
        no_read(&mut store, 10_000).result.err().unwrap().code,
        Code::Stopped
    );
    for channel in &channels {
        store.close_control_ingress_channel(channel).unwrap();
    }
    store.finish_owner_shutdown(Ok(())).unwrap();
}

#[test]
fn inbound_framing_open_requires_live_registration_and_closes_on_failure() {
    let w = Workspace::new();
    let mut store = w.create();
    let handle = register(&mut store, 2);
    assert_eq!(
        store.mark_inbound_ready(&handle).unwrap_err().code,
        Code::Stopped
    );
    assert!(matches!(
        no_read(&mut store, 0).result.unwrap(),
        InboundReadProgress::Idle
    ));
    store.shorten_control_activity(ACTIVITY, 10).unwrap();
    assert_eq!(
        store
            .open_inbound_stream(&handle, &clock(10))
            .unwrap_err()
            .code,
        Code::Expired
    );
    assert_eq!(
        store.mark_inbound_ready(&handle).unwrap_err().operation,
        "control ingress channel closing"
    );
    assert!(store.ingress.framing.is_none());
    assert!(
        store
            .register_control_ingress_channel(ACTIVITY, test_credential(1), test_credential(2))
            .is_err()
    );
    store.close_control_ingress_channel(&handle).unwrap();
}

#[test]
fn inbound_policy_is_checked_before_read_and_again_before_transfer() {
    let w = Workspace::new();
    let mut store = w.create();
    let blocked = open(&mut store, 2, 0);
    store
        .block_control_binding(ACTIVITY, test_credential(2))
        .unwrap();
    let step = no_read(&mut store, 0);
    assert_eq!(step.closing.len(), 1);
    assert_eq!(step.closing[0].0, blocked.binding());
    assert_eq!(step.closing[0].1.code, Code::Conflict);
    assert!(matches!(step.result.unwrap(), InboundReadProgress::Idle));

    let expiring = open(&mut store, 3, 0);
    store.shorten_control_activity(ACTIVITY, 10).unwrap();
    prefix(&mut store, 1u32.to_be_bytes(), 0).result.unwrap();
    let step = store.poll_inbound(
        &clock(9),
        |channel, buf| {
            assert_eq!(channel, expiring.binding());
            buf[0] = 7;
            Ok(1)
        },
        || Ok(clock(10)),
        |_, _| panic!("expired activity cannot transfer"),
    );
    assert_eq!(step.closing.len(), 1);
    assert_eq!(step.closing[0].0, expiring.binding());
    assert_eq!(step.closing[0].1.operation, "control activity deadline");
    assert!(matches!(step.result.unwrap(), InboundReadProgress::Pending));
}

#[test]
fn inbound_readiness_is_removed_on_close_and_old_owner_cannot_rearm_after_reopen() {
    let w = Workspace::new();
    let mut store = w.create();
    let old = open(&mut store, 2, 0);
    prefix(&mut store, 1u32.to_be_bytes(), 0).result.unwrap();
    store.begin_control_ingress_channel_close(&old).unwrap();
    assert!(matches!(
        no_read(&mut store, 0).result.unwrap(),
        InboundReadProgress::Idle
    ));
    assert_eq!(
        store.ingress.framing.as_ref().unwrap().buffered_capacity(),
        0
    );
    store.close_control_ingress_channel(&old).unwrap();
    store.close().unwrap();

    let mut store = w.reopen(0);
    let replacement = register(&mut store, 2);
    assert_eq!(old.binding(), replacement.binding());
    store.open_inbound_stream(&replacement, &clock(0)).unwrap();
    assert_eq!(
        store.mark_inbound_ready(&old).unwrap_err().operation,
        "control ingress channel owner changed"
    );
    assert!(matches!(
        no_read(&mut store, 0).result.unwrap(),
        InboundReadProgress::Idle
    ));
    store.mark_inbound_ready(&replacement).unwrap();
    assert!(matches!(
        prefix(&mut store, 1u32.to_be_bytes(), 0).result.unwrap(),
        InboundReadProgress::Pending
    ));
}

#[test]
fn inbound_clock_regression_after_read_fences_all_attached_instances() {
    let w = Workspace::new();
    let mut store = w.create();
    let old = open(&mut store, 2, 0);
    let other = open(&mut store, 3, 0);
    let step = store.poll_inbound(
        &clock(2),
        |_, buf| {
            buf.copy_from_slice(&1u32.to_be_bytes());
            Ok(4)
        },
        || Ok(clock(1)),
        |_, _| panic!("uncertain bytes cannot transfer"),
    );
    assert_eq!(step.result.err().unwrap().code, Code::TimeUncertain);
    assert_eq!(
        step.closing
            .iter()
            .map(|(channel, _)| *channel)
            .collect::<Vec<_>>(),
        [old.binding(), other.binding()]
    );
    assert_eq!(
        store.ingress.framing.as_ref().unwrap().buffered_capacity(),
        0
    );
    assert!(store.is_time_uncertain());
    store.close_control_ingress_channel(&old).unwrap();
    store.close_control_ingress_channel(&other).unwrap();
    assert_eq!(
        no_read(&mut store, 3).result.err().unwrap().code,
        Code::TimeUncertain
    );
}
