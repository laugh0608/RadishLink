use super::outbound_cycle_tests::{ack, ack_budget, data, input, keys};
use super::outbound_tests::batch;
use super::tests::{Workspace, clock};
use super::*;

#[test]
fn failed_or_unknown_commit_never_publishes_runtime_progress_or_replays_outputs() {
    for fault in [TestFault::BeforeCommit, TestFault::AfterCommit] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 17);
        let mut cycle = s.start_outbound_cycle().unwrap();
        s.fault = Some(fault);
        let i = input(&s, 1000, vec![ack()]);
        let err = s
            .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
            .err()
            .unwrap();
        assert_eq!(
            err.code,
            if fault == TestFault::BeforeCommit {
                Code::StoreUnavailable
            } else {
                Code::OutcomeUnknown
            }
        );
        assert_eq!(s.is_quarantined(), fault == TestFault::AfterCommit);
        if fault == TestFault::BeforeCommit {
            assert_eq!(ack_budget(&s), "[]");
            s.fault = None;
            let i = input(&s, 1000, vec![ack()]);
            let r = s
                .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
                .unwrap();
            assert_eq!(
                keys(&r),
                (0..16).map(|n| format!("q{n:03}")).collect::<Vec<_>>()
            );
        }
        drop(s);
        let mut s = w.reopen(1001);
        let slots: serde_json::Value = serde_json::from_str(&ack_budget(&s)).unwrap();
        assert_eq!(slots[0]["attempts"], 1);
        let i = input(&s, 1002, vec![]);
        assert_eq!(
            s.process_outbound_cycle(&mut cycle, i, |_| panic!(
                "old owner cannot retry an uncertain response"
            ))
            .err()
            .unwrap()
            .code,
            Code::Conflict
        );
        let mut current = s.start_outbound_cycle().unwrap();
        let i = input(&s, 1002, vec![]);
        let r = s
            .process_outbound_cycle(&mut current, i, |_| Ok(batch(1002)))
            .unwrap();
        assert!(
            r.outbound
                .decisions
                .iter()
                .all(|d| matches!(d,OutboundDecision::Queue(_,d) if !d.send))
        );
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&ack_budget(&s)).unwrap()[0]["attempts"],
            1
        );
    }
}

#[test]
fn cycle_crash_child() {
    let Some(dir) = std::env::var_os("RADISHLINK_CYCLE_TEST_STORE") else {
        return;
    };
    let mut s = Store::open(Path::new(&dir), Limits::default(), clock(0)).unwrap();
    let mut cycle = s.start_outbound_cycle().unwrap();
    s.fault = Some(
        match std::env::var("RADISHLINK_CYCLE_TEST_SIDE")
            .unwrap()
            .as_str()
        {
            "before" => TestFault::CrashBeforeCommit,
            "after" => TestFault::CrashAfterCommit,
            _ => panic!("invalid synthetic side"),
        },
    );
    let i = input(&s, 1000, vec![ack()]);
    s.process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1000)))
        .unwrap();
    panic!("expected controlled process exit");
}

#[test]
fn process_exit_recovers_whole_cycle_and_does_not_restore_runtime_inputs() {
    for (side, code, committed) in [("before", 71, false), ("after", 72, true)] {
        let w = Workspace::new();
        let mut s = w.create();
        data(&mut s, 1);
        drop(s);
        let result = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "store::outbound_cycle_recovery_tests::cycle_crash_child",
                "--nocapture",
            ])
            .env("RADISHLINK_CYCLE_TEST_STORE", &w.dir)
            .env("RADISHLINK_CYCLE_TEST_SIDE", side)
            .status()
            .unwrap();
        assert_eq!(result.code(), Some(code));
        let raw = Connection::open(w.dir.join("node.sqlite3")).unwrap();
        let slot: i64 = raw
            .query_row(
                "SELECT json_extract(retry,'$.next_slot') FROM queues WHERE message_key='q000'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        let floor: i64 = raw
            .query_row("SELECT monotonic_ms FROM current_clock", [], |r| r.get(0))
            .unwrap();
        assert_eq!(slot, if committed { 3 } else { 0 });
        assert_eq!(floor, if committed { 1000 } else { 0 });
        drop(raw);
        let mut s = w.reopen(1001);
        let slots: serde_json::Value = serde_json::from_str(&ack_budget(&s)).unwrap();
        assert_eq!(slots.as_array().unwrap().len(), usize::from(committed));
        let mut cycle = s.start_outbound_cycle().unwrap();
        let i = input(&s, 1002, vec![]);
        let r = s
            .process_outbound_cycle(&mut cycle, i, |_| Ok(batch(1002)))
            .unwrap();
        assert!(
            matches!(&r.outbound.decisions[0],OutboundDecision::Queue(_,d) if d.send!=committed)
        );
        // No ACK input was restored merely by reopening; only prior committed budget remains.
        assert_eq!(
            serde_json::from_str::<serde_json::Value>(&ack_budget(&s)).unwrap(),
            slots
        );
    }
}
