use super::tests::{ACTIVITY, Workspace, clock, relay, send, test_credential};
use super::*;

/// Reconstruct the actual historical v8 DDL for migration fixtures, not a product downgrade.
pub(super) fn strip_v9(store: &Store) {
    if store.schema_version().unwrap() != 9 {
        return;
    }
    let count: i64 = store
        .conn
        .query_row("SELECT count(*) FROM clock_domains", [], |r| r.get(0))
        .unwrap();
    assert_eq!(
        count, 1,
        "legacy fixtures cannot discard multiple clock domains"
    );
    let legacy = Connection::open_in_memory().unwrap();
    for sql in [
        include_str!("schema.sql"),
        include_str!("migration_v2.sql"),
        include_str!("migration_v3.sql"),
        include_str!("migration_v4.sql"),
        include_str!("migration_v5.sql"),
        include_str!("migration_v6.sql"),
        include_str!("migration_v7.sql"),
        include_str!("migration_v8.sql"),
    ] {
        legacy.execute_batch(sql).unwrap();
    }
    let tables = [
        "control_activity",
        "control_bindings",
        "control_objects",
        "control_neighbors",
        "meta",
        "action_scopes",
        "actions",
    ];
    let mut definitions = Vec::new();
    for table in tables {
        let columns = legacy
            .prepare(&format!("PRAGMA table_info({table})"))
            .unwrap()
            .query_map([], |r| r.get::<_, String>(1))
            .unwrap()
            .collect::<std::result::Result<Vec<_>, _>>()
            .unwrap()
            .join(",");
        let select = if table == "meta" {
            "m.id,m.revision,c.boot,c.monotonic_ms,c.unix_ms,m.limits,c.unix_upper_ms,m.current_activity FROM meta m JOIN current_clock c ON c.id=m.id".to_owned()
        } else {
            format!("{columns} FROM {table}")
        };
        store
            .conn
            .execute_batch(&format!(
                "CREATE TEMP TABLE saved9_{table} AS SELECT {select};"
            ))
            .unwrap();
        let ddl: String = legacy
            .query_row(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?1",
                [table],
                |r| r.get(0),
            )
            .unwrap();
        definitions.push((table, columns, ddl));
    }
    let triggers: Vec<String> = store
        .conn
        .prepare("SELECT name FROM sqlite_master WHERE type='trigger'")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .collect::<std::result::Result<_, _>>()
        .unwrap();
    for name in triggers {
        store
            .conn
            .execute_batch(&format!("DROP TRIGGER {name};"))
            .unwrap();
    }
    for name in [
        "current_control_neighbors",
        "current_control_objects",
        "current_control_bindings",
        "current_control_activity",
        "activity_archive_usage",
        "current_clock",
    ] {
        store
            .conn
            .execute_batch(&format!("DROP VIEW {name};"))
            .unwrap();
    }
    store.conn.execute_batch("DROP INDEX message_domain_deadline; ALTER TABLE message_data DROP COLUMN domain_id; ALTER TABLE messages DROP COLUMN domain_id;").unwrap();
    for table in [
        "actions",
        "action_scopes",
        "control_neighbors",
        "control_objects",
        "control_bindings",
        "meta",
        "control_activity",
        "clock_domains",
    ] {
        store
            .conn
            .execute_batch(&format!("DROP TABLE {table};"))
            .unwrap();
    }
    for (_, _, ddl) in &definitions {
        store.conn.execute_batch(ddl).unwrap();
    }
    for (table, columns, _) in &definitions {
        store.conn.execute_batch(&format!("INSERT INTO {table}({columns}) SELECT * FROM saved9_{table}; DROP TABLE saved9_{table};")).unwrap();
    }
    let schema:Vec<(String,String)>=legacy.prepare("SELECT tbl_name,sql FROM sqlite_master WHERE type IN ('index','view','trigger') AND sql IS NOT NULL").unwrap().query_map([],|r|Ok((r.get(0)?,r.get(1)?))).unwrap().collect::<std::result::Result<_,_>>().unwrap();
    for (table, sql) in schema {
        // Existing non-rebuilt business tables already retain their indexes/triggers.
        if tables.contains(&table.as_str())
            || sql.starts_with("CREATE VIEW")
            || sql.starts_with("CREATE TRIGGER")
        {
            store.conn.execute_batch(&sql).unwrap();
        }
    }
    store.conn.execute_batch("PRAGMA user_version=8;").unwrap();
}

