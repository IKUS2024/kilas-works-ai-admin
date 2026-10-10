CREATE TABLE IF NOT EXISTS kilas_trading_control_credentials_v2 (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 session_id TEXT NOT NULL UNIQUE,
 credential_hash TEXT NOT NULL UNIQUE,
 scope TEXT NOT NULL CHECK(scope='DEMO_BOUNDED_RUN_COORDINATION_V2'),
 symbol TEXT NOT NULL CHECK(symbol IN ('GOLD','BTCUSD')),
 server TEXT NOT NULL CHECK(server='XMGlobal-MT5 10'),
 max_run_seconds BIGINT CHECK(max_run_seconds BETWEEN 1 AND 300),
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
);
CREATE TABLE IF NOT EXISTS kilas_trading_controls_v2 (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 revision BIGINT NOT NULL DEFAULT 0,
 command_id TEXT,
 desired_state TEXT NOT NULL DEFAULT 'OFF' CHECK(desired_state IN ('ON','OFF')),
 instrument TEXT NOT NULL DEFAULT 'BTC' CHECK(instrument IN ('GOLD','BTC')),
 lot TEXT NOT NULL DEFAULT '0.01',
 issued_at TEXT,
 command_expires_at TEXT,
 run_seconds BIGINT NOT NULL DEFAULT 0,
 run_expires_at TEXT,
 run_started_at TEXT,
 worker_lease_expires_at TEXT,
 run_status TEXT NOT NULL DEFAULT 'NONE' CHECK(run_status IN ('NONE','PENDING','ACTIVE','ENDED')),
 end_reason TEXT NOT NULL DEFAULT 'NONE',
 worker_session_id TEXT,
 worker_sequence BIGINT NOT NULL DEFAULT 0,
 worker_challenge_hash TEXT,
 worker_challenge_expires TEXT,
 ack_json TEXT,
 ack_received_at TEXT
);
CREATE TABLE IF NOT EXISTS kilas_trading_control_receipts_v2 (
 user_id BIGINT NOT NULL REFERENCES users(id),
 command_id TEXT NOT NULL,
 revision BIGINT NOT NULL,
 payload_hash TEXT NOT NULL,
 intent_json TEXT NOT NULL,
 PRIMARY KEY(user_id,command_id)
);
