use super::*;

const PEER: Neighbor = [1; 16];

fn clock(monotonic_ms: i64) -> Clock {
    Clock {
        boot: "synthetic-boot".into(),
        monotonic_ms,
        trusted_utc: None,
    }
}

fn ingress() -> Ingress {
    let mut ingress = Ingress::new(&clock(0)).unwrap();
    ingress.open(PEER, &clock(0)).unwrap();
    ingress
}

#[test]
fn fragmented_prefix_and_body_keep_one_deadline() {
    let mut ingress = ingress();
    for byte in [0, 0, 0, 3] {
        let progress = ingress.push(&PEER, &clock(0), &[byte]).unwrap();
        assert_eq!(progress.consumed, 1);
        assert!(!progress.complete);
    }
    assert!(ingress.take(&PEER, &clock(9998)).unwrap().is_none());
    assert!(!ingress.push(&PEER, &clock(9998), b"ab").unwrap().complete);
    assert!(ingress.push(&PEER, &clock(9999), b"c").unwrap().complete);
    // Complete assembly is not made incomplete again by waiting in the next stage.
    assert!(ingress.expire(&clock(20000)).unwrap().is_empty());
    assert_eq!(ingress.take(&PEER, &clock(20000)).unwrap().unwrap(), b"abc");
    assert_eq!(ingress.buffered_capacity(), 4);
}

#[test]
fn zero_and_oversized_prefixes_close_before_body_allocation() {
    for len in [0_u32, 65533, 65536, u32::MAX] {
        let mut ingress = ingress();
        let error = ingress
            .push(&PEER, &clock(0), &len.to_be_bytes())
            .unwrap_err();
        assert_eq!(error.code, Code::InvalidInput);
        assert_eq!(ingress.stream_count(), 0);
        assert_eq!(ingress.buffered_capacity(), 0);
        assert_eq!(
            ingress
                .push(&PEER, &clock(0), b"secret-input")
                .unwrap_err()
                .code,
            Code::Stopped
        );
        assert!(!format!("{error:?}").contains("secret-input"));
    }
}

#[test]
fn maximum_body_and_four_neighbors_are_bounded() {
    let mut ingress = Ingress::new(&clock(0)).unwrap();
    for n in 0..4 {
        let peer = [n; 16];
        ingress.open(peer, &clock(0)).unwrap();
        ingress
            .push(&peer, &clock(0), &(MAX_BODY_BYTES as u32).to_be_bytes())
            .unwrap();
    }
    assert_eq!(ingress.stream_count(), 4);
    assert!(ingress.buffered_capacity() <= 4 * MAX_FRAME_BYTES);
    assert_eq!(
        ingress.open([4; 16], &clock(0)).unwrap_err().code,
        Code::Quota
    );
    let data = vec![42; MAX_BODY_BYTES];
    let progress = ingress.push(&[0; 16], &clock(9999), &data).unwrap();
    assert_eq!(progress.consumed, MAX_BODY_BYTES);
    assert!(progress.complete);
    assert_eq!(ingress.take(&[0; 16], &clock(9999)).unwrap().unwrap(), data);
    ingress.close(&[0; 16]);
    ingress.open([4; 16], &clock(9999)).unwrap();
    assert!(ingress.buffered_capacity() <= 4 * MAX_FRAME_BYTES);
}

#[test]
fn coalesced_frames_stop_at_first_and_never_overwrite_ready_body() {
    let mut ingress = ingress();
    let frames = [0, 0, 0, 1, 7, 0, 0, 0, 2, 8, 9];
    let first = ingress.push(&PEER, &clock(1), &frames).unwrap();
    assert_eq!(
        first,
        Progress {
            consumed: 5,
            complete: true
        }
    );
    assert_eq!(
        ingress
            .push(&PEER, &clock(2), &frames[5..])
            .unwrap_err()
            .code,
        Code::Busy
    );
    assert_eq!(ingress.take(&PEER, &clock(2)).unwrap().unwrap(), [7]);
    let second = ingress.push(&PEER, &clock(3), &frames[5..]).unwrap();
    assert_eq!(
        second,
        Progress {
            consumed: 6,
            complete: true
        }
    );
    assert_eq!(ingress.take(&PEER, &clock(3)).unwrap().unwrap(), [8, 9]);
}

#[test]
fn all_fragment_boundaries_preserve_single_frame() {
    let bytes = [0, 0, 0, 5, 2, 4, 6, 8, 10];
    for split in 0..=bytes.len() {
        let mut ingress = ingress();
        let first = ingress.push(&PEER, &clock(0), &bytes[..split]).unwrap();
        if !first.complete {
            assert!(
                ingress
                    .push(&PEER, &clock(1), &bytes[split..])
                    .unwrap()
                    .complete
            );
        }
        assert_eq!(ingress.take(&PEER, &clock(1)).unwrap().unwrap(), bytes[4..]);
    }
}

