use super::tests::{Workspace, clock, relay, strip_v4};
use super::*;
use crate::retry::{Admission, LinkEvent, Signal};
const ACT: ActivityId = [1; 32];
fn pid(n: u8) -> ParticipantId {
    [n; 16]
}
fn cred(n: u8, g: u8) -> CredentialRef {
    let mut c = [n; 32];
    c[31] = g;
    c
}
fn binding(n: u8, g: u8) -> ControlBinding {
    ControlBinding {
        participant: pid(n),
        credential: cred(n, g),
        generation: u32::from(g),
        body: vec![n, g],
    }
}
fn pair(s: &mut Store, n: u8, g: u8) {
    s.stage_control_binding(ACT, binding(n, g)).unwrap();
    s.activate_control_binding(ACT, cred(n, g), &[n, g])
        .unwrap();
}
fn setup() -> (Workspace, Store) {
    let w = Workspace::new();
    let mut s = w.create_bare();
    s.start_control_activity(ACT, pid(1), MAX_ACTIVITY_MS)
        .unwrap();
    for n in 1..=5 {
        pair(&mut s, n, 1);
    }
    s.advance_clock(clock(1000)).unwrap();
    (w, s)
}
fn object(issuer: u8, ig: u8, target: u8, tg: u8, op: u8) -> PreparedControl {
    let kind = if issuer == target {
        ControlKind::Exit
    } else {
        ControlKind::Report
    };
    let mut reference = [op; 32];
    reference[0] = issuer;
    reference[1] = ig;
    reference[2] = target;
    reference[3] = tg;
    PreparedControl {
        fields: ControlPayload {
            activity: ACT,
            kind,
            issuer: cred(issuer, ig),
            issuer_id: pid(issuer),
            target: cred(target, tg),
            target_id: pid(target),
            operation: [op; 16],
            reason: 0,
            reference,
            payload: vec![issuer, ig, target, tg, op],
        },
        cose: vec![7, issuer, ig, target, tg, op],
    }
}
fn neighbor(n: u8) -> ControlNeighbor {
    ControlNeighbor {
        participant: pid(n),
        link: Link::Up,
    }
}
fn event(o: ObjectRef, n: u8) -> ControlEvent {
    ControlEvent {
        object: o,
        neighbor: pid(n),
        link: LinkEvent::Unchanged,
        signal: Signal::Continue,
        admission: Admission::Allow,
    }
}
fn report(s: &mut Store) -> ObjectRef {
    let o = object(2, 1, 3, 1, 1);
    let r = o.fields.reference;
    s.accept_control(o, &[neighbor(4)]).unwrap();
    r
}
fn step(s: &mut Store, r: ObjectRef, now: i64, link: LinkEvent) -> ControlDecision {
    s.process_control_batch(
        ACT,
        clock(now),
        vec![ControlEvent {
            link,
            ..event(r, 4)
        }],
    )
    .unwrap()
    .remove(0)
}
#[test]
fn v4_reservation_is_inside_existing_totals_and_rejects_small_limits_before_create() {
    let w = Workspace::new();
    let s = w.create_bare();
    let u = s.control_usage().unwrap();
    assert_eq!(u.reserved_bytes, 1048576);
    assert_eq!(u.reserved_records, 576);
    assert_eq!(u.used_records, 0);
    assert_eq!((s.limits.control_bytes - u.reserved_bytes) / 4096, 1792);
    let w = Workspace::new();
    let limits = Limits {
        control_bytes: CONTROL_RESERVED_BYTES - 1,
        ..Limits::default()
    };
    assert_eq!(
        Store::create(&w.dir, limits, clock(0)).err().unwrap().code,
        Code::Quota
    );
    assert!(!w.dir.exists());
}
#[test]
fn v3_migration_requires_explicit_call_and_rolls_back_capacity_failure() {
    for enough in [false, true] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        strip_v4(&s);
        let limits = Limits {
            control_bytes: CONTROL_RESERVED_BYTES + if enough { 4096 } else { 4095 },
            ..Limits::default()
        };
        s.conn
            .execute("UPDATE meta SET limits=?1", [limits_json(&limits).unwrap()])
            .unwrap();
        drop(s);
        assert_eq!(
            Store::open(&w.dir, limits.clone(), clock(1))
                .err()
                .unwrap()
                .code,
            Code::MigrationRequired
        );
        let result = Store::migrate_v3(&w.dir, limits, clock(1));
        if enough {
            let s = result.unwrap();
            assert!(s.message("one").unwrap().unwrap().payload_present);
        } else {
            assert_eq!(result.err().unwrap().code, Code::Quota);
        }
        let c = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        let v: i64 = c
            .pragma_query_value(None, "user_version", |r| r.get(0))
            .unwrap();
        assert_eq!(v, if enough { 6 } else { 3 });
        let has: bool = c
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='control_activity')",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(has, enough);
    }
}
#[test]
fn generations_are_bounded_and_replacement_never_reactivates_old_credential() {
    let (_w, mut s) = setup();
    assert_eq!(
        s.stage_control_binding(ACT, binding(6, 1))
            .unwrap_err()
            .code,
        Code::Quota
    );
    assert_eq!(
        s.stage_control_binding(ACT, binding(2, 3))
            .unwrap_err()
            .code,
        Code::Conflict
    );
    for g in 2..=4 {
        for n in 1..=5 {
            pair(&mut s, n, g);
        }
    }
    assert_eq!(s.control_usage().unwrap().bindings, 20);
    assert_eq!(
        s.stage_control_binding(ACT, binding(2, 5))
            .unwrap_err()
            .code,
        Code::InvalidInput
    );
    assert_eq!(
        s.control_binding_state(cred(2, 1)).unwrap(),
        Some(BindingState::Blocked)
    );
    assert_eq!(
        s.activate_control_binding(ACT, cred(2, 1), &[2, 1])
            .unwrap_err()
            .code,
        Code::Conflict
    );
}
#[test]
fn slots_merge_operation_and_key_changes_without_creating_tombstones() {
    let (_w, mut s) = setup();
    let r = report(&mut s);
    let mut conflict = object(2, 1, 3, 1, 1);
    conflict.fields.payload.push(99);
    assert!(matches!(
        s.accept_control(conflict, &[]),
        Err(Error {
            code: Code::Conflict,
            ..
        })
    ));
    assert_eq!(
        s.accept_control(object(2, 1, 3, 1, 2), &[]).unwrap(),
        ControlAdmission::Merged(r)
    );
    pair(&mut s, 2, 2);
    assert_eq!(
        s.accept_control(object(2, 2, 3, 1, 3), &[]).unwrap(),
        ControlAdmission::Merged(r)
    );
    assert_eq!(s.control_usage().unwrap().objects, 1);
    assert_eq!(
        s.control_object(ACT, r).unwrap().unwrap(),
        vec![7, 2, 1, 3, 1, 1]
    );
}
#[test]
fn budget_persists_before_output_and_reopen_or_neighbor_replacement_cannot_refill() {
    let (w, mut s) = setup();
    let r = report(&mut s);
    assert!(step(&mut s, r, 1000, LinkEvent::Unchanged).send);
    let before = s.control_progress(r, pid(4)).unwrap().unwrap();
    drop(s);
    let mut s = w.reopen(1001);
    assert_eq!(s.control_progress(r, pid(4)).unwrap().unwrap(), before);
    assert!(!step(&mut s, r, 1001, LinkEvent::Unchanged).send);
    pair(&mut s, 4, 2);
    s.schedule_control_neighbor(ACT, r, neighbor(4)).unwrap();
    assert_eq!(s.control_progress(r, pid(4)).unwrap().unwrap(), before);
    assert!(step(&mut s, r, 2000, LinkEvent::Unchanged).send);
    assert_eq!(s.control_progress(r, pid(4)).unwrap().unwrap().attempts, 2);
}
#[test]
fn late_slots_are_skipped_and_only_two_spaced_down_up_recoveries_exist() {
    let (_w, mut s) = setup();
    let r = report(&mut s);
    let d = step(&mut s, r, 1801001, LinkEvent::Down);
    assert!(!d.send);
    assert_eq!(d.progress.slots_consumed, 8);
    let d = step(&mut s, r, 1802000, LinkEvent::Up);
    assert!(d.send);
    assert_eq!(d.progress.recoveries_consumed, 1);
    step(&mut s, r, 1802001, LinkEvent::Down);
    assert!(!step(&mut s, r, 1802002, LinkEvent::Up).send);
    step(&mut s, r, 1861999, LinkEvent::Down);
    let d = step(&mut s, r, 1862000, LinkEvent::Up);
    assert!(d.send && d.progress.terminal);
    assert_eq!(d.progress.recoveries_consumed, 2);
    step(&mut s, r, 1900000, LinkEvent::Down);
    assert!(!step(&mut s, r, 2000000, LinkEvent::Up).send);
}
#[test]
fn local_exit_retains_unique_intent_and_commits_block_and_object_atomically() {
    let (w, mut s) = setup();
    s.begin_control_exit(object(1, 1, 1, 1, 9).fields).unwrap();
    assert_eq!(
        s.control_binding_state(cred(1, 1)).unwrap(),
        Some(BindingState::Retiring)
    );
    assert!(s.begin_control_exit(object(1, 1, 1, 1, 10).fields).is_err());
    assert!(s.accept_control(object(1, 1, 1, 1, 10), &[]).is_err());
    assert!(s.stage_control_binding(ACT, binding(1, 2)).is_err());
    s.fault = Some(TestFault::BeforeCommit);
    assert!(
        s.accept_control(object(1, 1, 1, 1, 9), &[neighbor(2)])
            .is_err()
    );
    drop(s);
    let mut s = w.reopen(1001);
    assert_eq!(
        s.control_binding_state(cred(1, 1)).unwrap(),
        Some(BindingState::Retiring)
    );
    assert_eq!(s.control_usage().unwrap().objects, 0);
    assert!(s.control_exit_intent(ACT).unwrap().is_some());
    s.accept_control(object(1, 1, 1, 1, 9), &[neighbor(2)])
        .unwrap();
    assert_eq!(
        s.control_binding_state(cred(1, 1)).unwrap(),
        Some(BindingState::Blocked)
    );
    assert_eq!(s.control_usage().unwrap().objects, 1);
    assert!(s.control_exit_intent(ACT).unwrap().is_none());
}

