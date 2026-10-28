-- v4 -> v5. Legacy rows remain format 0: their missing authenticated fields
-- cannot be reconstructed. They remain queryable but cannot produce output.
ALTER TABLE meta ADD COLUMN unix_upper_ms INTEGER CHECK(unix_upper_ms>=unix_ms);
ALTER TABLE messages ADD COLUMN data_version INTEGER NOT NULL DEFAULT 0 CHECK(data_version IN (0,1));
CREATE TABLE message_data (
 message_key TEXT PRIMARY KEY REFERENCES messages(key),
 version INTEGER NOT NULL CHECK(version=1),
 raw_core BLOB NOT NULL CHECK(length(raw_core) BETWEEN 1 AND 512),
 activity_id BLOB NOT NULL CHECK(length(activity_id)=32),
 origin_id BLOB NOT NULL CHECK(length(origin_id)=16),
 origin_credential_ref BLOB NOT NULL CHECK(length(origin_credential_ref)=32),
 message_id BLOB NOT NULL CHECK(length(message_id)=16),
 destination_id BLOB NOT NULL CHECK(length(destination_id)=16 AND destination_id!=origin_id),
 destination_credential_ref BLOB NOT NULL CHECK(length(destination_credential_ref)=32),
 mls_group_id BLOB NOT NULL CHECK(length(mls_group_id)=32),
 mls_epoch BLOB NOT NULL CHECK(length(mls_epoch)=8),
 originated_at INTEGER NOT NULL CHECK(originated_at>=0),
 lifetime INTEGER NOT NULL CHECK(lifetime BETWEEN 1 AND 3600000),
 initial_hops INTEGER NOT NULL CHECK(initial_hops IN (1,2)),
 boot TEXT NOT NULL,
 admitted_mono INTEGER NOT NULL CHECK(admitted_mono>=0),
 admitted_lower INTEGER NOT NULL CHECK(admitted_lower>=0),
 admitted_upper INTEGER NOT NULL CHECK(admitted_upper>=admitted_lower AND admitted_upper-admitted_lower<=2000),
 deadline_bound INTEGER NOT NULL CHECK(deadline_bound>admitted_mono),
 UNIQUE(activity_id,origin_id,origin_credential_ref,message_id)
) STRICT;
PRAGMA user_version = 5;
