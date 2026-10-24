-- Explicit v2 -> v3: a destination commits an intent before producing a proof.
CREATE TABLE receipt_intents (
 message_key TEXT PRIMARY KEY REFERENCES messages(key),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4096)
) STRICT;
CREATE INDEX message_deadline ON messages(deadline);
-- Every destination row was admitted by T-C. Proof expiry cannot undo that fact.
UPDATE messages SET state='delivered' WHERE role='destination' AND state='expired';
PRAGMA user_version = 3;
