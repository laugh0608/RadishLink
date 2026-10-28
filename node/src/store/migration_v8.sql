-- Explicit stopped v7 -> v8. Legacy sessions/actions retain facts without authority.
CREATE TABLE control_activity_v8 (
 id INTEGER PRIMARY KEY CHECK(id>0),
 activity BLOB NOT NULL UNIQUE CHECK(length(activity)=32),
 local_participant BLOB NOT NULL CHECK(length(local_participant)=16),
 boot TEXT NOT NULL, started INTEGER NOT NULL CHECK(started>=0),
 deadline INTEGER NOT NULL CHECK(deadline>started AND deadline-started<=43200000),
 stopped INTEGER NOT NULL DEFAULT 0 CHECK(stopped IN (0,1)),
 exit_credential BLOB CHECK(length(exit_credential)=32),
 exit_operation BLOB CHECK(length(exit_operation)=16),
 exit_ref BLOB CHECK(length(exit_ref)=32),
 exit_payload BLOB CHECK(length(exit_payload) BETWEEN 1 AND 512),
 exit_reason INTEGER CHECK(exit_reason BETWEEN 0 AND 3),
 policy_revision INTEGER NOT NULL DEFAULT 0 CHECK(policy_revision>=0),
 archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 closed_ms INTEGER CHECK(closed_ms>=started),
 successor BLOB UNIQUE CHECK(length(successor)=32),
 final_rate TEXT CHECK(length(final_rate)<=2048),
 CHECK((archived=0 AND closed_ms IS NULL AND successor IS NULL AND final_rate IS NULL)
 OR (archived=1 AND stopped=1 AND closed_ms IS NOT NULL AND successor IS NOT NULL AND final_rate IS NOT NULL)),
 CHECK((exit_credential IS NULL AND exit_operation IS NULL AND exit_ref IS NULL AND exit_payload IS NULL AND exit_reason IS NULL)
    OR (exit_credential IS NOT NULL AND exit_operation IS NOT NULL AND exit_ref IS NOT NULL AND exit_payload IS NOT NULL AND exit_reason IS NOT NULL))
) STRICT;
CREATE TABLE control_bindings_v8 (
 activity BLOB NOT NULL REFERENCES control_activity_v8(activity) CHECK(length(activity)=32),
 credential BLOB PRIMARY KEY CHECK(length(credential)=32),
 participant BLOB NOT NULL CHECK(length(participant)=16),
 generation INTEGER NOT NULL CHECK(generation BETWEEN 1 AND 4),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 160),
 state TEXT NOT NULL CHECK(state IN ('pending','active','blocked','retiring')),
 UNIQUE(participant,generation)
) STRICT;
CREATE UNIQUE INDEX control_one_pending_v8 ON control_bindings_v8(participant) WHERE state='pending';
CREATE UNIQUE INDEX control_one_active_v8 ON control_bindings_v8(participant) WHERE state IN ('active','retiring');
CREATE TABLE control_objects_v8 (
 activity BLOB NOT NULL REFERENCES control_activity_v8(activity) CHECK(length(activity)=32),
 reference BLOB PRIMARY KEY CHECK(length(reference)=32),
 kind INTEGER NOT NULL CHECK(kind IN (2,3)),
 issuer BLOB NOT NULL REFERENCES control_bindings_v8(credential),
 reporter BLOB NOT NULL CHECK(length(reporter)=16),
 target BLOB NOT NULL REFERENCES control_bindings_v8(credential),
 operation BLOB NOT NULL CHECK(length(operation)=16),
 reason INTEGER NOT NULL CHECK(reason BETWEEN 0 AND 3),
 payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 512),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 512),
 accepted INTEGER NOT NULL CHECK(accepted>=0),
 UNIQUE(issuer,operation),
 CHECK((kind=2 AND issuer=target) OR (kind=3 AND issuer!=target))
) STRICT;
CREATE UNIQUE INDEX control_exit_slot_v8 ON control_objects_v8(target) WHERE kind=2;
CREATE UNIQUE INDEX control_report_slot_v8 ON control_objects_v8(reporter,target) WHERE kind=3;
CREATE TABLE control_neighbors_v8 (
 activity BLOB NOT NULL REFERENCES control_activity_v8(activity) CHECK(length(activity)=32),
 object BLOB NOT NULL REFERENCES control_objects_v8(reference),
 participant BLOB NOT NULL CHECK(length(participant)=16),
 start INTEGER NOT NULL CHECK(start>=0),
 next_slot INTEGER NOT NULL DEFAULT 0 CHECK(next_slot BETWEEN 0 AND 8),
 recoveries INTEGER NOT NULL DEFAULT 0 CHECK(recoveries BETWEEN 0 AND 2),
 last_recovery INTEGER CHECK(last_recovery>=start),
 link_up INTEGER NOT NULL CHECK(link_up IN (0,1)),
 terminal INTEGER NOT NULL DEFAULT 0 CHECK(terminal IN (0,1)),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 10),
 ack_attempts INTEGER NOT NULL DEFAULT 0 CHECK(ack_attempts BETWEEN 0 AND 10),
 last_ms INTEGER CHECK(last_ms>=start),
 last_event TEXT CHECK(length(last_event)<=256),
 PRIMARY KEY(object,participant),
 CHECK((last_ms IS NULL)=(last_event IS NULL)),
 CHECK((recoveries=0)=(last_recovery IS NULL)),
 CHECK(attempts<=next_slot+recoveries),
 CHECK(last_recovery IS NULL OR (last_ms IS NOT NULL AND last_recovery<=last_ms))
) STRICT;
INSERT INTO control_activity_v8(id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision) SELECT id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision FROM control_activity;
INSERT INTO control_bindings_v8(activity,credential,participant,generation,body,state) SELECT (SELECT activity FROM control_activity WHERE id=1),credential,participant,generation,body,state FROM control_bindings;
INSERT INTO control_objects_v8(activity,reference,kind,issuer,reporter,target,operation,reason,payload,body,accepted) SELECT (SELECT activity FROM control_activity WHERE id=1),reference,kind,issuer,reporter,target,operation,reason,payload,body,accepted FROM control_objects;
INSERT INTO control_neighbors_v8(activity,object,participant,start,next_slot,recoveries,last_recovery,link_up,terminal,attempts,ack_attempts,last_ms,last_event) SELECT (SELECT activity FROM control_activity WHERE id=1),object,participant,start,next_slot,recoveries,last_recovery,link_up,terminal,attempts,ack_attempts,last_ms,last_event FROM control_neighbors;
DROP TABLE control_neighbors;
DROP TABLE control_objects;
DROP TABLE control_bindings;
DROP TABLE control_activity;
ALTER TABLE control_activity_v8 RENAME TO control_activity;
ALTER TABLE control_bindings_v8 RENAME TO control_bindings;
ALTER TABLE control_objects_v8 RENAME TO control_objects;
ALTER TABLE control_neighbors_v8 RENAME TO control_neighbors;
ALTER TABLE meta ADD COLUMN current_activity BLOB REFERENCES control_activity(activity);
UPDATE meta SET current_activity=(SELECT activity FROM control_activity WHERE id=1);
ALTER TABLE action_scopes ADD COLUMN activity BLOB REFERENCES control_activity(activity);
ALTER TABLE action_scopes ADD COLUMN retired INTEGER NOT NULL DEFAULT 1 CHECK(retired IN (0,1));
CREATE TABLE security_states_v8 (
 activity BLOB NOT NULL CHECK(length(activity) IN (0,32)),
 session TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0),
 state BLOB NOT NULL CHECK(length(state) BETWEEN 1 AND 65536),
 PRIMARY KEY(activity,session)
) STRICT;
INSERT INTO security_states_v8 SELECT X'',session,revision,state FROM security_states;
DROP TABLE security_states;
ALTER TABLE security_states_v8 RENAME TO security_states;
CREATE INDEX control_binding_activity ON control_bindings(activity,participant);
CREATE INDEX control_object_activity ON control_objects(activity,kind);
CREATE INDEX control_neighbor_activity ON control_neighbors(activity);
CREATE INDEX action_scope_activity ON action_scopes(activity);
CREATE VIEW current_control_activity AS SELECT 1 AS id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision FROM control_activity WHERE activity=(SELECT current_activity FROM meta WHERE id=1);
CREATE VIEW current_control_bindings AS SELECT * FROM control_bindings WHERE activity=(SELECT current_activity FROM meta WHERE id=1);
CREATE VIEW current_control_objects AS SELECT * FROM control_objects WHERE activity=(SELECT current_activity FROM meta WHERE id=1);
CREATE VIEW current_control_neighbors AS SELECT * FROM control_neighbors WHERE activity=(SELECT current_activity FROM meta WHERE id=1);
CREATE TRIGGER control_activity_archive_update BEFORE UPDATE ON control_activity WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_activity_archive_delete BEFORE DELETE ON control_activity WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_bindings_archive_update BEFORE UPDATE ON control_bindings WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_bindings_archive_delete BEFORE DELETE ON control_bindings WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_objects_archive_update BEFORE UPDATE ON control_objects WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_objects_archive_delete BEFORE DELETE ON control_objects WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_neighbors_archive_update BEFORE UPDATE ON control_neighbors WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE TRIGGER control_neighbors_archive_delete BEFORE DELETE ON control_neighbors WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived control is immutable'); END;
CREATE VIEW activity_archive_usage AS SELECT
 (SELECT count(*)*4096 FROM control_activity WHERE archived=1)+
 (SELECT count(*)*1024 FROM control_bindings b JOIN control_activity a ON a.activity=b.activity WHERE a.archived=1)+
 (SELECT count(*)*4096 FROM control_objects o JOIN control_activity a ON a.activity=o.activity WHERE a.archived=1)+
 (SELECT count(*)*512 FROM control_neighbors n JOIN control_activity a ON a.activity=n.activity WHERE a.archived=1) AS bytes,
 (SELECT count(*) FROM control_activity WHERE archived=1)+
 (SELECT count(*) FROM control_bindings b JOIN control_activity a ON a.activity=b.activity WHERE a.archived=1)+
 (SELECT count(*) FROM control_objects o JOIN control_activity a ON a.activity=o.activity WHERE a.archived=1)+
 (SELECT count(*) FROM control_neighbors n JOIN control_activity a ON a.activity=n.activity WHERE a.archived=1) AS records;

CREATE TRIGGER control_bindings_current_insert BEFORE INSERT ON control_bindings WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER control_objects_current_insert BEFORE INSERT ON control_objects WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER control_neighbors_current_insert BEFORE INSERT ON control_neighbors WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER security_states_current_insert BEFORE INSERT ON security_states WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER security_states_archive_update BEFORE UPDATE ON security_states WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived session is immutable'); END;
CREATE TRIGGER security_states_archive_delete BEFORE DELETE ON security_states WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived session is immutable'); END;
PRAGMA user_version = 8;
