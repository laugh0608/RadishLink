-- v5 -> v6. No policy/channel authority is inferred for existing messages.
ALTER TABLE control_activity ADD COLUMN policy_revision INTEGER NOT NULL DEFAULT 0 CHECK(policy_revision>=0);
ALTER TABLE messages ADD COLUMN policy_revision INTEGER CHECK(policy_revision>=0);
ALTER TABLE messages ADD COLUMN local_credential BLOB CHECK(length(local_credential)=32);
ALTER TABLE messages ADD COLUMN policy_stopped INTEGER NOT NULL DEFAULT 1 CHECK(policy_stopped IN (0,1));
PRAGMA user_version = 6;