pub(super) fn new_clock(boot: &str, mono: i64, wall: i64) -> Clock {
    Clock {
        boot: boot.into(),
        monotonic_ms: mono,
        trusted_utc: Some(crate::data::UtcInterval {
            lower_ms: wall,
            upper_ms: wall,
        }),
    }
}
pub(super) fn isolation(s: &Store, reference: &str) -> IsolateClockDomain {
    IsolateClockDomain {
        domain: s.current_domain_id().unwrap(),
        activity: s.optional_current_activity().unwrap(),
        expected_revision: s.revision().unwrap(),
        reference: reference.into(),
    }
}
pub(super) fn next(s: &Store, n: u8) -> NewClockDomainActivity {
    let d = s.current_clock_domain().unwrap();
    NewClockDomainActivity {
        source: d.domain,
        isolated_revision: d.isolated_revision.unwrap(),
        reference: format!("new-{n}"),
        domain: [n; 32],
        sequence: d.sequence + 1,
        boot: s.clock.boot.clone(),
        activity: [n + 10; 32],
        local_participant: [n + 10; 16],
        started_ms: s.clock.monotonic_ms,
        deadline_ms: s.clock.monotonic_ms + 100000,
    }
}

#[test]
fn cold_isolation_and_new_domain_preserve_old_responsibilities_and_history() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(5000)).unwrap();
    s.receive(relay("old")).unwrap();
    s.create_action_scope("ui").unwrap();
    s.submit(send("sent", "one", 0)).unwrap();
    let saved = s.message_core("old").unwrap().unwrap();
    let old: (i64, i64, Vec<u8>) = s
        .conn
        .query_row(
            "SELECT deadline,retain_until,payload FROM messages WHERE key='old'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 1, 200000)).unwrap();
    let req = isolation(&s, "isolate");
    s.isolate_clock_domain(req.clone()).unwrap();
    assert!(s.current_clock_domain().unwrap().frozen && s.is_time_uncertain());
    let revision = s.revision().unwrap();
    s.isolate_clock_domain(req).unwrap();
    assert_eq!(s.revision().unwrap(), revision);
    let r = next(&s, 2);
    s.establish_clock_domain(r.clone()).unwrap();
    assert!(!s.is_time_uncertain());
    assert_eq!(s.establish_clock_domain(r).unwrap().activity, [12; 32]);
    assert!(s.message_core("old").unwrap().unwrap() == saved);
    assert!(s.action("ui", 1, "one").is_err());
    assert_eq!(
        s.message_remaining_ms("old").unwrap_err().code,
        Code::TimeUncertain
    );
    assert!(s.submit(send("new", "two", 0)).is_err());
    s.maintain(new_clock("boot-b", 30000, 230000)).unwrap();
    let after: (i64, i64, Vec<u8>) = s
        .conn
        .query_row(
            "SELECT deadline,retain_until,payload FROM messages WHERE key='old'",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .unwrap();
    assert_eq!(old, after);
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
    assert_eq!(s.history(0, 100).unwrap().len(), 1);
    assert!(s.activity_status(ACTIVITY).unwrap().unwrap().archived);
    drop(s);
    let s = Store::open(
        &w.dir,
        Limits::default(),
        new_clock("boot-b", 30000, 230000),
    )
    .unwrap();
    assert!(!s.is_time_uncertain());
    assert_eq!(s.current_clock_domain().unwrap().sequence, 2);
}

#[test]
fn stopped_v8_migration_is_explicit_and_source_version_is_checked() {
    let w = Workspace::new();
    let mut s = w.create();
    s.stop_control_activity(ACTIVITY).unwrap();
    strip_v9(&s);
    drop(s);
    assert_eq!(
        Store::open(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::MigrationRequired
    );
    let s = Store::migrate_v8(&w.dir, Limits::default(), clock(1)).unwrap();
    assert_eq!(s.schema_version().unwrap(), 9);
    assert!(s.activity_status(ACTIVITY).unwrap().unwrap().stopped);
    drop(s);
    assert_eq!(
        Store::migrate_v8(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
}

#[test]
fn fresh_activity_can_commit_business_only_after_new_bindings_and_scope() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("old", "old-ref", 0)).unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 1, 200000)).unwrap();
    let req = isolation(&s, "stop-old");
    s.isolate_clock_domain(req).unwrap();
    let req = next(&s, 2);
    s.establish_clock_domain(req.clone()).unwrap();
    assert_eq!(s.renew_action_scope("ui", 1).unwrap(), 2);
    for n in 12..=16 {
        s.stage_control_binding(
            req.activity,
            ControlBinding {
                participant: [n; 16],
                credential: test_credential(n),
                generation: 1,
                body: vec![n, 1],
            },
        )
        .unwrap();
        s.activate_control_binding(req.activity, test_credential(n), &[n, 1])
            .unwrap();
    }
    let mut input = send("new", "new-ref", 0);
    input.action.generation = 2;
    input.message.data.identity.activity_id = req.activity;
    input.message.data.identity.origin_id = [12; 16];
    input.message.data.identity.origin_credential_ref = test_credential(12);
    input.message.data.destination_id = [14; 16];
    input.message.data.destination_credential_ref = test_credential(14);
    input.message.data.originated_at_ms = 200000;
    input.message.deadline_ms = 10001;
    input.message.retain_until_ms = 20001;
    input.neighbor = credential_key(&test_credential(13));
    s.submit(input).unwrap();
    assert!(s.action("ui", 2, "new-ref").unwrap().is_some());
    assert!(s.action("ui", 1, "old-ref").is_err());
    let states: i64 = s
        .conn
        .query_row(
            "SELECT count(*) FROM security_states WHERE session='session'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(states, 2);
    let revisions: Vec<i64> = s
        .conn
        .prepare("SELECT revision FROM security_states WHERE session='session'")
        .unwrap()
        .query_map([], |r| r.get(0))
        .unwrap()
        .collect::<std::result::Result<_, _>>()
        .unwrap();
    assert_eq!(revisions, vec![1, 1]);
}

#[test]
fn no_previous_activity_and_empty_activity_are_charged_differently() {
    for has_activity in [false, true] {
        let w = Workspace::new();
        let mut s = w.create_bare();
        if has_activity {
            s.start_control_activity(ACTIVITY, [1; 16], MAX_ACTIVITY_MS)
                .unwrap();
        }
        drop(s);
        let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
        let req = isolation(&s, "isolate");
        assert_eq!(req.activity.is_some(), has_activity);
        s.isolate_clock_domain(req).unwrap();
        let p = s.preflight_clock_domain().unwrap();
        assert_eq!(p.archive_bytes, if has_activity { 8192 } else { 4096 });
        assert_eq!(p.archive_records, if has_activity { 2 } else { 1 });
        let req = next(&s, 2);
        s.establish_clock_domain(req).unwrap();
        let u = s.usage().unwrap();
        assert_eq!(u.archived_control_bytes, p.archive_bytes);
        assert_eq!(u.archived_control_records, p.archive_records);
        assert_eq!(s.activity_status(ACTIVITY).unwrap().is_some(), has_activity);
        s.check_invariants().unwrap();
    }
}

#[test]
fn changed_request_parameters_conflict_and_repeated_outcomes_do_not_write() {
    let w = Workspace::new();
    drop(w.create());
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&s, "isolate");
    s.isolate_clock_domain(r.clone()).unwrap();
    let mut changed = r.clone();
    changed.expected_revision += 1;
    assert_eq!(
        s.isolate_clock_domain(changed).unwrap_err().code,
        Code::Conflict
    );
    let before = s.revision().unwrap();
    let mut alternate = r;
    alternate.reference = "query-isolated".into();
    s.isolate_clock_domain(alternate).unwrap();
    assert_eq!(s.revision().unwrap(), before);
    let r = next(&s, 2);
    s.establish_clock_domain(r.clone()).unwrap();
    let committed = s.revision().unwrap();
    for field in 0..7 {
        let mut changed = r.clone();
        match field {
            0 => changed.deadline_ms += 1,
            1 => changed.local_participant = [99; 16],
            2 => changed.domain = [99; 32],
            3 => changed.boot = "changed".into(),
            4 => changed.sequence += 1,
            5 => changed.isolated_revision += 1,
            _ => changed.reference = "different".into(),
        };
        assert_eq!(
            s.establish_clock_domain(changed).unwrap_err().code,
            Code::Conflict
        );
        assert_eq!(s.revision().unwrap(), committed);
    }
    s.establish_clock_domain(r).unwrap();
    assert_eq!(s.revision().unwrap(), committed);
}

