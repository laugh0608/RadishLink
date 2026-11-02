use super::clock_domain_tests::{isolation, new_clock, next, strip_v9};
use super::tests::{ACTIVITY, Workspace, clock, relay};
use super::*;

#[test]
fn migration_commit_faults_leave_whole_v8_or_whole_v9() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        s.stop_control_activity(ACTIVITY).unwrap();
        strip_v9(&s);
        drop(s);
        assert!(
            Store::open_version(
                &w.dir,
                Limits::default(),
                clock(1),
                OpenMode::MigrateV8Fault(fault)
            )
            .is_err()
        );
        let c = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        let v: i64 = c
            .pragma_query_value(None, "user_version", |r| r.get(0))
            .unwrap();
        assert_eq!(
            v,
            if fault == TestFault::BeforeCommit {
                8
            } else {
                9
            }
        );
        drop(c);
        let s = if v == 8 {
            Store::migrate_v8(&w.dir, Limits::default(), clock(2)).unwrap()
        } else {
            w.reopen(2)
        };
        s.check_invariants().unwrap();
    }
}

#[test]
fn every_isolation_and_establishment_write_failure_rolls_back_its_step() {
    let first = [
        ("control_activity", "UPDATE", "NEW.stopped=1"),
        ("action_scopes", "UPDATE", "1"),
        ("messages", "UPDATE", "NEW.policy_stopped=1"),
        ("clock_domains", "UPDATE", "NEW.frozen=1"),
    ];
    let second = [
        ("control_activity", "UPDATE", "NEW.archived=1"),
        ("clock_domains", "INSERT", "1"),
        ("clock_domains", "UPDATE", "NEW.successor IS NOT NULL"),
        ("control_activity", "INSERT", "1"),
        ("meta", "UPDATE", "1"),
        ("control_output_rate", "UPDATE", "1"),
    ];
    for (phase, points) in [(1, &first[..]), (2, &second[..])] {
        for (table, event, condition) in points {
            let w = Workspace::new();
            let mut s = w.create();
            s.create_action_scope("ui").unwrap();
            s.receive(relay("old")).unwrap();
            drop(s);
            let mut s =
                Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
            let iso = isolation(&s, "isolate");
            if phase == 2 {
                s.isolate_clock_domain(iso.clone()).unwrap();
            }
            let revision = s.revision().unwrap();
            s.conn.execute_batch(&format!("CREATE TRIGGER fail_domain_write BEFORE {event} ON {table} WHEN {condition} BEGIN SELECT RAISE(FAIL,'synthetic domain write failure'); END;")).unwrap();
            let result = if phase == 1 {
                s.isolate_clock_domain(iso.clone()).map(|_| ())
            } else {
                let r = next(&s, 2);
                s.establish_clock_domain(r).map(|_| ())
            };
            assert!(result.is_err(), "phase={phase} {table} {event}");
            assert_eq!(s.revision().unwrap(), revision);
            let d = s.current_clock_domain().unwrap();
            assert_eq!(d.frozen, phase == 2);
            assert!(d.successor.is_none());
            assert!(!s.activity_status(ACTIVITY).unwrap().unwrap().archived);
            assert!(s.message("old").unwrap().unwrap().payload_present);
            s.conn
                .execute_batch("DROP TRIGGER fail_domain_write;")
                .unwrap();
            if phase == 1 {
                s.isolate_clock_domain(iso).unwrap();
            } else {
                let r = next(&s, 2);
                s.establish_clock_domain(r).unwrap();
            }
        }
    }
}

#[test]
fn commit_unknown_quarantines_owner_and_reopen_queries_stable_outcome() {
    for operation in ["isolate", "establish"] {
        for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
            let w = Workspace::new();
            drop(w.create());
            let mut s =
                Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
            let iso = isolation(&s, "isolate");
            if operation == "establish" {
                s.isolate_clock_domain(iso.clone()).unwrap();
            }
            let request = if operation == "establish" {
                Some(next(&s, 2))
            } else {
                None
            };
            s.fault = Some(fault);
            let result = if let Some(r) = &request {
                s.establish_clock_domain(r.clone()).map(|_| ())
            } else {
                s.isolate_clock_domain(iso.clone()).map(|_| ())
            };
            assert!(result.is_err());
            assert_eq!(s.is_quarantined(), fault == TestFault::AfterCommit);
            drop(s);
            let mut s =
                Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
            let committed = fault == TestFault::AfterCommit;
            if operation == "isolate" {
                assert_eq!(s.current_clock_domain().unwrap().frozen, committed);
                s.isolate_clock_domain(iso).unwrap();
            } else {
                assert_eq!(
                    s.current_clock_domain().unwrap().sequence,
                    if committed { 2 } else { 1 }
                );
                let before = s.revision().unwrap();
                s.establish_clock_domain(request.unwrap()).unwrap();
                if committed {
                    assert_eq!(s.revision().unwrap(), before);
                }
            }
            s.check_invariants().unwrap();
        }
    }
}

