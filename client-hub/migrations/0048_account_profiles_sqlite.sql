-- Account personal invoice profile + reusable profile-photo links. Additive only.
CREATE TABLE IF NOT EXISTS account_personal_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    tax_id TEXT NOT NULL DEFAULT '',
    website TEXT NOT NULL DEFAULT '',
    payment_method TEXT NOT NULL DEFAULT '',
    payment_bank_name TEXT NOT NULL DEFAULT '',
    payment_account_number TEXT NOT NULL DEFAULT '',
    payment_account_name TEXT NOT NULL DEFAULT '',
    payment_instructions TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_profile_assets (
    owner_type TEXT NOT NULL CHECK(owner_type IN ('USER','BUSINESS')),
    owner_id INTEGER NOT NULL,
    asset_id INTEGER NOT NULL REFERENCES platform_assets(id),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_type, owner_id)
);

CREATE INDEX IF NOT EXISTS idx_account_profile_assets_asset
    ON account_profile_assets(asset_id);
