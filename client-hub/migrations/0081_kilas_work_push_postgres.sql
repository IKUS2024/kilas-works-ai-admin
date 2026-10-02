CREATE TABLE IF NOT EXISTS kilas_work_push_subscriptions (
 id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 endpoint TEXT NOT NULL UNIQUE, keys_json TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS kilas_work_push_deliveries (
 event_id BIGINT NOT NULL REFERENCES kilas_agent_events(id) ON DELETE CASCADE,
 subscription_id BIGINT NOT NULL REFERENCES kilas_work_push_subscriptions(id) ON DELETE CASCADE,
 state TEXT NOT NULL DEFAULT 'PENDING', attempted_at TIMESTAMPTZ, PRIMARY KEY(event_id,subscription_id)
);