#[test]
fn report_capacity_and_full_business_budget_do_not_block_owner_or_exit() {
    let (_w, mut s) = setup();
    for g in 2..=4 {
        for n in 1..=5 {
            pair(&mut s, n, g);
        }
    }
    let mut op = 1u8;
    for target in 1..=5 {
        for generation in 1..=4 {
            for issuer in 1..=5 {
                if issuer == target {
                    continue;
                }
                s.accept_control(object(issuer, 4, target, generation, op), &[])
                    .unwrap();
                op += 1;
            }
        }
    }
    assert_eq!(s.control_usage().unwrap().objects, 80);
    // A new operation for an occupied slot cannot create an 81st report.
    assert!(matches!(
        s.accept_control(object(2, 4, 3, 4, 200), &[]).unwrap(),
        ControlAdmission::Merged(_)
    ));
    assert_eq!(s.control_usage().unwrap().objects, 80);
    // Fill the business byte ceiling in one synthetic fixture transaction.
    s.atomic(|s| {
        s.conn.execute_batch("WITH RECURSIVE n(i) AS (VALUES(1) UNION ALL SELECT i+1 FROM n WHERE i<1792)
            INSERT INTO messages(key,origin_ref,core,role,state,payload,deadline,retain_until,hops,source_neighbor) SELECT printf('bulk-%d',i),printf('origin-%d',i%4),x'01','relay','stored',x'02',100000,200000,1,'A' FROM n;
            INSERT INTO control_reservations SELECT key,4096 FROM messages;")?;Ok(())
    }).unwrap();
    let mut overflow = relay("overflow");
    overflow.expected_policy_revision = s.business_policy_revision(ACT).unwrap();
    overflow.message.data.identity.origin_credential_ref = cred(2, 4);
    overflow.message.data.destination_credential_ref = cred(3, 4);
    overflow.neighbor = credential_key(&cred(2, 4));
    assert_eq!(s.receive(overflow).unwrap_err().code, Code::Quota);
    s.block_control_binding(ACT, cred(3, 4)).unwrap();
    s.begin_control_exit(object(1, 4, 1, 4, 201).fields)
        .unwrap();
    s.accept_control(object(1, 4, 1, 4, 201), &[neighbor(2)])
        .unwrap();
    assert_eq!(s.control_usage().unwrap().objects, 81); // 80 reports plus protected own exit.
    assert_eq!(s.usage().unwrap().reserved_control_bytes, 1792 * 4096);
    assert_eq!(
        s.control_binding_state(cred(1, 4)).unwrap(),
        Some(BindingState::Blocked)
    );
}
#[test]
fn pending_conflicts_wrong_fields_and_oversize_inputs_leave_no_partial_records() {
    let (_w, mut s) = setup();
    s.stage_control_binding(ACT, binding(2, 2)).unwrap();
    let mut changed = binding(2, 2);
    changed.body.push(9);
    assert!(s.stage_control_binding(ACT, changed).is_err());
    assert!(
        s.activate_control_binding(ACT, cred(2, 2), b"wrong")
            .is_err()
    );
    assert!(s.accept_control(object(2, 2, 3, 1, 1), &[]).is_err());
    let mut wrong = object(2, 1, 3, 1, 1);
    wrong.fields.target_id = pid(5);
    assert!(s.accept_control(wrong, &[]).is_err());
    let mut large = object(2, 1, 3, 1, 1);
    large.cose = vec![0; 513];
    assert!(s.accept_control(large, &[]).is_err());
    let mut invalid = object(2, 1, 2, 1, 1);
    invalid.fields.target = cred(3, 1);
    assert!(s.accept_control(invalid, &[]).is_err());
    let o = object(2, 1, 3, 1, 1);
    assert!(s.accept_control(o, &[neighbor(6)]).is_err());
    assert_eq!(s.control_usage().unwrap().objects, 0);
    assert_eq!(
        s.control_binding_state(cred(2, 1)).unwrap(),
        Some(BindingState::Active)
    );
}
#[test]
fn deadlines_stop_and_cross_boot_never_restore_control_outputs() {
    let (w, mut s) = setup();
    let r = report(&mut s);
    assert!(
        s.shorten_control_activity(ACT, MAX_ACTIVITY_MS + 1)
            .is_err()
    );
    s.shorten_control_activity(ACT, 2000).unwrap();
    assert!(!step(&mut s, r, 1999, LinkEvent::Unchanged).send);
    assert_eq!(
        s.process_control_batch(ACT, clock(2000), vec![event(r, 4)])
            .err()
            .unwrap()
            .code,
        Code::Expired
    );
    assert_eq!(s.control_progress(r, pid(4)).unwrap().unwrap().attempts, 0);
    s.stop_control_activity(ACT).unwrap();
    assert!(s.start_control_activity(ACT, pid(1), 3000).is_err());
    drop(s);
    let mut other = clock(2001);
    other.boot = "another-boot".into();
    let mut s = Store::open(&w.dir, Limits::default(), other.clone()).unwrap();
    assert!(s.is_time_uncertain());
    assert_eq!(
        s.process_control_batch(ACT, other, vec![event(r, 4)])
            .err()
            .unwrap()
            .code,
        Code::TimeUncertain
    );
    assert!(s.control_object(ACT, r).is_err());
    assert_eq!(s.control_usage().unwrap().objects, 1);
}
#[test]
fn full_ten_attempt_schedule_and_simultaneous_recovery_never_double_send() {
    let (_w, mut s) = setup();
    let r = report(&mut s);
    // Eight exact normal opportunities, two separate down/up recoveries.
    for now in [1000, 2000, 4000, 11000, 31000, 121000, 601000, 1801000] {
        assert!(step(&mut s, r, now, LinkEvent::Unchanged).send);
    }
    step(&mut s, r, 1802000, LinkEvent::Down);
    assert!(step(&mut s, r, 1803000, LinkEvent::Up).send);
    step(&mut s, r, 1862999, LinkEvent::Down);
    let d = step(&mut s, r, 1863000, LinkEvent::Up);
    assert!(d.send);
    assert_eq!(d.progress.attempts, 10);
    assert!(!step(&mut s, r, 2000000, LinkEvent::Unchanged).send);
    let (_w, mut s) = setup();
    let r = report(&mut s);
    step(&mut s, r, 1000, LinkEvent::Down);
    let d = step(&mut s, r, 2000, LinkEvent::Up);
    assert!(d.send);
    assert_eq!(d.progress.attempts, 1);
    assert_eq!(d.progress.slots_consumed, 2);
    assert_eq!(d.progress.recoveries_consumed, 1);
    assert!(!step(&mut s, r, 2000, LinkEvent::Up).send);
}
#[test]
fn batch_conflicts_or_lost_commit_response_cannot_expose_uncommitted_attempts() {
    let (w, mut s) = setup();
    let r = report(&mut s);
    let err = s
        .process_control_batch(
            ACT,
            clock(1000),
            vec![
                ControlEvent {
                    link: LinkEvent::Down,
                    ..event(r, 4)
                },
                ControlEvent {
                    link: LinkEvent::Up,
                    ..event(r, 4)
                },
            ],
        )
        .err()
        .unwrap();
    assert_eq!(err.code, Code::Conflict);
    assert_eq!(
        s.control_progress(r, pid(4))
            .unwrap()
            .unwrap()
            .slots_consumed,
        0
    );
    s.fault = Some(TestFault::BeforeCommit);
    assert!(
        s.process_control_batch(ACT, clock(1000), vec![event(r, 4)])
            .is_err()
    );
    s.fault = None;
    assert_eq!(s.control_progress(r, pid(4)).unwrap().unwrap().attempts, 0);
    s.fault = Some(TestFault::AfterCommit);
    assert_eq!(
        s.process_control_batch(ACT, clock(1000), vec![event(r, 4)])
            .err()
            .unwrap()
            .code,
        Code::OutcomeUnknown
    );
    assert!(s.is_quarantined());
    drop(s);
    let mut s = w.reopen(1000);
    assert_eq!(s.control_progress(r, pid(4)).unwrap().unwrap().attempts, 1);
    assert!(!step(&mut s, r, 1000, LinkEvent::Unchanged).send);
}
#[test]
fn control_ack_is_bounded_and_rate_reconstruction_starts_empty() {
    let (w, mut s) = setup();
    let r = report(&mut s);
    for _ in 0..4 {
        assert!(s.consume_control_ack(ACT, r, pid(4)).unwrap());
    }
    assert!(!s.consume_control_ack(ACT, r, pid(4)).unwrap());
    drop(s);
    let mut s = w.reopen(100000);
    assert!(!s.consume_control_ack(ACT, r, pid(4)).unwrap());
    assert_eq!(
        s.control_progress(r, pid(4)).unwrap().unwrap().ack_attempts,
        4
    );
    for n in 1..=6 {
        s.advance_clock(clock(100000 + n * 250)).unwrap();
        assert!(s.consume_control_ack(ACT, r, pid(4)).unwrap());
    }
    s.advance_clock(clock(102000)).unwrap();
    assert!(!s.consume_control_ack(ACT, r, pid(4)).unwrap());
    assert!(!s.consume_control_ack(ACT, [99; 32], pid(4)).unwrap());
    assert_eq!(s.control_usage().unwrap().neighbors, 1);
}
#[test]
fn authenticated_ack_and_policy_stop_are_terminal_per_neighbor() {
    let (_w, mut s) = setup();
    let r = report(&mut s);
    s.schedule_control_neighbor(ACT, r, neighbor(5)).unwrap();
    let d = s
        .process_control_batch(
            ACT,
            clock(1000),
            vec![
                ControlEvent {
                    signal: Signal::Pause,
                    ..event(r, 4)
                },
                event(r, 5),
            ],
        )
        .unwrap();
    assert!(!d[0].send && d[0].progress.terminal);
    assert!(d[1].send);
    assert!(!step(&mut s, r, 2000, LinkEvent::Unchanged).send);
    s.block_control_binding(ACT, cred(5, 1)).unwrap();
    let d = s
        .process_control_batch(ACT, clock(2000), vec![event(r, 5)])
        .unwrap();
    assert!(!d[0].send && d[0].progress.terminal);
    pair(&mut s, 5, 2);
    let d = s
        .process_control_batch(ACT, clock(4000), vec![event(r, 5)])
        .unwrap();
    assert!(!d[0].send);
}
#[test]
fn remote_exit_blocks_only_issuer_and_retains_exact_forwardable_object() {
    let (_w, mut s) = setup();
    let o = object(2, 1, 2, 1, 1);
    let r = o.fields.reference;
    s.accept_control(o, &[neighbor(4)]).unwrap();
    assert_eq!(
        s.control_binding_state(cred(2, 1)).unwrap(),
        Some(BindingState::Blocked)
    );
    assert_eq!(
        s.control_binding_state(cred(3, 1)).unwrap(),
        Some(BindingState::Active)
    );
    assert!(step(&mut s, r, 1000, LinkEvent::Unchanged).send);
    assert_eq!(
        s.accept_control(object(2, 1, 2, 1, 2), &[]).unwrap(),
        ControlAdmission::Merged(r)
    );
    assert!(s.accept_control(object(2, 1, 3, 1, 3), &[]).is_err());
    assert_eq!(s.control_usage().unwrap().objects, 1);
}
#[test]
fn v3_migration_faults_and_unknown_versions_preserve_source() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("one")).unwrap();
        strip_v4(&s);
        drop(s);
        let e = Store::open_version(
            &w.dir,
            Limits::default(),
            clock(1),
            OpenMode::MigrateV3Fault(fault),
        )
        .err()
        .unwrap();
        assert_eq!(
            e.code,
            if fault == TestFault::BeforeCommit {
                Code::StoreUnavailable
            } else {
                Code::OutcomeUnknown
            }
        );
        let c = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        let v: i64 = c
            .pragma_query_value(None, "user_version", |r| r.get(0))
            .unwrap();
        assert_eq!(
            v,
            if fault == TestFault::BeforeCommit {
                3
            } else {
                6
            }
        );
        let s = if v == 3 {
            Store::migrate_v3(&w.dir, Limits::default(), clock(2)).unwrap()
        } else {
            w.reopen(2)
        };
        assert!(s.message("one").unwrap().unwrap().payload_present);
        assert!(Store::migrate_v3(&w.dir, Limits::default(), clock(3)).is_err()); // still owned
    }
}
#[test]
fn control_crash_child() {
    let Ok(dir) = std::env::var("RADISHLINK_CONTROL_TEST_STORE") else {
        return;
    };
    let operation = std::env::var("RADISHLINK_CONTROL_TEST_OPERATION").unwrap();
    let fault = match std::env::var("RADISHLINK_CONTROL_TEST_SIDE")
        .unwrap()
        .as_str()
    {
        "before" => TestFault::CrashBeforeCommit,
        "after" => TestFault::CrashAfterCommit,
        _ => panic!("test side"),
    };
    if operation == "migrate" {
        Store::open_version(
            Path::new(&dir),
            Limits::default(),
            clock(1000),
            OpenMode::MigrateV3Fault(fault),
        )
        .unwrap();
    } else {
        let mut s = Store::open(Path::new(&dir), Limits::default(), clock(1000)).unwrap();
        // Reopening starts the output bucket empty; let one second elapse before injecting.
        s.advance_clock(clock(2000)).unwrap();
        s.fault = Some(fault);
        match operation.as_str() {
            "attempt" => {
                let r = object(2, 1, 3, 1, 1).fields.reference;
                s.process_control_batch(ACT, clock(2000), vec![event(r, 4)])
                    .unwrap();
            }
            "exit" => {
                s.accept_control(object(1, 1, 1, 1, 9), &[neighbor(2)])
                    .unwrap();
            }
            "intent" => {
                s.begin_control_exit(object(1, 1, 1, 1, 9).fields).unwrap();
            }
            _ => panic!("test operation"),
        }
    }
    panic!("expected controlled process exit");
}
#[test]
fn process_exit_recovers_whole_migration_exit_and_consumed_budget() {
    for operation in ["migrate", "intent", "exit", "attempt"] {
        for (side, code, committed) in [("before", 71, false), ("after", 72, true)] {
            let (w, mut s) = setup();
            match operation {
                "migrate" => {
                    // legacy fixture has no control records
                    s.conn.execute_batch("DELETE FROM control_bindings; DELETE FROM control_output_rate; DELETE FROM control_activity;").unwrap();
                    strip_v4(&s);
                }
                "intent" => {}
                "exit" => s.begin_control_exit(object(1, 1, 1, 1, 9).fields).unwrap(),
                "attempt" => {
                    report(&mut s);
                }
                _ => unreachable!(),
            }
            drop(s);
            let status = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::control_tests::control_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_CONTROL_TEST_STORE", &w.dir)
                .env("RADISHLINK_CONTROL_TEST_OPERATION", operation)
                .env("RADISHLINK_CONTROL_TEST_SIDE", side)
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(code));
            let s = if operation == "migrate" && !committed {
                Store::migrate_v3(&w.dir, Limits::default(), clock(2001)).unwrap()
            } else {
                w.reopen(2001)
            };
            match operation {
                "migrate" => assert_eq!(s.control_usage().unwrap().used_records, 0),
                "intent" => assert_eq!(
                    s.control_binding_state(cred(1, 1)).unwrap(),
                    Some(if committed {
                        BindingState::Retiring
                    } else {
                        BindingState::Active
                    })
                ),
                "exit" => {
                    assert_eq!(
                        s.control_binding_state(cred(1, 1)).unwrap(),
                        Some(if committed {
                            BindingState::Blocked
                        } else {
                            BindingState::Retiring
                        })
                    );
                    assert_eq!(s.control_usage().unwrap().objects, u64::from(committed));
                }
                "attempt" => assert_eq!(
                    s.control_progress(object(2, 1, 3, 1, 1).fields.reference, pid(4))
                        .unwrap()
                        .unwrap()
                        .attempts,
                    u8::from(committed)
                ),
                _ => unreachable!(),
            }
        }
    }
}