#[test]
fn missing_or_regressing_utc_can_isolate_but_cannot_establish_domain() {
    for sample in [
        None,
        Some(crate::data::UtcInterval {
            lower_ms: 99999,
            upper_ms: 99999,
        }),
    ] {
        let w = Workspace::new();
        drop(w.create());
        let mut c = new_clock("boot-b", 0, 200000);
        c.trusted_utc = sample;
        let mut s = Store::open(&w.dir, Limits::default(), c).unwrap();
        let r = isolation(&s, "isolate");
        s.isolate_clock_domain(r).unwrap();
        let r = next(&s, 2);
        assert_eq!(
            s.establish_clock_domain(r).unwrap_err().code,
            Code::TimeUncertain
        );
        assert!(s.current_clock_domain().unwrap().frozen);
        assert_eq!(
            s.advance_clock(new_clock("boot-b", 1, 200001))
                .unwrap_err()
                .code,
            Code::TimeUncertain
        );
        drop(s);
        let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 1, 200001)).unwrap();
        let r = next(&s, 2);
        s.establish_clock_domain(r).unwrap();
    }
}

#[test]
fn same_boot_rollback_and_identity_reuse_never_create_new_authority() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(100)).unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), clock(0)).unwrap();
    let r = isolation(&s, "not-a-new-boot");
    assert_eq!(
        s.isolate_clock_domain(r).unwrap_err().code,
        Code::TimeUncertain
    );
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&s, "isolate");
    s.isolate_clock_domain(r).unwrap();
    for kind in 0..4 {
        let mut r = next(&s, 2);
        match kind {
            0 => r.domain = INITIAL_CLOCK_DOMAIN,
            1 => r.activity = ACTIVITY,
            2 => r.local_participant = [2; 16],
            _ => r.boot = "test-boot".into(),
        };
        assert!(matches!(
            s.establish_clock_domain(r).unwrap_err().code,
            Code::Conflict | Code::TimeUncertain
        ));
        assert!(s.current_clock_domain().unwrap().frozen);
    }
    let mut r = next(&s, 2);
    r.sequence = i64::MAX;
    assert_eq!(s.establish_clock_domain(r).unwrap_err().code, Code::Quota);
    let mut r = next(&s, 2);
    r.reference = "x".repeat(257);
    assert_eq!(
        s.establish_clock_domain(r).unwrap_err().code,
        Code::InvalidInput
    );
}

