-- Replay protection only. Never stores OAuth codes, tokens, PINs or credentials.
CREATE TABLE IF NOT EXISTS whatsapp_signup_sessions (
 business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
 user_id INTEGER NOT NULL REFERENCES users(id),
 state_hash TEXT NOT NULL,
 expires_at BIGINT NOT NULL,
 used BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS whatsapp_signup_lock (id INTEGER PRIMARY KEY CHECK(id=1));
INSERT INTO whatsapp_signup_lock(id) VALUES(1) ON CONFLICT(id) DO NOTHING;