#[test]
fn reserve_record_and_byte_edges_preserve_full_proof_charge_after_conversion() {
    for (records, bytes, admitted) in [
        (575, CONTROL_RESERVED_BYTES, false),
        (576, CONTROL_RESERVED_BYTES - 1, false),
        (576, CONTROL_RESERVED_BYTES, true),
    ] {
        let w = Workspace::new();
        let limits = Limits {
            control_count: records,
            control_bytes: bytes,
            ..Limits::default()
        };
        assert_eq!(Store::create(&w.dir, limits, clock(0)).is_ok(), admitted);
    }
    for extra in [4095, 4096] {
        let w = Workspace::new();
        let limits = Limits {
            control_count: 577,
            control_bytes: CONTROL_RESERVED_BYTES + extra,
            record_count: CONTROL_RESERVED_RECORDS + 3,
            ..Limits::default()
        };
        let mut s = Store::create(&w.dir, limits, clock(0)).unwrap();
        super::tests::prepare_business(&mut s);
        if extra == 4095 {
            assert_eq!(s.receive(relay("one")).unwrap_err().code, Code::Quota);
            continue;
        }
        s.receive(relay("one")).unwrap();
        s.finish_delivery(
            "one",
            &super::tests::binding("one"),
            Some((super::tests::PEER_2, b"small-proof")),
            5,
        )
        .unwrap();
        assert_eq!(s.usage().unwrap().evidence_bytes, 11);
        // A shorter proof still owns its 4096-byte logical responsibility.
        assert_eq!(s.receive(relay("two")).unwrap_err().code, Code::Quota);
    }
}
#[test]
fn four_neighbor_slots_and_batch_failure_preserve_all_original_counters() {
    let (_w, mut s) = setup();
    let o = object(2, 1, 3, 1, 1);
    let r = o.fields.reference;
    s.accept_control(o, &[neighbor(2), neighbor(3), neighbor(4), neighbor(5)])
        .unwrap();
    assert_eq!(s.control_usage().unwrap().neighbors, 4);
    assert!(s.schedule_control_neighbor(ACT, r, neighbor(1)).is_err());
    assert!(s.schedule_control_neighbor(ACT, r, neighbor(6)).is_err());
    let before = s.revision().unwrap();
    assert!(
        s.process_control_batch(ACT, clock(1000), vec![event(r, 2), event([88; 32], 3)])
            .is_err()
    );
    assert_eq!(s.revision().unwrap(), before);
    assert_eq!(s.control_progress(r, pid(2)).unwrap().unwrap().attempts, 0);
    let decisions = s
        .process_control_batch(ACT, clock(1000), (2..=5).map(|n| event(r, n)).collect())
        .unwrap();
    assert_eq!(decisions.iter().filter(|d| d.send).count(), 4);
    assert!(!s.consume_control_ack(ACT, r, pid(2)).unwrap());
}
#[test]
fn corruption_of_control_authorization_and_time_is_rejected_on_open() {
    for sql in [
        "UPDATE control_bindings SET state='active' WHERE credential=(SELECT issuer FROM control_objects)",
        "UPDATE control_neighbors SET start=500000",
        "UPDATE control_output_rate SET last_ms=500000",
    ] {
        let (w, mut s) = setup();
        s.accept_control(object(2, 1, 2, 1, 1), &[neighbor(4)])
            .unwrap();
        s.conn.execute_batch(sql).unwrap();
        drop(s);
        assert_eq!(
            Store::open(&w.dir, Limits::default(), clock(1001))
                .err()
                .unwrap()
                .code,
            Code::StoreCorrupt
        );
    }
}
#[test]
fn integer_time_limit_and_activity_start_after_empty_reopen_are_checked() {
    let w = Workspace::new();
    let s = w.create_bare();
    drop(s);
    let mut s = Store::open(
        &w.dir,
        Limits::default(),
        Clock {
            monotonic_ms: i64::MAX - 10,
            ..clock(0)
        },
    )
    .unwrap();
    s.start_control_activity(ACT, pid(1), i64::MAX).unwrap();
    for n in 1..=4 {
        pair(&mut s, n, 1);
    }
    let r = report(&mut s);
    assert!(
        !s.process_control_batch(
            ACT,
            Clock {
                monotonic_ms: i64::MAX - 10,
                trusted_utc: Some(crate::data::UtcInterval {
                    lower_ms: i64::MAX,
                    upper_ms: i64::MAX
                }),
                ..clock(0)
            },
            vec![event(r, 4)]
        )
        .unwrap()[0]
            .send
    );
}