#[test]
fn another_boot_between_steps_neither_invents_nor_skips_domains() {
    let w = Workspace::new();
    drop(w.create());
    let mut b = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&b, "isolate-a");
    b.isolate_clock_domain(r).unwrap();
    drop(b);
    let mut c = Store::open(&w.dir, Limits::default(), new_clock("boot-c", 0, 300000)).unwrap();
    let r = next(&c, 2);
    c.establish_clock_domain(r).unwrap();
    let observed: String = c
        .conn
        .query_row(
            "SELECT json_extract(isolation,'$.observed_boot') FROM clock_domains WHERE sequence=1",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(observed, "boot-b");
    assert_eq!(c.current_clock_domain().unwrap().boot, "boot-c");
    let count: i64 = c
        .conn
        .query_row("SELECT count(*) FROM clock_domains", [], |r| r.get(0))
        .unwrap();
    assert_eq!(count, 2);
    drop(c);
    let mut d = Store::open(&w.dir, Limits::default(), new_clock("boot-d", 0, 400000)).unwrap();
    let r = isolation(&d, "isolate-c");
    d.isolate_clock_domain(r).unwrap();
    let r = next(&d, 3);
    d.establish_clock_domain(r).unwrap();
    assert_eq!(d.current_clock_domain().unwrap().sequence, 3);
    let first = d
        .clock_domain_status(INITIAL_CLOCK_DOMAIN)
        .unwrap()
        .unwrap();
    assert_eq!(first.successor, Some([2; 32]));
    d.check_invariants().unwrap();
}

