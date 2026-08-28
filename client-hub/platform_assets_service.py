"""Kilas-owned global media storage — Business Hub V2, Final Operations Polish (Section 2).

Deliberately separate from `project_files` (which requires a NOT NULL business_id and belongs to
one tenant's project). Talent profile photos are Kilas Works' own media, not owned by any tenant,
so they live here instead — see migrations/0009_ops_polish_*.sql for the full rationale.

Write access is admin-only, enforced at the route layer (routes_admin.py), same trust boundary as
every other admin-only module in this app. Read access (serving the actual image bytes) goes
through a dedicated route that streams from this table by numeric id — never a raw filesystem
path, so there is nothing here for a path-traversal attack to reach.
"""
import db

ASSET_KINDS = ("TALENT_PHOTO",)


def save_asset(kind, filename, mime_type, size_bytes, content_bytes, uploaded_by_user_id):
    assert kind in ASSET_KINDS, f"unknown platform asset kind {kind}"
    return db.insert_returning_id(
        "INSERT INTO platform_assets (kind, original_filename, mime_type, size_bytes, content, "
        "uploaded_by_user_id) VALUES (?, ?, ?, ?, ?, ?)",
        (kind, filename, mime_type, size_bytes, content_bytes, uploaded_by_user_id),
    )


def get_asset(asset_id):
    return db.query_one("SELECT * FROM platform_assets WHERE id = ?", (asset_id,))


def get_asset_meta(asset_id):
    """Same as get_asset() but never pulls the (potentially large) `content` BLOB — use this for
    anything that just needs to check existence/kind without reading the image bytes."""
    return db.query_one(
        "SELECT id, kind, original_filename, mime_type, size_bytes, uploaded_by_user_id, created_at "
        "FROM platform_assets WHERE id = ?",
        (asset_id,),
    )
