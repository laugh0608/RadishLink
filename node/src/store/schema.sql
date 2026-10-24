PRAGMA application_id = 1380732491;
PRAGMA user_version = 1;
CREATE TABLE meta (
 id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL CHECK(revision>=0),
 boot TEXT NOT NULL, monotonic_ms INTEGER NOT NULL CHECK(monotonic_ms>=0),
 unix_ms INTEGER CHECK(unix_ms>=0), limits TEXT NOT NULL
) STRICT;
CREATE TABLE security_states (
 session TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>0),
 state BLOB NOT NULL CHECK(length(state) BETWEEN 1 AND 65536)
) STRICT;
CREATE TABLE messages (
 key TEXT PRIMARY KEY, origin_ref TEXT NOT NULL, core BLOB NOT NULL CHECK(length(core) BETWEEN 1 AND 512),
 role TEXT NOT NULL CHECK(role IN ('origin','relay','destination')),
 source_neighbor TEXT,
 state TEXT NOT NULL CHECK(state IN ('queued','stored','committed','delivered','expired')),
 payload BLOB CHECK(length(payload) BETWEEN 1 AND 65536),
 deadline INTEGER NOT NULL CHECK(deadline>=0), retain_until INTEGER NOT NULL CHECK(retain_until>=deadline),
 hops INTEGER NOT NULL CHECK(hops BETWEEN 0 AND 255),
 custody INTEGER NOT NULL DEFAULT 0 CHECK(custody IN (0,1)),
 CHECK((role='origin' AND source_neighbor IS NULL) OR
       (role!='origin' AND source_neighbor IS NOT NULL)),
 CHECK((state IN ('delivered','expired') AND payload IS NULL) OR
       (state NOT IN ('delivered','expired') AND payload IS NOT NULL))
) STRICT;
CREATE TABLE action_scopes (scope TEXT PRIMARY KEY, generation INTEGER NOT NULL CHECK(generation>0)) STRICT;
CREATE TABLE actions (
 scope TEXT NOT NULL REFERENCES action_scopes(scope), generation INTEGER NOT NULL CHECK(generation>0),
 reference TEXT NOT NULL, binding BLOB NOT NULL CHECK(length(binding) BETWEEN 1 AND 512),
 message_key TEXT NOT NULL REFERENCES messages(key), PRIMARY KEY(scope,generation,reference)
) STRICT;
CREATE TABLE queues (
 message_key TEXT NOT NULL REFERENCES messages(key), kind TEXT NOT NULL CHECK(kind IN ('data','evidence')),
 neighbor TEXT NOT NULL, hops INTEGER NOT NULL CHECK(hops BETWEEN 0 AND 255),
 body BLOB NOT NULL CHECK(length(body)<=4096), retry TEXT NOT NULL CHECK(length(retry)<=4096),
 PRIMARY KEY(message_key,kind,neighbor)
) STRICT;
CREATE TABLE history (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, message_key TEXT NOT NULL UNIQUE REFERENCES messages(key),
 body BLOB NOT NULL CHECK(length(body) BETWEEN 1 AND 4096), expires INTEGER NOT NULL CHECK(expires>=0)
) STRICT;
CREATE INDEX history_expiry ON history(expires);