#[test]
fn domain_archive_exact_byte_record_limits_and_full_quota_isolation() {
    for dimension in 0..3 {
        for short in [false, true] {
            let w = Workspace::new();
            let mut limits = Limits {
                control_bytes: CONTROL_RESERVED_BYTES + 8192,
                control_count: CONTROL_RESERVED_RECORDS + 2,
                record_count: CONTROL_RESERVED_RECORDS + 2,
                ..Limits::default()
            };
            if short {
                match dimension {
                    0 => limits.control_bytes -= 1,
                    1 => limits.control_count -= 1,
                    _ => limits.record_count -= 1,
                };
            }
            let mut s = Store::create(&w.dir, limits.clone(), clock(0)).unwrap();
            s.start_control_activity(ACTIVITY, [1; 16], MAX_ACTIVITY_MS)
                .unwrap();
            drop(s);
            let mut s = Store::open(&w.dir, limits, new_clock("boot-b", 0, 200000)).unwrap();
            let r = isolation(&s, "isolate");
            s.isolate_clock_domain(r).unwrap();
            let r = next(&s, 2);
            let result = s.establish_clock_domain(r);
            if short {
                assert_eq!(result.unwrap_err().code, Code::Quota);
                assert!(s.current_clock_domain().unwrap().frozen);
            } else {
                result.unwrap();
                assert_eq!(s.usage().unwrap().archived_control_bytes, 8192);
            }
        }
    }
    let w = Workspace::new();
    let limits = Limits {
        control_bytes: CONTROL_RESERVED_BYTES,
        control_count: CONTROL_RESERVED_RECORDS,
        record_count: CONTROL_RESERVED_RECORDS,
        ..Limits::default()
    };
    let s = Store::create(&w.dir, limits.clone(), clock(0)).unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, limits, new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&s, "full-isolate");
    s.isolate_clock_domain(r).unwrap();
    let r = next(&s, 2);
    assert_eq!(s.establish_clock_domain(r).unwrap_err().code, Code::Quota);
}

#[test]
fn cold_v8_migration_preserves_running_source_and_explicitly_isolates_it() {
    let w = Workspace::new();
    let mut s = w.create();
    s.receive(relay("old")).unwrap();
    let r = isolation(&s, "cold-migrate");
    strip_v9(&s);
    drop(s);
    assert_eq!(
        Store::migrate_v8(&w.dir, Limits::default(), clock(1))
            .err()
            .unwrap()
            .code,
        Code::Conflict
    );
    let mut s =
        Store::migrate_v8_isolated(&w.dir, Limits::default(), new_clock("boot-b", 1, 200000), r)
            .unwrap();
    assert_eq!(s.schema_version().unwrap(), 9);
    assert!(s.current_clock_domain().unwrap().frozen);
    assert!(s.message("old").unwrap().unwrap().payload_present);
    let r = next(&s, 2);
    s.establish_clock_domain(r).unwrap();
    assert_eq!(s.usage().unwrap().reserved_control_count, 1);
}

#[test]
fn frozen_facts_cannot_be_modified_and_old_corruption_is_not_filtered_out() {
    for corrupt in [
        None,
        Some("UPDATE message_data SET boot='corrupt' WHERE message_key='old'"),
        Some("UPDATE clock_domains SET unix_ms=NULL,unix_upper_ms=NULL WHERE sequence=2"),
        Some("UPDATE clock_domains SET unix_ms=0,unix_upper_ms=0 WHERE sequence=2"),
    ] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("old")).unwrap();
        drop(s);
        let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
        let r = isolation(&s, "isolate");
        s.isolate_clock_domain(r).unwrap();
        let r = next(&s, 2);
        s.establish_clock_domain(r).unwrap();
        assert!(
            s.conn
                .execute(
                    "UPDATE clock_domains SET monotonic_ms=monotonic_ms+1 WHERE sequence=1",
                    []
                )
                .is_err()
        );
        assert!(
            s.conn
                .execute("DELETE FROM clock_domains WHERE sequence=1", [])
                .is_err()
        );
        assert!(s.conn.execute("UPDATE control_activity SET policy_revision=policy_revision+1 WHERE archived=1",[]).is_err());
        if let Some(sql) = corrupt {
            s.conn.execute(sql, []).unwrap();
            drop(s);
            assert_eq!(
                Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000))
                    .err()
                    .unwrap()
                    .code,
                Code::StoreCorrupt
            );
        } else {
            s.check_invariants().unwrap();
        }
    }
}

