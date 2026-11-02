-- Explicit v8 -> v9. The source coordinate remains a persisted fact, not a platform Clock.
CREATE TABLE clock_domains (
 domain_id BLOB PRIMARY KEY CHECK(length(domain_id)=32), sequence INTEGER NOT NULL UNIQUE CHECK(sequence>0),
 boot TEXT NOT NULL UNIQUE CHECK(length(boot) BETWEEN 1 AND 64),
 monotonic_ms INTEGER NOT NULL CHECK(monotonic_ms>=0), unix_ms INTEGER CHECK(unix_ms>=0),
 unix_upper_ms INTEGER CHECK(unix_upper_ms>=unix_ms AND unix_upper_ms-unix_ms<=2000),
 frozen INTEGER NOT NULL DEFAULT 0 CHECK(frozen IN (0,1)),
 isolation TEXT CHECK(length(isolation)<=1024), successor BLOB UNIQUE REFERENCES clock_domains(domain_id),
 transition TEXT CHECK(length(transition)<=2048),
 CHECK((unix_ms IS NULL)=(unix_upper_ms IS NULL)),
 CHECK((frozen=0 AND isolation IS NULL AND successor IS NULL AND transition IS NULL)
 OR (frozen=1 AND isolation IS NOT NULL AND ((successor IS NULL AND transition IS NULL) OR (successor IS NOT NULL AND transition IS NOT NULL))))
) STRICT;
CREATE UNIQUE INDEX clock_one_active ON clock_domains(frozen) WHERE frozen=0;
CREATE UNIQUE INDEX clock_isolation_reference ON clock_domains(json_extract(isolation,'$.request.reference')) WHERE isolation IS NOT NULL;
CREATE UNIQUE INDEX clock_transition_reference ON clock_domains(json_extract(transition,'$.reference')) WHERE transition IS NOT NULL;
INSERT INTO clock_domains(domain_id,sequence,boot,monotonic_ms,unix_ms,unix_upper_ms) SELECT X'0000000000000000000000000000000000000000000000000000000000000000',1,boot,monotonic_ms,unix_ms,unix_upper_ms FROM meta;
CREATE TABLE control_activity_v9 (
 id INTEGER PRIMARY KEY CHECK(id>0), activity BLOB NOT NULL UNIQUE CHECK(length(activity)=32),
 local_participant BLOB NOT NULL CHECK(length(local_participant)=16),
 boot TEXT NOT NULL, started INTEGER NOT NULL CHECK(started>=0),
 deadline INTEGER NOT NULL CHECK(deadline>started AND deadline-started<=43200000),
 stopped INTEGER NOT NULL DEFAULT 0 CHECK(stopped IN (0,1)),
 exit_credential BLOB CHECK(length(exit_credential)=32), exit_operation BLOB CHECK(length(exit_operation)=16),
 exit_ref BLOB CHECK(length(exit_ref)=32), exit_payload BLOB CHECK(length(exit_payload) BETWEEN 1 AND 512), exit_reason INTEGER CHECK(exit_reason BETWEEN 0 AND 3),
 policy_revision INTEGER NOT NULL DEFAULT 0 CHECK(policy_revision>=0), archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
 closed_ms INTEGER CHECK(closed_ms>=started), successor BLOB UNIQUE CHECK(length(successor)=32), final_rate TEXT CHECK(length(final_rate)<=2048),
 domain_id BLOB NOT NULL REFERENCES clock_domains(domain_id) CHECK(length(domain_id)=32),
 closed_kind TEXT CHECK(closed_kind IN ('same_boot','cross_boot')),
 CHECK((archived=0 AND closed_ms IS NULL AND successor IS NULL AND final_rate IS NULL AND closed_kind IS NULL)
 OR (archived=1 AND stopped=1 AND successor IS NOT NULL AND final_rate IS NOT NULL AND
 ((closed_kind='same_boot' AND closed_ms IS NOT NULL) OR (closed_kind='cross_boot' AND closed_ms IS NULL)))),
 CHECK((exit_credential IS NULL AND exit_operation IS NULL AND exit_ref IS NULL AND exit_payload IS NULL AND exit_reason IS NULL)
 OR (exit_credential IS NOT NULL AND exit_operation IS NOT NULL AND exit_ref IS NOT NULL AND exit_payload IS NOT NULL AND exit_reason IS NOT NULL))
) STRICT;
CREATE TABLE control_bindings_v9 (
 activity BLOB NOT NULL REFERENCES control_activity_v9(activity) CHECK(length(activity)=32),
 credential BLOB PRIMARY KEY CHECK(length(credential)=32),
 participant BLOB NOT NULL CHECK(length(participant)=16),
 generation INTEGER NOT NULL CHECK(generation BETWEEN 1 AND 4),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 160),
 state TEXT NOT NULL CHECK(state IN ('pending','active','blocked','retiring')),
 UNIQUE(participant,generation)
) STRICT;
CREATE TABLE control_objects_v9 (
 activity BLOB NOT NULL REFERENCES control_activity_v9(activity) CHECK(length(activity)=32),
 reference BLOB PRIMARY KEY CHECK(length(reference)=32),
 kind INTEGER NOT NULL CHECK(kind IN (2,3)),
 issuer BLOB NOT NULL REFERENCES control_bindings_v9(credential),
 reporter BLOB NOT NULL CHECK(length(reporter)=16),
 target BLOB NOT NULL REFERENCES control_bindings_v9(credential),
 operation BLOB NOT NULL CHECK(length(operation)=16),
 reason INTEGER NOT NULL CHECK(reason BETWEEN 0 AND 3),
 payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 512),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 512),
 accepted INTEGER NOT NULL CHECK(accepted>=0),
 UNIQUE(issuer,operation),
 CHECK((kind=2 AND issuer=target) OR (kind=3 AND issuer!=target))
) STRICT;
CREATE TABLE control_neighbors_v9 (
 activity BLOB NOT NULL REFERENCES control_activity_v9(activity) CHECK(length(activity)=32),
 object BLOB NOT NULL REFERENCES control_objects_v9(reference),
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
CREATE TABLE action_scopes_v9(scope TEXT PRIMARY KEY,generation INTEGER NOT NULL CHECK(generation>0),activity BLOB REFERENCES control_activity_v9(activity),retired INTEGER NOT NULL DEFAULT 1 CHECK(retired IN (0,1))) STRICT;
CREATE TABLE actions_v9(scope TEXT NOT NULL REFERENCES action_scopes_v9(scope),generation INTEGER NOT NULL CHECK(generation>0),reference TEXT NOT NULL,binding BLOB NOT NULL CHECK(length(binding) BETWEEN 1 AND 512),message_key TEXT NOT NULL REFERENCES messages(key),PRIMARY KEY(scope,generation,reference)) STRICT;
CREATE TABLE meta_v9(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL CHECK(revision>=0),limits TEXT NOT NULL,current_activity BLOB REFERENCES control_activity_v9(activity),current_domain BLOB NOT NULL REFERENCES clock_domains(domain_id)) STRICT;
INSERT INTO control_activity_v9(id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision,archived,closed_ms,successor,final_rate,domain_id,closed_kind) SELECT id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision,archived,closed_ms,successor,final_rate,X'0000000000000000000000000000000000000000000000000000000000000000',CASE WHEN archived=1 THEN 'same_boot' END FROM control_activity;
INSERT INTO control_bindings_v9 SELECT * FROM control_bindings;
INSERT INTO control_objects_v9 SELECT * FROM control_objects;
INSERT INTO control_neighbors_v9 SELECT * FROM control_neighbors;
INSERT INTO action_scopes_v9 SELECT * FROM action_scopes;
INSERT INTO actions_v9 SELECT * FROM actions;
INSERT INTO meta_v9 SELECT id,revision,limits,current_activity,X'0000000000000000000000000000000000000000000000000000000000000000' FROM meta;
DROP TRIGGER control_activity_archive_update;
DROP TRIGGER control_activity_archive_delete;
DROP TRIGGER control_bindings_archive_update;
DROP TRIGGER control_bindings_archive_delete;
DROP TRIGGER control_objects_archive_update;
DROP TRIGGER control_objects_archive_delete;
DROP TRIGGER control_neighbors_archive_update;
DROP TRIGGER control_neighbors_archive_delete;
DROP TRIGGER security_states_archive_update;
DROP TRIGGER security_states_archive_delete;
DROP TRIGGER control_bindings_current_insert;
DROP TRIGGER control_objects_current_insert;
DROP TRIGGER control_neighbors_current_insert;
DROP TRIGGER security_states_current_insert;
DROP VIEW current_control_neighbors;
DROP VIEW current_control_objects;
DROP VIEW current_control_bindings;
DROP VIEW current_control_activity;
DROP VIEW activity_archive_usage;
DROP TABLE actions;
DROP TABLE action_scopes;
DROP TABLE control_neighbors;
DROP TABLE control_objects;
DROP TABLE control_bindings;
DROP TABLE meta;
DROP TABLE control_activity;
ALTER TABLE control_activity_v9 RENAME TO control_activity;
ALTER TABLE control_bindings_v9 RENAME TO control_bindings;
ALTER TABLE control_objects_v9 RENAME TO control_objects;
ALTER TABLE control_neighbors_v9 RENAME TO control_neighbors;
ALTER TABLE action_scopes_v9 RENAME TO action_scopes;
ALTER TABLE actions_v9 RENAME TO actions;
ALTER TABLE meta_v9 RENAME TO meta;
ALTER TABLE messages ADD COLUMN domain_id BLOB REFERENCES clock_domains(domain_id) CHECK(length(domain_id)=32);
UPDATE messages SET domain_id=X'0000000000000000000000000000000000000000000000000000000000000000';
CREATE TRIGGER messages_domain_required_insert BEFORE INSERT ON messages WHEN NEW.domain_id IS NULL BEGIN SELECT RAISE(ABORT,'message domain required'); END;
CREATE TRIGGER messages_domain_required_update BEFORE UPDATE ON messages WHEN NEW.domain_id IS NULL BEGIN SELECT RAISE(ABORT,'message domain required'); END;

ALTER TABLE message_data ADD COLUMN domain_id BLOB REFERENCES clock_domains(domain_id) CHECK(length(domain_id)=32);
UPDATE message_data SET domain_id=X'0000000000000000000000000000000000000000000000000000000000000000';
CREATE TRIGGER message_data_domain_required_insert BEFORE INSERT ON message_data WHEN NEW.domain_id IS NULL BEGIN SELECT RAISE(ABORT,'message domain required'); END;
CREATE TRIGGER message_data_domain_required_update BEFORE UPDATE ON message_data WHEN NEW.domain_id IS NULL BEGIN SELECT RAISE(ABORT,'message domain required'); END;

CREATE INDEX control_binding_activity ON control_bindings(activity,participant);
CREATE INDEX control_object_activity ON control_objects(activity,kind);
CREATE INDEX control_neighbor_activity ON control_neighbors(activity);
CREATE INDEX action_scope_activity ON action_scopes(activity);
CREATE UNIQUE INDEX control_one_pending_v9 ON control_bindings(participant) WHERE state='pending';
CREATE UNIQUE INDEX control_one_active_v9 ON control_bindings(participant) WHERE state IN ('active','retiring');
CREATE UNIQUE INDEX control_exit_slot_v9 ON control_objects(target) WHERE kind=2;
CREATE UNIQUE INDEX control_report_slot_v9 ON control_objects(reporter,target) WHERE kind=3;
CREATE INDEX message_domain_deadline ON messages(domain_id,deadline);
CREATE VIEW current_clock AS SELECT 1 AS id,d.* FROM clock_domains d WHERE domain_id=(SELECT current_domain FROM meta WHERE id=1);
CREATE VIEW current_control_activity AS SELECT 1 AS id,activity,local_participant,boot,started,deadline,stopped,exit_credential,exit_operation,exit_ref,exit_payload,exit_reason,policy_revision,domain_id FROM control_activity WHERE activity=(SELECT current_activity FROM meta WHERE id=1);
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
 (SELECT count(*)*512 FROM control_neighbors n JOIN control_activity a ON a.activity=n.activity WHERE a.archived=1)+(SELECT count(*)*4096 FROM clock_domains WHERE domain_id IS NOT (SELECT current_domain FROM meta WHERE id=1)) AS bytes,
 (SELECT count(*) FROM control_activity WHERE archived=1)+
 (SELECT count(*) FROM control_bindings b JOIN control_activity a ON a.activity=b.activity WHERE a.archived=1)+
 (SELECT count(*) FROM control_objects o JOIN control_activity a ON a.activity=o.activity WHERE a.archived=1)+
 (SELECT count(*) FROM control_neighbors n JOIN control_activity a ON a.activity=n.activity WHERE a.archived=1)+(SELECT count(*) FROM clock_domains WHERE domain_id IS NOT (SELECT current_domain FROM meta WHERE id=1)) AS records;

CREATE TRIGGER control_bindings_current_insert BEFORE INSERT ON control_bindings WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER control_objects_current_insert BEFORE INSERT ON control_objects WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER control_neighbors_current_insert BEFORE INSERT ON control_neighbors WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER security_states_current_insert BEFORE INSERT ON security_states WHEN NEW.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'current activity required'); END;
CREATE TRIGGER security_states_archive_update BEFORE UPDATE ON security_states WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived session is immutable'); END;
CREATE TRIGGER security_states_archive_delete BEFORE DELETE ON security_states WHEN OLD.activity IS NOT (SELECT current_activity FROM meta WHERE id=1) BEGIN SELECT RAISE(ABORT,'archived session is immutable'); END;
CREATE TRIGGER clock_domain_immutable BEFORE UPDATE ON clock_domains WHEN
 NEW.domain_id IS NOT OLD.domain_id OR NEW.sequence!=OLD.sequence OR
 (OLD.frozen=1 AND (NEW.frozen!=1 OR NEW.boot!=OLD.boot OR NEW.monotonic_ms!=OLD.monotonic_ms OR NEW.unix_ms IS NOT OLD.unix_ms OR NEW.unix_upper_ms IS NOT OLD.unix_upper_ms OR NEW.isolation IS NOT OLD.isolation)) OR
 (OLD.successor IS NOT NULL AND (NEW.successor IS NOT OLD.successor OR NEW.transition IS NOT OLD.transition))
 BEGIN SELECT RAISE(ABORT,'frozen clock domain is immutable'); END;
CREATE TRIGGER clock_domain_no_delete BEFORE DELETE ON clock_domains BEGIN SELECT RAISE(ABORT,'clock domain marker is retained'); END;
PRAGMA user_version = 9;
