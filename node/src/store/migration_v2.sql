-- From schema v1: reserve one maximum-size return proof for every live relay.
-- Applied only by explicit migration or inside new-store initialization.
CREATE TABLE control_reservations (
 message_key TEXT PRIMARY KEY REFERENCES messages(key),
 bytes INTEGER NOT NULL CHECK(bytes=4096)
) STRICT;
INSERT INTO control_reservations
 SELECT key,4096 FROM messages WHERE role='relay' AND state='stored';
CREATE INDEX message_expiry ON messages(deadline) WHERE payload IS NOT NULL;
PRAGMA user_version = 2;
