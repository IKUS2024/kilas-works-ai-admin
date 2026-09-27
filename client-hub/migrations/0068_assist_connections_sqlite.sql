-- Operational evidence only. tenant_whatsapp_config remains the mapping authority.
CREATE TABLE IF NOT EXISTS kw_assist_connections (
 business_id INTEGER PRIMARY KEY REFERENCES businesses(id),
 state TEXT NOT NULL CHECK(state IN ('Pending','Processing','Waiting OTP','Connected','Error','Disconnected')),
 requested_phone TEXT NOT NULL, display_phone_number TEXT,
 mapping_fingerprint TEXT, version INTEGER NOT NULL DEFAULT 1,
 challenge_hash TEXT, challenge_until TEXT, inbound_event_id TEXT, inbound_at TEXT,
 outbound_event_id TEXT, outbound_state TEXT, outbound_at TEXT,
 last_error TEXT, operator_id INTEGER REFERENCES users(id), updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kw_assist_connection_deliveries (
 provider_id TEXT PRIMARY KEY, business_id INTEGER NOT NULL REFERENCES businesses(id),
 mapping_fingerprint TEXT NOT NULL, status TEXT NOT NULL, received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS kw_assist_connection_queue ON kw_assist_connections(state, updated_at);
