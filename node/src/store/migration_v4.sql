-- Explicit v3 -> v4. D16 reserves 1 MiB / 576 records inside existing ceilings.
-- No old responsibility is removed; quota validation precedes COMMIT.
CREATE TABLE control_activity (
 id INTEGER PRIMARY KEY CHECK(id=1),
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
 CHECK((exit_credential IS NULL AND exit_operation IS NULL AND exit_ref IS NULL AND exit_payload IS NULL AND exit_reason IS NULL)
    OR (exit_credential IS NOT NULL AND exit_operation IS NOT NULL AND exit_ref IS NOT NULL AND exit_payload IS NOT NULL AND exit_reason IS NOT NULL))
) STRICT;
CREATE TABLE control_bindings (
 credential BLOB PRIMARY KEY CHECK(length(credential)=32),
 participant BLOB NOT NULL CHECK(length(participant)=16),
 generation INTEGER NOT NULL CHECK(generation BETWEEN 1 AND 4),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 160),
 state TEXT NOT NULL CHECK(state IN ('pending','active','blocked','retiring')),
 UNIQUE(participant,generation)
) STRICT;
CREATE UNIQUE INDEX control_one_pending ON control_bindings(participant) WHERE state='pending';
CREATE UNIQUE INDEX control_one_active ON control_bindings(participant) WHERE state IN ('active','retiring');
CREATE TABLE control_objects (
 reference BLOB PRIMARY KEY CHECK(length(reference)=32),
 kind INTEGER NOT NULL CHECK(kind IN (2,3)),
 issuer BLOB NOT NULL REFERENCES control_bindings(credential),
 reporter BLOB NOT NULL CHECK(length(reporter)=16),
 target BLOB NOT NULL REFERENCES control_bindings(credential),
 operation BLOB NOT NULL CHECK(length(operation)=16),
 reason INTEGER NOT NULL CHECK(reason BETWEEN 0 AND 3),
 payload BLOB NOT NULL CHECK(length(payload) BETWEEN 1 AND 512),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 512),
 accepted INTEGER NOT NULL CHECK(accepted>=0),
 UNIQUE(issuer,operation),
 CHECK((kind=2 AND issuer=target) OR (kind=3 AND issuer!=target))
) STRICT;
CREATE UNIQUE INDEX control_exit_slot ON control_objects(target) WHERE kind=2;
CREATE UNIQUE INDEX control_report_slot ON control_objects(reporter,target) WHERE kind=3;
CREATE TABLE control_neighbors (
 object BLOB NOT NULL REFERENCES control_objects(reference),
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
CREATE TABLE control_output_rate (
 id INTEGER PRIMARY KEY CHECK(id=1),
 last_ms INTEGER NOT NULL CHECK(last_ms>=0),
 frames INTEGER NOT NULL CHECK(frames BETWEEN 0 AND 4000),
 bytes INTEGER NOT NULL CHECK(bytes BETWEEN 0 AND 8192000)
) STRICT;
PRAGMA user_version = 4;
