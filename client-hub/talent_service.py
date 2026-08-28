"""Talent Management V1 — Business Hub V2, Phase D (Section 14/15).

Seed data ships here (not hardcoded into any template — Section 14 explicitly requires this) and
is applied idempotently at boot, same pattern as catalog_service.seed_catalog_if_needed(): only
inserts a talent whose name doesn't already exist, never overwrites an admin's edits (follower
count, availability, etc.) on an existing row.
"""
import json

import db
import repo

SEED_TALENTS = [
    {"name": "Putri Maudy", "social_handle": "@pm__bae", "follower_count": 186_000,
     "niche": "Lifestyle"},
    {"name": "Irene Agustine Moire", "social_handle": "@irene_agustine", "follower_count": 1_500_000,
     "niche": "Lifestyle"},
    {"name": "Bimo Putra Dwitya", "social_handle": "@bimopd", "follower_count": 2_000_000,
     "niche": "Lifestyle"},
]

PUBLIC_DISCLAIMER = "Follower count dapat berubah. Harga dan ketersediaan tergantung kebutuhan campaign."

# BUSY added in Final Operations Polish (Section 4) alongside AVAILABLE/LIMITED/UNAVAILABLE.
AVAILABILITY_STATUSES = ("AVAILABLE", "LIMITED", "BUSY", "UNAVAILABLE")
TALENT_REQUEST_STATUSES = (
    "WAITING_FOR_REVIEW", "WAITING_FOR_QUOTE", "QUOTED", "APPROVED", "PAYMENT_PENDING", "PAID",
    "IN_PROGRESS", "WAITING_FOR_CLIENT", "REVISION", "COMPLETED", "CANCELLED",
)


def seed_talents_if_needed():
    for t in SEED_TALENTS:
        existing = db.query_one("SELECT id FROM talents WHERE name = ?", (t["name"],))
        if existing is None:
            db.execute(
                "INSERT INTO talents (name, social_handle, platform, follower_count, niche, "
                "public_notes, pricing_mode) VALUES (?, ?, 'Instagram', ?, ?, ?, 'CUSTOM_QUOTE')",
                (t["name"], t["social_handle"], t["follower_count"], t["niche"], PUBLIC_DISCLAIMER),
            )


def list_active_talents():
    return db.query_all(
        "SELECT * FROM talents WHERE is_active = ? ORDER BY display_order, name", (True,)
    )


def list_all_talents():
    return db.query_all("SELECT * FROM talents ORDER BY display_order, name")


def get_talent(talent_id):
    return db.query_one("SELECT * FROM talents WHERE id = ?", (talent_id,))


def create_talent(name, social_handle=None, platform="Instagram", follower_count=None, niche=None,
                   bio=None, availability_status="AVAILABLE", availability_note=None,
                   public_notes=None, internal_notes=None, internal_rate=None,
                   profile_photo_url=None, created_by_user_id=None):
    """Final Operations Polish, Section 1: KILAS_ADMIN can add unlimited additional talents from
    the app, no coding/deploy required. New talents sort after every existing one by default
    (max(display_order) + 1) — admin can then reorder by editing the number, same as any other
    talent."""
    assert availability_status in AVAILABILITY_STATUSES, f"unknown availability {availability_status}"
    max_order_row = db.query_one("SELECT MAX(display_order) AS m FROM talents")
    next_order = (max_order_row["m"] or 0) + 1 if max_order_row else 1
    talent_id = db.insert_returning_id(
        "INSERT INTO talents (name, social_handle, platform, follower_count, niche, bio, "
        "availability_status, availability_note, public_notes, internal_notes, internal_rate, "
        "profile_photo_url, display_order, pricing_mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CUSTOM_QUOTE')",
        (name.strip(), (social_handle or "").strip() or None, platform or "Instagram",
         follower_count, (niche or "").strip() or None, bio, availability_status,
         (availability_note or "").strip() or None, public_notes or PUBLIC_DISCLAIMER,
         internal_notes, internal_rate, (profile_photo_url or "").strip() or None, next_order),
    )
    if created_by_user_id is not None:
        repo.write_audit(created_by_user_id, None, "TALENT_CREATED", f"talent_id={talent_id} name={name}")
    _bump_catalog_cache()
    return talent_id


