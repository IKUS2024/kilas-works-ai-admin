CREATE TABLE IF NOT EXISTS kilas_learning_sessions (
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), start_key TEXT NOT NULL,
 target TEXT NOT NULL CHECK(target IN ('en','zh','es')), native TEXT NOT NULL,
 level TEXT NOT NULL CHECK(level IN ('beginner','intermediate','advanced')), voice TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','ENDED')), created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 UNIQUE(user_id,start_key)
);
CREATE INDEX IF NOT EXISTS kilas_learning_owner ON kilas_learning_sessions(user_id,status);
CREATE TABLE IF NOT EXISTS kilas_learning_cancelled_starts (
 user_id INTEGER NOT NULL REFERENCES users(id), start_key TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(user_id,start_key)
);
CREATE TABLE IF NOT EXISTS kilas_learning_turns (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES kilas_learning_sessions(id), fingerprint TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PROCESSING','COMPLETED','FAILED','CANCELLED')),
 input_text TEXT, output_text TEXT, error_code TEXT, audio_job_id INTEGER REFERENCES kilas_audio_jobs(id),
 created_at TEXT NOT NULL, timings TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS kilas_learning_turn_session ON kilas_learning_turns(session_id,created_at);
CREATE TABLE IF NOT EXISTS kilas_learning_clips (
 turn_id TEXT NOT NULL REFERENCES kilas_learning_turns(id), sequence INTEGER NOT NULL CHECK(sequence>=0),
 chars INTEGER NOT NULL, duration_ms INTEGER NOT NULL DEFAULT 0, audio BYTEA,
 dispatched_at TEXT NOT NULL, PRIMARY KEY(turn_id,sequence)
);

CREATE TABLE IF NOT EXISTS kilas_learning_inputs (
 turn_id TEXT PRIMARY KEY REFERENCES kilas_learning_turns(id),
 status TEXT NOT NULL CHECK(status IN ('WAITING','STREAMING','COMMITTING','DONE','FAILED','CANCELLED')),
 next_chunk INTEGER NOT NULL DEFAULT 0, sent_chunk INTEGER NOT NULL DEFAULT 0,
 audio_bytes INTEGER NOT NULL DEFAULT 0, charge_micro INTEGER NOT NULL, dispatched INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, first_final_ms INTEGER
);
CREATE TABLE IF NOT EXISTS kilas_learning_input_chunks (
 turn_id TEXT NOT NULL REFERENCES kilas_learning_inputs(turn_id), sequence INTEGER NOT NULL,
 fingerprint TEXT NOT NULL, pcm BYTEA, PRIMARY KEY(turn_id,sequence)
);
