-- Business Hub V2, Final Operations Polish (SQLite dialect). ADDITIVE ONLY.
--
-- platform_assets: a NEW, minimal table for Kilas-owned global media (currently: talent profile
-- photos) that does NOT belong to any single tenant business. The existing project_files table
-- can't be reused for this: its business_id column is NOT NULL, and Kilas Works' own talents
-- aren't owned by any tenant business — inventing a fake "internal business" purely to satisfy
-- that FK would be new, unrelated surface area for a solo-founder catalog of a few hand-managed
-- talents. This table is the clean alternative: no business_id at all, admin-only write access
-- (enforced at the route layer, same as everywhere else), served through a dedicated route that
-- never exposes a raw filesystem path.
CREATE TABLE IF NOT EXISTS platform_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                     -- e.g. 'TALENT_PHOTO' — reserved for future kinds
    original_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content BLOB NOT NULL,
    uploaded_by_user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Talent Management, final ops polish: display order (admin-manageable, "1 Putri / 2 Irene / 3
-- Bimo" style), an optional human-readable availability note ("Available after 15 September"),
-- and a direct-upload image pointer (profile_photo_url from the previous cycle stays as an
-- optional fallback — see talent_service.py).
ALTER TABLE talents ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0;
ALTER TABLE talents ADD COLUMN availability_note TEXT;
ALTER TABLE talents ADD COLUMN profile_image_asset_id INTEGER REFERENCES platform_assets(id);

-- Service catalog, final ops polish: an optional short customer-facing CTA/short copy line,
-- separate from the longer `description` field. sort_order already exists (migration 0004) and is
-- reused as-is for "admin-manageable display order" — no new column needed for that.
ALTER TABLE service_catalog ADD COLUMN cta_text TEXT;

-- Audit log, final ops polish: an optional project_id so admin can pull a clean, filtered history
-- for one project (quote created/changed/approved/rejected, payment proof uploaded/verified/
-- rejected, status changes) without parsing free-text `detail` strings. Nullable and additive —
-- every existing audit_log row and every existing write_audit() call site keeps working unchanged.
ALTER TABLE audit_log ADD COLUMN project_id INTEGER REFERENCES projects(id);

CREATE INDEX IF NOT EXISTS idx_audit_log_project ON audit_log(project_id);
