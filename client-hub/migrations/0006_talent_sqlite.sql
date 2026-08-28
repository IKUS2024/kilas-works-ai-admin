-- Business Hub V2, Phase D (SQLite dialect) — Talent Management V1. ADDITIVE ONLY.

CREATE TABLE IF NOT EXISTS talents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    social_handle TEXT,
    platform TEXT NOT NULL DEFAULT 'Instagram',
    follower_count INTEGER,               -- manually editable, NOT realtime-synced (section 14)
    niche TEXT,
    bio TEXT,
    profile_image_file_id INTEGER REFERENCES project_files(id),
    availability_status TEXT NOT NULL DEFAULT 'AVAILABLE',  -- AVAILABLE|LIMITED|UNAVAILABLE
    is_active INTEGER NOT NULL DEFAULT 1,
    public_notes TEXT,                    -- shown to customers, e.g. "Follower count dapat berubah."
    internal_notes TEXT,                  -- admin-only
    pricing_mode TEXT NOT NULL DEFAULT 'CUSTOM_QUOTE',  -- always CUSTOM_QUOTE publicly (section 14)
    internal_rate INTEGER,                -- admin-only reference figure, NEVER exposed publicly
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS talent_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talent_id INTEGER NOT NULL REFERENCES talents(id),
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    project_id INTEGER REFERENCES projects(id),  -- linked once WAITING_FOR_REVIEW -> a project row is created
    campaign_type TEXT,
    platform TEXT,
    deliverables TEXT,
    num_content_pieces INTEGER,
    posting_requirements TEXT,
    target_date TEXT,
    location TEXT,
    usage_purpose TEXT,
    budget INTEGER,
    brief TEXT,
    status TEXT NOT NULL DEFAULT 'WAITING_FOR_REVIEW',
    -- WAITING_FOR_REVIEW -> WAITING_FOR_QUOTE -> QUOTED -> APPROVED -> ... (mirrors projects.status)
    created_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_talents_active ON talents(is_active);
CREATE INDEX IF NOT EXISTS idx_talent_requests_business ON talent_requests(business_id);
CREATE INDEX IF NOT EXISTS idx_talent_requests_talent ON talent_requests(talent_id);
