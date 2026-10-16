-- Additive, isolated text groups. No existing rows or balances are modified.
CREATE TABLE IF NOT EXISTS kilas_chat_groups (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL,
 ai_enabled INTEGER NOT NULL DEFAULT 1 CHECK(ai_enabled IN (0,1)),
 invite_hash TEXT UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kilas_chat_group_members (
 group_id INTEGER NOT NULL REFERENCES kilas_chat_groups(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 state TEXT NOT NULL CHECK(state IN ('ACTIVE','REMOVED')),
 joined_at TEXT NOT NULL,
 PRIMARY KEY(group_id,user_id)
);
CREATE INDEX IF NOT EXISTS kilas_group_member_user ON kilas_chat_group_members(user_id,state,group_id);
CREATE TABLE IF NOT EXISTS kilas_chat_group_operations (
 operation_key TEXT PRIMARY KEY,
 group_id INTEGER NOT NULL REFERENCES kilas_chat_groups(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 fingerprint TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('TEXT','ASK','SUMMARY')),
 status TEXT NOT NULL CHECK(status IN ('PENDING','DISPATCHED','COMPLETE','FAILED')),
 error_code TEXT,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS kilas_group_operation_state ON kilas_chat_group_operations(group_id,status);
CREATE TABLE IF NOT EXISTS kilas_chat_group_messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 group_id INTEGER NOT NULL REFERENCES kilas_chat_groups(id),
 user_id INTEGER REFERENCES users(id),
 role TEXT NOT NULL CHECK(role IN ('user','assistant')),
 content TEXT NOT NULL,
 operation_key TEXT NOT NULL REFERENCES kilas_chat_group_operations(operation_key),
 created_at TEXT NOT NULL,
 UNIQUE(operation_key,role)
);
CREATE INDEX IF NOT EXISTS kilas_group_message_order ON kilas_chat_group_messages(group_id,id);
