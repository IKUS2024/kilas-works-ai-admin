-- Additive transport metadata. Existing conversation/message/Customer/Job storage is shared.
CREATE TABLE IF NOT EXISTS kw_core_wa_conversations (
 business_id INTEGER NOT NULL,
 conversation_id TEXT NOT NULL,
 phone_number_id TEXT NOT NULL,
 customer_phone TEXT NOT NULL,
 last_inbound_at BIGINT NOT NULL DEFAULT 0,
 PRIMARY KEY(business_id,conversation_id),
 UNIQUE(business_id,phone_number_id,customer_phone),
 FOREIGN KEY(business_id,conversation_id) REFERENCES kw_web_conversations(business_id,id)
);
CREATE TABLE IF NOT EXISTS kw_core_wa_outbound (
 business_id INTEGER NOT NULL,
 conversation_id TEXT NOT NULL,
 event_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('attempting','accepted','sent','delivered','read','failed','unknown','suppressed')),
 provider_id TEXT,
 error TEXT,
 created_at BIGINT NOT NULL,
 PRIMARY KEY(business_id,conversation_id,event_id),
 UNIQUE(business_id,provider_id),
 FOREIGN KEY(business_id,conversation_id) REFERENCES kw_core_wa_conversations(business_id,conversation_id)
);

CREATE TABLE IF NOT EXISTS kw_core_wa_inbound (
 business_id INTEGER NOT NULL, phone_number_id TEXT NOT NULL, provider_id TEXT NOT NULL,
 conversation_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
 PRIMARY KEY(business_id,phone_number_id,provider_id),
 FOREIGN KEY(business_id,conversation_id) REFERENCES kw_core_wa_conversations(business_id,conversation_id)
);
