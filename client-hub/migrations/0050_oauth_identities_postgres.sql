CREATE TABLE IF NOT EXISTS oauth_identities (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id),
    email_at_link TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, provider_subject)
);
CREATE INDEX IF NOT EXISTS idx_oauth_identities_user ON oauth_identities(user_id);

CREATE TABLE IF NOT EXISTS oauth_email_aliases (
    id BIGSERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    email TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, email)
);
CREATE INDEX IF NOT EXISTS idx_oauth_alias_user ON oauth_email_aliases(user_id);