#[test]
fn history_expiry_uses_utc_without_deleting_frozen_payload_or_markers() {
    let w = Workspace::new();
    let mut s = w.create();
    s.create_action_scope("ui").unwrap();
    s.submit(send("old", "old", 0)).unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&s, "isolate");
    s.isolate_clock_domain(r).unwrap();
    let r = next(&s, 2);
    s.establish_clock_domain(r).unwrap();
    let expiry: i64 = s
        .conn
        .query_row("SELECT expires FROM history", [], |r| r.get(0))
        .unwrap();
    assert_eq!(
        s.maintain(new_clock("boot-b", 1, expiry - 1))
            .unwrap()
            .deleted_history,
        0
    );
    assert_eq!(
        s.maintain(new_clock("boot-b", 2, expiry))
            .unwrap()
            .deleted_history,
        1
    );
    assert!(s.message("old").unwrap().unwrap().payload_present);
    assert_eq!(
        s.conn
            .query_row("SELECT count(*) FROM actions", [], |r| r.get::<_, i64>(0))
            .unwrap(),
        1
    );
    assert!(s.message_core("old").unwrap().is_some());
}

#[test]
fn request_references_cannot_be_rebound_to_a_different_source_domain() {
    let w = Workspace::new();
    drop(w.create());
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&s, "first-isolation");
    s.isolate_clock_domain(r).unwrap();
    let r = next(&s, 2);
    let used = r.reference.clone();
    s.establish_clock_domain(r).unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-c", 0, 300000)).unwrap();
    let r = isolation(&s, "first-isolation");
    assert_eq!(s.isolate_clock_domain(r).unwrap_err().code, Code::Conflict);
    assert!(!s.current_clock_domain().unwrap().frozen);
    let r = isolation(&s, "second-isolation");
    s.isolate_clock_domain(r).unwrap();
    let mut r = next(&s, 3);
    r.reference = used;
    assert_eq!(
        s.establish_clock_domain(r).unwrap_err().code,
        Code::Conflict
    );
    assert!(s.current_clock_domain().unwrap().frozen);
    let r = next(&s, 3);
    s.establish_clock_domain(r).unwrap();
}

#[test]
fn old_verification_job_cannot_enter_a_new_domain_owner() {
    let w = Workspace::new();
    let mut s = w.create();
    s.advance_clock(clock(1000)).unwrap();
    assert_eq!(
        s.queue_control_candidate(ACTIVITY, test_credential(2), b"synthetic unverified")
            .unwrap(),
        ControlIngressAdmission::Queued
    );
    let job = s.next_control_verification().unwrap().job.unwrap();
    drop(s);
    let mut s = Store::open(&w.dir, Limits::default(), new_clock("boot-b", 0, 200000)).unwrap();
    let r = isolation(&s, "isolate");
    s.isolate_clock_domain(r).unwrap();
    let r = next(&s, 2);
    s.establish_clock_domain(r).unwrap();
    assert_eq!(
        s.complete_control_verification(job, ControlVerificationOutcome::Rejected, &[])
            .unwrap_err()
            .code,
        Code::Conflict
    );
    assert_eq!(s.control_ingress_usage().verifying, 0);
}

#[test]
fn equal_and_larger_new_monotonic_coordinates_do_not_expire_old_payload() {
    for mono in [0, 50000] {
        let w = Workspace::new();
        let mut s = w.create();
        s.receive(relay("old")).unwrap();
        drop(s);
        let mut s =
            Store::open(&w.dir, Limits::default(), new_clock("boot-b", mono, 200000)).unwrap();
        let r = isolation(&s, "isolate");
        s.isolate_clock_domain(r).unwrap();
        let r = next(&s, 2);
        s.establish_clock_domain(r).unwrap();
        let report = s.maintain(new_clock("boot-b", mono, 200000)).unwrap();
        assert_eq!(report.expired_payloads, 0);
        assert!(!report.more_due);
        assert!(s.message("old").unwrap().unwrap().payload_present);
    }
}
