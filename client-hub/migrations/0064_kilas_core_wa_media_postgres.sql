-- Core WhatsApp Inbox media metadata. Binary data remains at Meta and is fetched on demand.
CREATE TABLE IF NOT EXISTS kw_core_wa_media (
 id TEXT PRIMARY KEY,
 business_id INTEGER NOT NULL,
 conversation_id TEXT NOT NULL,
 event_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','assistant','human')),
 media_id TEXT NOT NULL,
 message_type TEXT NOT NULL CHECK(message_type IN ('image','video','audio','document','sticker')),
 mime_type TEXT NOT NULL,
 filename TEXT NOT NULL,
 caption TEXT NOT NULL,
 created_at BIGINT NOT NULL,
 UNIQUE(business_id,conversation_id,event_id,role),
 FOREIGN KEY(business_id,conversation_id,event_id,role)
   REFERENCES kw_web_messages(business_id,conversation_id,event_id,role)
);
CREATE INDEX IF NOT EXISTS kw_core_wa_media_thread
 ON kw_core_wa_media(business_id,conversation_id,created_at);
