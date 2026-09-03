"""Projects / custom service requests — Business Hub V2, Phase B.

One `projects` row per fixed-price order OR custom request (Section 10: project-by-project
checkout instead of an overcomplicated multi-item cart — the master spec explicitly allows this
simpler architecture when it fits better). A business can have many projects at once (Section 9).

CRITICAL RULE (Section 6/7/8, enforced here structurally, not just by convention): a CUSTOM_QUOTE
project is created with final_price = NULL and status REQUESTED/WAITING_FOR_QUOTE. Nothing in this
module ever computes or guesses a final_price for a custom project — that only ever happens via
quotation_service.create_quotation(), which requires an explicit KILAS_ADMIN-supplied amount.
"""
import json

import db
import repo

PROJECT_TYPES = ("PHOTO", "VIDEO", "WEBSITE", "APPLICATION", "TALENT", "CONTENT", "ADS", "EVENT", "OTHER")

PROJECT_STATUSES = (
    "REQUESTED", "WAITING_FOR_QUOTE", "QUOTED", "APPROVED", "PAYMENT_PENDING", "PAID",
    "IN_PROGRESS", "WAITING_FOR_CLIENT", "REVISION", "COMPLETED", "CANCELLED",
)


def create_fixed_price_project(business_id, catalog_item, created_by_user_id):
    """A fixed-price catalog selection. Checkout-ready immediately (Section 6) — no quotation
    needed, since the price is already known from the catalog."""
    project_id = db.insert_returning_id(
        "INSERT INTO projects (business_id, project_type, catalog_key, pricing_mode, title, "
        "status, final_price, created_by_user_id) VALUES (?, ?, ?, 'FIXED_PRICE', ?, 'APPROVED', ?, ?)",
        (business_id, _project_type_for_category(catalog_item["category"]), catalog_item["catalog_key"],
         catalog_item["name"], catalog_item["price_amount"], created_by_user_id),
    )
    repo.write_audit(created_by_user_id, business_id, "PROJECT_CREATED",
                      f"fixed-price: {catalog_item['name']} (project_id={project_id})",
                      project_id=project_id)
    return project_id


def create_custom_project(business_id, project_type, title, requirements, budget_min, budget_max,
                           created_by_user_id, catalog_key=None):
    """A CUSTOM_QUOTE request (Section 7/8: video/photo/website-app). Always starts at
    WAITING_FOR_QUOTE with final_price = NULL — the system NEVER invents a price here."""
    assert project_type in PROJECT_TYPES, f"unknown project_type {project_type}"
    project_id = db.insert_returning_id(
        "INSERT INTO projects (business_id, project_type, catalog_key, pricing_mode, title, "
        "status, requirements_json, budget_min, budget_max, created_by_user_id) "
        "VALUES (?, ?, ?, 'CUSTOM_QUOTE', ?, 'WAITING_FOR_QUOTE', ?, ?, ?, ?)",
        (business_id, project_type, catalog_key, title, json.dumps(requirements, ensure_ascii=False),
         budget_min, budget_max, created_by_user_id),
    )
    repo.write_audit(created_by_user_id, business_id, "PROJECT_CREATED",
                      f"custom {project_type}: {title} (project_id={project_id})",
                      project_id=project_id)
    # Ecosystem Sync Section 10(B)/11: notify the owner of a new custom project request. TALENT
    # is excluded here — talent_service.create_talent_request (which calls this function) sends
    # its own more specific TALENT_REQUEST_SUBMITTED notification right after this returns, so
    # notifying here too would double-notify the owner for the exact same submission.
    if project_type != "TALENT":
        try:
            import owner_notifications
            owner_notifications.notify_custom_project_submitted(project_id, business_id, project_type, title)
        except Exception:
            pass
    return project_id


def _project_type_for_category(category):
    mapping = {
        "AI_ADMIN": "OTHER", "CONTENT": "CONTENT", "BUNDLE": "OTHER", "ADS": "ADS",
        "WEBSITE": "WEBSITE", "EVENT": "EVENT", "VIDEO": "VIDEO", "PHOTO": "PHOTO",
        "APPLICATION": "APPLICATION", "TALENT": "TALENT",
    }
    return mapping.get(category, "OTHER")


def get_project(project_id):
    row = db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row and row.get("requirements_json"):
        try:
            row["requirements"] = json.loads(row["requirements_json"]) if isinstance(row["requirements_json"], str) else row["requirements_json"]
        except (TypeError, ValueError):
            row["requirements"] = {}
    return row


def list_projects_for_business(business_id):
    return db.query_all("SELECT * FROM projects WHERE business_id = ? ORDER BY created_at DESC", (business_id,))


def get_unfinished_project_for_catalog_key(business_id, catalog_key):
    """Repeat-click / refresh safety (Client Hub purchase-flow fix, Section 6): finds an existing
    NON-TERMINAL project for this exact business+catalog_key combination, if one exists — the
    service catalog page uses this to show "Lanjutkan" instead of creating a second project for
    the same intended purchase. "Non-terminal" excludes CANCELLED/REJECTED (those are dead ends,
    a customer should be able to start fresh) but includes everything else (WAITING_FOR_QUOTE
    through IN_PROGRESS) — COMPLETED is also excluded since a completed order is historical, not
    "unfinished"."""
    return db.query_one(
        "SELECT * FROM projects WHERE business_id = ? AND catalog_key = ? "
        "AND status NOT IN ('CANCELLED', 'REJECTED', 'COMPLETED') "
        "ORDER BY created_at DESC LIMIT 1",
        (business_id, catalog_key),
    )


def list_all_projects(status_filter=None, project_type_filter=None, business_id_filter=None):
    """Final Operations Polish, Section 13: admin project list filters. Each filter is optional and
    independent — pass any combination. Built with a plain, safe WHERE-clause accumulator (no
    string-formatted values, only placeholders) rather than a query builder dependency."""
    clauses, params = [], []
    if status_filter:
        clauses.append("status = ?")
        params.append(status_filter)
    if project_type_filter:
        clauses.append("project_type = ?")
        params.append(project_type_filter)
    if business_id_filter:
        clauses.append("business_id = ?")
        params.append(business_id_filter)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return db.query_all(f"SELECT * FROM projects{where} ORDER BY created_at DESC", tuple(params))


def list_projects_needing_action():
    """Admin dashboard 'projects needing action' (Section 20): anything waiting on Kilas Works,
    not on the customer."""
    return db.query_all(
        "SELECT * FROM projects WHERE status IN ('REQUESTED', 'WAITING_FOR_QUOTE', 'PAID') "
        "ORDER BY created_at ASC"
    )


def set_project_status(project_id, new_status, actor_user_id=None, business_id=None, detail=None):
    assert new_status in PROJECT_STATUSES, f"unknown status {new_status}"
    db.execute(
        "UPDATE projects SET status = ?, updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE projects SET status = ?, updated_at = now() WHERE id = ?",
        (new_status, project_id),
    )
    if business_id is not None:
        repo.write_audit(actor_user_id, business_id, "PROJECT_STATUS_CHANGED",
                          detail or f"project_id={project_id} new_status={new_status}",
                          project_id=project_id)


def set_project_final_price(project_id, final_price):
    """Called ONLY from quotation_service when a quotation is approved — never called directly by
    a route, so a final_price can never appear on a project without a corresponding quotation
    record explaining where it came from."""
    db.execute("UPDATE projects SET final_price = ? WHERE id = ?", (final_price, project_id))
