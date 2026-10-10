CREATE TABLE IF NOT EXISTS kilas_trading_bridges (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 bridge_id TEXT NOT NULL UNIQUE,
 symbol TEXT NOT NULL CHECK(symbol IN ('GOLD','BTCUSD')),
 server TEXT NOT NULL CHECK(server='XMGlobal-MT5 10'),
 pair_hash TEXT UNIQUE,
 pair_expires TEXT NOT NULL,
 token_hash TEXT UNIQUE,
 token_expires TEXT,
 revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
 sequence BIGINT NOT NULL DEFAULT 0,
 challenge_hash TEXT,
 challenge_expires TEXT,
 last_received TEXT,
 terminal_connected INTEGER NOT NULL DEFAULT 0 CHECK(terminal_connected IN (0,1)),
 market_json TEXT,
 advancing INTEGER NOT NULL DEFAULT 0 CHECK(advancing IN (0,1))
);
