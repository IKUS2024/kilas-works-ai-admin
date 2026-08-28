"""Quotation system — Business Hub V2, Phase C (Section 11).

The ONLY way a CUSTOM_QUOTE project gets a final_price is through create_quotation() here, always
called with an explicit amount supplied by a KILAS_ADMIN actor (enforced by routes_admin.py's
@security.admin_required, not re-checked here — this module trusts its caller the same way
provisioning.py trusts _require_admin at the route layer for admin-only actions elsewhere).
"""
import db
import repo
import projects_repo

QUOTATION_STATUSES = ("DRAFT", "SENT", "VIEWED", "APPROVED", "REJECTED", "EXPIRED")


def _generate_quotation_number(quotation_id):
    from datetime import datetime, timezone
    year = datetime.now(timezone.utc).year
    return f"QUO-{year}-{quotation_id:06d}"


def create_quotation(project_id, business_id, scope, deliverables, quantity, final_price, notes,
                      created_by_user_id):
    """Creates a quotation and immediately marks it SENT (Kilas Works' one-admin-action-per-step
    flow — a DRAFT-then-separately-send two-step UI can be added later without a schema change,
    since status is already a first-class column). Also flips the project to QUOTED."""
    quotation_id = db.insert_returning_id(
        "INSERT INTO quotations (quotation_number, business_id, project_id, scope, deliverables, "
        "quantity, final_price, notes, status, created_by_user_id, updated_by_user_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'SENT', ?, ?)",
        ("PENDING", business_id, project_id, scope, deliverables, quantity, final_price, notes,
         created_by_user_id, created_by_user_id),
    )
    # quotation_number embeds the id for human-readable uniqueness; needs the id first, so it's a
    # two-step insert-then-update rather than a single statement.
    quotation_number = _generate_quotation_number(quotation_id)
    db.execute("UPDATE quotations SET quotation_number = ? WHERE id = ?", (quotation_number, quotation_id))

    projects_repo.set_project_status(project_id, "QUOTED", created_by_user_id, business_id,
                                      f"quotation {quotation_number} sent")
    repo.write_audit(created_by_user_id, business_id, "QUOTE_CREATED",
                      f"{quotation_number} project_id={project_id} final_price={final_price}",
                      project_id=project_id)
    repo.write_audit(created_by_user_id, business_id, "QUOTE_SENT", quotation_number,
                      project_id=project_id)
    return quotation_id


def get_quotation(quotation_id):
    return db.query_one("SELECT * FROM quotations WHERE id = ?", (quotation_id,))


def list_quotations_for_business(business_id):
    return db.query_all("SELECT * FROM quotations WHERE business_id = ? ORDER BY created_at DESC", (business_id,))


def list_all_quotations():
    """Absolute Final Production Patch — read-only listing used by the bot's owner-query context
    (app.py's _get_recent_quotations_safe), e.g. 'Quotation Rina berapa?'. Never mutates anything."""
    return db.query_all("SELECT * FROM quotations ORDER BY created_at DESC")


def get_latest_quotation_for_project(project_id):
    rows = db.query_all("SELECT * FROM quotations WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
    return rows[0] if rows else None


def mark_viewed(quotation_id):
    row = get_quotation(quotation_id)
    if row and row["status"] == "SENT":
        db.execute(
            "UPDATE quotations SET status = 'VIEWED', viewed_at = datetime('now') WHERE id = ?"
            if db.BACKEND == "sqlite" else
            "UPDATE quotations SET status = 'VIEWED', viewed_at = now() WHERE id = ?",
            (quotation_id,),
        )


def approve_quotation(quotation_id, business_id, actor_user_id):
    """Customer approval — the ONLY event that unlocks checkout for a custom project (Section 6:
    'ONLY THEN checkout becomes available'). Sets the project's final_price from the quotation
    (never re-computed) and flips the project to APPROVED, matching the fixed-price project's
    checkout-ready state so routes_payments.py doesn't need to special-case custom vs fixed."""
    quotation = get_quotation(quotation_id)
    if quotation is None or quotation["business_id"] != business_id:
        raise ValueError("quotation_not_found")
    if quotation["status"] not in ("SENT", "VIEWED"):
        raise ValueError(f"invalid_state: quotation is {quotation['status']}, cannot approve")

    db.execute(
        "UPDATE quotations SET status = 'APPROVED', responded_at = datetime('now'), "
        "updated_by_user_id = ? WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE quotations SET status = 'APPROVED', responded_at = now(), "
        "updated_by_user_id = ? WHERE id = ?",
        (actor_user_id, quotation_id),
    )
    projects_repo.set_project_final_price(quotation["project_id"], quotation["final_price"])
    projects_repo.set_project_status(quotation["project_id"], "APPROVED", actor_user_id, business_id,
                                      f"{quotation['quotation_number']} approved by customer")
    repo.write_audit(actor_user_id, business_id, "QUOTE_APPROVED", quotation["quotation_number"],
                      project_id=quotation["project_id"])
    try:
        import owner_notifications
        owner_notifications.notify_quotation_approved(
            quotation_id, quotation["project_id"], business_id,
            quotation["quotation_number"], quotation["final_price"],
        )
    except Exception:
        pass


def reject_quotation(quotation_id, business_id, actor_user_id, note=None):
    """Customer rejects / requests change — project goes back to WAITING_FOR_QUOTE so a Kilas
    admin can send a revised quotation. Checkout must NEVER be reachable from this state."""
    quotation = get_quotation(quotation_id)
    if quotation is None or quotation["business_id"] != business_id:
        raise ValueError("quotation_not_found")
    if quotation["status"] not in ("SENT", "VIEWED"):
        raise ValueError(f"invalid_state: quotation is {quotation['status']}, cannot reject")

    db.execute(
        "UPDATE quotations SET status = 'REJECTED', responded_at = datetime('now'), "
        "notes = ?, updated_by_user_id = ? WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE quotations SET status = 'REJECTED', responded_at = now(), "
        "notes = ?, updated_by_user_id = ? WHERE id = ?",
        (note or quotation["notes"], actor_user_id, quotation_id),
    )
    projects_repo.set_project_status(quotation["project_id"], "WAITING_FOR_QUOTE", actor_user_id, business_id,
                                      f"{quotation['quotation_number']} rejected by customer: {note or ''}")
    repo.write_audit(actor_user_id, business_id, "QUOTE_REJECTED", f"{quotation['quotation_number']}: {note or ''}",
                      project_id=quotation["project_id"])