#[test]
fn domain_crash_child() {
    let Some(path) = std::env::var_os("RADISHLINK_DOMAIN_TEST_STORE") else {
        return;
    };
    let operation = std::env::var("RADISHLINK_DOMAIN_TEST_OPERATION").unwrap();
    let side = std::env::var("RADISHLINK_DOMAIN_TEST_SIDE").unwrap();
    let fault = if side == "before" {
        TestFault::CrashBeforeCommit
    } else {
        TestFault::CrashAfterCommit
    };
    let dir = Path::new(&path);
    let c = new_clock("boot-b", 0, 200000);
    if operation == "migration" {
        let raw = Connection::open(dir.join("node.sqlite3")).unwrap();
        let revision: i64 = raw
            .query_row("SELECT revision FROM meta", [], |r| r.get(0))
            .unwrap();
        drop(raw);
        let r = IsolateClockDomain {
            domain: INITIAL_CLOCK_DOMAIN,
            activity: Some(ACTIVITY),
            expected_revision: revision,
            reference: "cold-migrate".into(),
        };
        Store::open_version(dir, Limits::default(), c, OpenMode::ColdV8Fault(r, fault)).unwrap();
    } else {
        let mut s = Store::open(dir, Limits::default(), c).unwrap();
        s.fault = Some(fault);
        if operation == "isolate" {
            let r = isolation(&s, "isolate");
            s.isolate_clock_domain(r).unwrap();
        } else {
            let r = next(&s, 2);
            s.establish_clock_domain(r).unwrap();
        }
    }
    panic!("expected controlled domain process exit");
}

#[test]
fn process_exit_on_both_commit_sides_preserves_migration_and_two_step_states() {
    for operation in ["isolate", "establish", "migration"] {
        for (side, exit, committed) in [("before", 71, false), ("after", 72, true)] {
            let w = Workspace::new();
            let s = w.create();
            if operation == "migration" {
                strip_v9(&s);
            }
            drop(s);
            if operation == "establish" {
                let mut s =
                    Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
                let r = isolation(&s, "isolate");
                s.isolate_clock_domain(r).unwrap();
            }
            let status = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--exact",
                    "store::clock_domain_recovery_tests::domain_crash_child",
                    "--nocapture",
                ])
                .env("RADISHLINK_DOMAIN_TEST_STORE", &w.dir)
                .env("RADISHLINK_DOMAIN_TEST_OPERATION", operation)
                .env("RADISHLINK_DOMAIN_TEST_SIDE", side)
                .status()
                .unwrap();
            assert_eq!(status.code(), Some(exit), "{operation} {side}");
            let raw = Connection::open(w.dir.join("node.sqlite3")).unwrap();
            let v: i64 = raw
                .pragma_query_value(None, "user_version", |r| r.get(0))
                .unwrap();
            let revision: i64 = raw
                .query_row("SELECT revision FROM meta", [], |r| r.get(0))
                .unwrap();
            drop(raw);
            let s = if operation == "migration" && !committed {
                assert_eq!(v, 8);
                let r = IsolateClockDomain {
                    domain: INITIAL_CLOCK_DOMAIN,
                    activity: Some(ACTIVITY),
                    expected_revision: revision,
                    reference: "cold-migrate".into(),
                };
                Store::migrate_v8_isolated(
                    &w.dir,
                    Limits::default(),
                    new_clock("boot-b", 0, 200000),
                    r,
                )
                .unwrap()
            } else {
                assert_eq!(v, 9);
                Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap()
            };
            let d = s.current_clock_domain().unwrap();
            if operation == "establish" {
                assert_eq!(d.sequence, if committed { 2 } else { 1 });
                assert_eq!(d.frozen, !committed);
            } else if operation == "isolate" {
                assert_eq!(d.frozen, committed);
            } else {
                assert!(d.frozen);
            }
            s.check_invariants().unwrap();
        }
    }
}
