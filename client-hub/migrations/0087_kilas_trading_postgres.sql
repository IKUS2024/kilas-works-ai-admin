CREATE TABLE IF NOT EXISTS kilas_trading_accounts (
 user_id BIGINT PRIMARY KEY REFERENCES users(id),
 initial_cents BIGINT NOT NULL DEFAULT 1000000,
 realized_cents BIGINT NOT NULL DEFAULT 0,
 paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)),
 killed INTEGER NOT NULL DEFAULT 0 CHECK(killed IN (0,1)),
 tick INTEGER NOT NULL DEFAULT 60,
 generated_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'IDLE',
 last_error TEXT NOT NULL DEFAULT '',
 cooldown_until TEXT,
 risk_json TEXT NOT NULL,
 strategy_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kilas_trading_positions (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES kilas_trading_accounts(user_id),
 side TEXT NOT NULL CHECK(side IN ('BUY','SELL')),
 quantity_units BIGINT NOT NULL CHECK(quantity_units>0),
 entry_cents BIGINT NOT NULL CHECK(entry_cents>0),
 stop_cents BIGINT NOT NULL CHECK(stop_cents>0),
 target_cents BIGINT NOT NULL CHECK(target_cents>0),
 trailing_cents BIGINT NOT NULL DEFAULT 0 CHECK(trailing_cents>=0),
 activation_cents BIGINT NOT NULL DEFAULT 0 CHECK(activation_cents>=0),
 breakeven_cents BIGINT NOT NULL DEFAULT 0 CHECK(breakeven_cents>=0),
 entry_fee_cents BIGINT NOT NULL DEFAULT 0 CHECK(entry_fee_cents>=0),
 fee_bps INTEGER NOT NULL DEFAULT 2 CHECK(fee_bps>=0),
 status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED')),
 exit_cents BIGINT,
 pnl_cents BIGINT NOT NULL DEFAULT 0,
 close_reason TEXT,
 opened_at TEXT NOT NULL,
 closed_at TEXT
);
CREATE INDEX IF NOT EXISTS kilas_trading_positions_owner ON kilas_trading_positions(user_id,status);
CREATE TABLE IF NOT EXISTS kilas_trading_events (
 id BIGSERIAL PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES kilas_trading_accounts(user_id),
 operation_key TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 action TEXT NOT NULL,
 outcome TEXT NOT NULL,
 message TEXT NOT NULL,
 inputs_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(user_id,operation_key)
);
CREATE INDEX IF NOT EXISTS kilas_trading_events_owner ON kilas_trading_events(user_id,id);