def update_talent(talent_id, **fields):
    """Admin-only edit (Section 20 / Final Operations Polish Section 1: follower count,
    availability, photo, active/inactive, handle, niche, display order — all editable from the
    dashboard, never via code/DB edits). Only touches fields explicitly passed."""
    row = get_talent(talent_id)
    if row is None:
        return None
    allowed = ("name", "social_handle", "platform", "follower_count", "niche", "bio",
               "profile_image_file_id", "profile_photo_url", "profile_image_asset_id",
               "availability_status", "availability_note", "display_order", "is_active",
               "public_notes", "internal_notes", "internal_rate")
    set_parts, params = [], []
    for key in allowed:
        if key in fields:
            set_parts.append(f"{key} = ?")
            params.append(bool(fields[key]) if key == "is_active" else fields[key])
    if not set_parts:
        return row
    params.append(talent_id)
    db.execute(
        f"UPDATE talents SET {', '.join(set_parts)}, updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        f"UPDATE talents SET {', '.join(set_parts)}, updated_at = now() WHERE id = ?",
        tuple(params),
    )
    _bump_catalog_cache()
    return get_talent(talent_id)


def _bump_catalog_cache():
    """Absolute Final Production Patch: any talent create/update/archive/reactivate can change
    what the public live-generated catalog PDF shows (follower count, active state, name/handle,
    niche) — never never touches internal_rate's visibility (that field is simply never read by
    the catalog generator), but the cache still needs invalidating for everything else."""
    try:
        import catalog_cache
        catalog_cache.bump_version()
    except Exception:
        pass


def archive_talent(talent_id, actor_user_id=None):
    """Soft delete only (Section 1: 'Do NOT hard delete talents that have historical
    requests/projects') — flips is_active to False. talent_requests/projects referencing this
    talent are completely untouched; the talent simply stops appearing in the public list."""
    updated = update_talent(talent_id, is_active=False)
    if updated and actor_user_id is not None:
        repo.write_audit(actor_user_id, None, "TALENT_ARCHIVED", f"talent_id={talent_id} name={updated['name']}")
    return updated


def reactivate_talent(talent_id, actor_user_id=None):
    updated = update_talent(talent_id, is_active=True)
    if updated and actor_user_id is not None:
        repo.write_audit(actor_user_id, None, "TALENT_REACTIVATED", f"talent_id={talent_id} name={updated['name']}")
    return updated


def create_talent_request(talent_id, business_id, fields, created_by_user_id):
    """Section 15's request flow — starts WAITING_FOR_REVIEW. No price is ever set here; this is
    purely the intake step. A project row is created in lock-step (project_type='TALENT') so the
    admin dashboard's unified 'projects needing action' view also surfaces talent requests."""
    import projects_repo
    talent = get_talent(talent_id)
    if talent is None:
        raise ValueError("talent_not_found")

    title = f"Talent request: {talent['name']}"
    project_id = projects_repo.create_custom_project(
        business_id, "TALENT", title,
        requirements={**fields, "talent_id": talent_id, "talent_name": talent["name"]},
        budget_min=fields.get("budget"), budget_max=fields.get("budget"),
        created_by_user_id=created_by_user_id, catalog_key="talent_management",
    )
    request_id = db.insert_returning_id(
        "INSERT INTO talent_requests (talent_id, business_id, project_id, campaign_type, platform, "
        "deliverables, num_content_pieces, posting_requirements, target_date, location, "
        "usage_purpose, budget, brief, status, created_by_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WAITING_FOR_REVIEW', ?)",
        (talent_id, business_id, project_id, fields.get("campaign_type"), fields.get("platform"),
         fields.get("deliverables"), fields.get("num_content_pieces"), fields.get("posting_requirements"),
         fields.get("target_date"), fields.get("location"), fields.get("usage_purpose"),
         fields.get("budget"), fields.get("brief"), created_by_user_id),
    )
    repo.write_audit(created_by_user_id, business_id, "TALENT_REQUESTED",
                      f"talent={talent['name']} request_id={request_id} project_id={project_id}",
                      project_id=project_id)
    try:
        import owner_notifications
        owner_notifications.notify_talent_request_submitted(request_id, project_id, business_id, talent["name"])
    except Exception:
        pass
    return request_id, project_id


def get_talent_request(request_id):
    return db.query_one("SELECT * FROM talent_requests WHERE id = ?", (request_id,))


def list_talent_requests_for_business(business_id):
    return db.query_all("SELECT * FROM talent_requests WHERE business_id = ? ORDER BY created_at DESC", (business_id,))


def list_all_talent_requests():
    return db.query_all("SELECT * FROM talent_requests ORDER BY created_at DESC")