#[test]
fn timeout_applies_to_partial_prefix_at_exact_boundary() {
    for now in [10000, 10001] {
        let mut ingress = ingress();
        ingress.push(&PEER, &clock(0), &[0]).unwrap();
        assert_eq!(
            ingress
                .push(&PEER, &clock(now), &[0, 0, 1, 7])
                .unwrap_err()
                .code,
            Code::Expired
        );
        assert_eq!(ingress.stream_count(), 0);
    }
}

#[test]
fn trickle_reopen_and_empty_input_do_not_extend_started_frame() {
    let mut ingress = ingress();
    ingress.push(&PEER, &clock(0), &[0]).unwrap();
    assert_eq!(
        ingress.open(PEER, &clock(4000)).unwrap_err().code,
        Code::Conflict
    );
    ingress.push(&PEER, &clock(5000), &[]).unwrap();
    ingress.push(&PEER, &clock(9999), &[0]).unwrap();
    assert_eq!(ingress.expire(&clock(10000)).unwrap(), vec![PEER]);
    assert_eq!(ingress.buffered_capacity(), 0);
}

#[test]
fn empty_stream_has_no_assembly_deadline_and_next_frame_gets_its_own() {
    let mut ingress = ingress();
    ingress.push(&PEER, &clock(50000), &[]).unwrap();
    assert!(ingress.expire(&clock(60000)).unwrap().is_empty());
    ingress
        .push(&PEER, &clock(60000), &[0, 0, 0, 1, 5])
        .unwrap();
    assert_eq!(ingress.take(&PEER, &clock(60000)).unwrap().unwrap(), [5]);
    ingress.push(&PEER, &clock(60001), &[0]).unwrap();
    assert!(ingress.expire(&clock(70000)).unwrap().is_empty());
    assert_eq!(ingress.expire(&clock(70001)).unwrap(), vec![PEER]);
}

#[test]
fn timeout_maintenance_only_removes_incomplete_expired_streams() {
    let mut ingress = ingress();
    ingress.open([2; 16], &clock(0)).unwrap();
    ingress.open([3; 16], &clock(0)).unwrap();
    ingress.push(&PEER, &clock(0), &[0, 0, 0, 2, 1]).unwrap();
    ingress.push(&[2; 16], &clock(1), &[0, 0, 0, 1, 2]).unwrap();
    assert_eq!(ingress.expire(&clock(10000)).unwrap(), vec![PEER]);
    assert_eq!(ingress.stream_count(), 2);
    assert_eq!(ingress.take(&[2; 16], &clock(10000)).unwrap().unwrap(), [2]);
    assert!(ingress.take(&[3; 16], &clock(10000)).unwrap().is_none());
}

#[test]
fn clock_rollback_or_boot_change_quarantines_all_streams_permanently() {
    for bad in [
        clock(9),
        Clock {
            boot: "another-boot".into(),
            ..clock(10)
        },
        clock(-1),
    ] {
        let mut ingress = ingress();
        ingress.push(&PEER, &clock(10), &[0, 0, 0, 1, 99]).unwrap();
        assert_eq!(
            ingress.take(&PEER, &bad).unwrap_err().code,
            Code::TimeUncertain
        );
        assert_eq!(ingress.stream_count(), 0);
        assert_eq!(ingress.buffered_capacity(), 0);
        assert_eq!(
            ingress.open(PEER, &clock(11)).unwrap_err().code,
            Code::TimeUncertain
        );
        assert_eq!(
            ingress.expire(&clock(12)).unwrap_err().code,
            Code::TimeUncertain
        );
    }
}

#[test]
fn maximum_clock_does_not_overflow_timeout_arithmetic() {
    let mut ingress = Ingress::new(&clock(i64::MAX - 10000)).unwrap();
    ingress.open(PEER, &clock(i64::MAX - 10000)).unwrap();
    ingress.push(&PEER, &clock(i64::MAX - 10000), &[0]).unwrap();
    assert_eq!(ingress.expire(&clock(i64::MAX)).unwrap(), vec![PEER]);
}

#[test]
fn unknown_neighbor_cannot_allocate_or_disturb_existing_stream() {
    let mut ingress = ingress();
    assert_eq!(
        ingress
            .push(&[9; 16], &clock(0), &[0; 128])
            .unwrap_err()
            .code,
        Code::Stopped
    );
    assert_eq!(ingress.stream_count(), 1);
    assert_eq!(ingress.buffered_capacity(), 4);
    assert!(
        ingress
            .push(&PEER, &clock(1), &[0, 0, 0, 1, 3])
            .unwrap()
            .complete
    );
}
