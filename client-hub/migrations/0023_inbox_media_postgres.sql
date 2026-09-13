CREATE TABLE IF NOT EXISTS inbox_media (
 id TEXT PRIMARY KEY,
 scope_key TEXT NOT NULL,
 event_id TEXT NOT NULL,
 message_row_id BIGINT,
 media_id TEXT NOT NULL,
 message_type TEXT NOT NULL,
 mime_type TEXT NOT NULL,
 filename TEXT NOT NULL,
 caption TEXT NOT NULL,
 created_at TIMESTAMP NOT NULL,
 UNIQUE (scope_key, event_id)
);
CREATE INDEX IF NOT EXISTS inbox_media_message_idx ON inbox_media (scope_key, message_row_id);
