CREATE TABLE IF NOT EXISTS kilas_work_push_subscriptions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 endpoint TEXT NOT NULL UNIQUE, keys_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS kilas_work_push_deliveries (
 event_id INTEGER NOT NULL REFERENCES kilas_agent_events(id) ON DELETE CASCADE,
 subscription_id INTEGER NOT NULL REFERENCES kilas_work_push_subscriptions(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'PENDING', attempted_at TEXT, PRIMARY KEY(event_id,subscription_id)
);
