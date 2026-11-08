ALTER TABLE control_objects ADD COLUMN ack_source_credential BLOB
 REFERENCES control_bindings(credential)
 CHECK(ack_source_credential IS NULL OR length(ack_source_credential)=32);

CREATE TRIGGER control_ack_source_immutable
 BEFORE UPDATE OF ack_source_credential ON control_objects
 WHEN OLD.ack_source_credential IS NOT NEW.ack_source_credential
 BEGIN SELECT RAISE(ABORT,'control ACK source is immutable'); END;

PRAGMA user_version = 10;
