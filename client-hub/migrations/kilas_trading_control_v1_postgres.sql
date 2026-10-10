CREATE TABLE IF NOT EXISTS kilas_trading_control_credentials (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 session_id TEXT NOT NULL UNIQUE,
 credential_hash TEXT NOT NULL UNIQUE,
 scope TEXT NOT NULL CHECK(scope='DEMO_CONTROL_COORDINATION_V1'),
 symbol TEXT NOT NULL CHECK(symbol IN ('GOLD','BTCUSD')),
 server TEXT NOT NULL CHECK(server='XMGlobal-MT5 10'),
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
);
CREATE TABLE IF NOT EXISTS kilas_trading_controls (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 revision BIGINT NOT NULL DEFAULT 0,
 command_id TEXT,
 desired_state TEXT NOT NULL DEFAULT 'OFF' CHECK(desired_state IN ('ON','OFF')),
 instrument TEXT NOT NULL DEFAULT 'BTC' CHECK(instrument IN ('GOLD','BTC')),
 lot TEXT NOT NULL DEFAULT '0.01',
 issued_at TEXT,
 expires_at TEXT,
 worker_session_id TEXT,
 worker_sequence BIGINT NOT NULL DEFAULT 0,
 worker_challenge_hash TEXT,
 worker_challenge_expires TEXT,
 ack_json TEXT,
 ack_received_at TEXT
);
CREATE TABLE IF NOT EXISTS kilas_trading_control_receipts (
 user_id BIGINT NOT NULL REFERENCES users(id),
 command_id TEXT NOT NULL,
 revision BIGINT NOT NULL,
 payload_hash TEXT NOT NULL,
 intent_json TEXT NOT NULL,
 PRIMARY KEY(user_id,command_id)
);
