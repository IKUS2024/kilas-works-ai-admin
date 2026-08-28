-- Business Hub V2, Phase D (PostgreSQL dialect). HONESTY NOTE: hand-translated, untested against a
-- real Postgres instance from this sandbox. ADDITIVE ONLY.

CREATE TABLE IF NOT EXISTS talents (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    social_handle TEXT,
    platform TEXT NOT NULL DEFAULT 'Instagram',
    follower_count BIGINT,
    niche TEXT,
    bio TEXT,
    profile_image_file_id BIGINT REFERENCES project_files(id),
    availability_status TEXT NOT NULL DEFAULT 'AVAILABLE',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    public_notes TEXT,
    internal_notes TEXT,
    pricing_mode TEXT NOT NULL DEFAULT 'CUSTOM_QUOTE',
    internal_rate BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS talent_requests (
    id BIGSERIAL PRIMARY KEY,
    talent_id BIGINT NOT NULL REFERENCES talents(id),
    business_id BIGINT NOT NULL REFERENCES businesses(id),
    project_id BIGINT REFERENCES projects(id),
    campaign_type TEXT,
    platform TEXT,
    deliverables TEXT,
    num_content_pieces INTEGER,
    posting_requirements TEXT,
    target_date TEXT,
    location TEXT,
    usage_purpose TEXT,
    budget BIGINT,
    brief TEXT,
    status TEXT NOT NULL DEFAULT 'WAITING_FOR_REVIEW',
    created_by_user_id BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_talents_active ON talents(is_active);
CREATE INDEX IF NOT EXISTS idx_talent_requests_business ON talent_requests(business_id);
CREATE INDEX IF NOT EXISTS idx_talent_requests_talent ON talent_requests(talent_id);
