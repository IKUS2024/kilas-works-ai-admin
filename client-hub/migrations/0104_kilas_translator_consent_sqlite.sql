CREATE TABLE IF NOT EXISTS kilas_translator_consents (
 user_id INTEGER NOT NULL REFERENCES users(id), scope TEXT NOT NULL, version TEXT NOT NULL,
 accepted_at TEXT NOT NULL, revoked_at TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(user_id,scope,version)
);
