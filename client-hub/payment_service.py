"""Checkout, invoice, and payment workflow — Business Hub V2, Phase C (Section 10/12).

CRITICAL GATE (Section 6/10, enforced here): checkout() refuses to run unless project.status ==
'APPROVED' — which is true immediately for a FIXED_PRICE project (set at creation in
projects_repo.create_fixed_price_project) and ONLY becomes true for a CUSTOM_QUOTE project after
quotation_service.approve_quotation() has run. There is no other path to APPROVED for a custom
project, so a custom project can never reach checkout before its quotation is approved.
"""
import json

import db
import repo
import projects_repo
import ai_payment_review

PAYMENT_STATUSES = ("PAYMENT_PENDING", "PROOF_UPLOADED", "UNDER_REVIEW", "VERIFIED", "REJECTED")

BANK_DETAILS = {
    "bank_name": "BCA",
    "account_number": "7610267551",
    "account_holder": "Irvan Karnawi",
}


def _generate_invoice_number(invoice_id):
    from datetime import datetime, timezone
    year = datetime.now(timezone.utc).year
    return f"INV-{year}-{invoice_id:06d}"


def checkout(project_id, business_id, actor_user_id):
    """Creates the invoice + a PAYMENT_PENDING payment row together (Section 12: 'Create
    invoice/payment record before proof upload'). Raises ValueError if the project isn't actually
    checkout-ready — this is the one gate that keeps an unapproved custom quote from being paid."""
    project = projects_repo.get_project(project_id)
    if project is None or project["business_id"] != business_id:
        raise ValueError("project_not_found")
    if project["status"] != "APPROVED":
        raise ValueError(
            f"checkout_locked: project status is {project['status']!r}, must be APPROVED "
            "(fixed-price projects are APPROVED at creation; custom projects only after quotation approval)"
        )
    if project["final_price"] is None:
        raise ValueError("checkout_locked: project has no final_price set")

    existing_invoice = db.query_one(
        "SELECT * FROM invoices WHERE project_id = ? AND status != 'CANCELLED' ORDER BY created_at DESC",
        (project_id,),
    )
    if existing_invoice is not None:
        return existing_invoice["id"]  # idempotent — re-clicking checkout doesn't double-invoice

    quotation = None
    if project["pricing_mode"] == "CUSTOM_QUOTE":
        from quotation_service import get_latest_quotation_for_project
        quotation = get_latest_quotation_for_project(project_id)

    invoice_id = db.insert_returning_id(
        "INSERT INTO invoices (invoice_number, business_id, project_id, quotation_id, amount, status) "
        "VALUES ('PENDING', ?, ?, ?, ?, 'ISSUED')",
        (business_id, project_id, quotation["id"] if quotation else None, project["final_price"]),
    )
    invoice_number = _generate_invoice_number(invoice_id)
    db.execute("UPDATE invoices SET invoice_number = ? WHERE id = ?", (invoice_number, invoice_id))

    db.insert_returning_id(
        "INSERT INTO payments (business_id, invoice_id, status) VALUES (?, ?, 'PAYMENT_PENDING')",
        (business_id, invoice_id),
    )
    projects_repo.set_project_status(project_id, "PAYMENT_PENDING", actor_user_id, business_id,
                                      f"checkout: {invoice_number}")
    return invoice_id


def get_invoice(invoice_id):
    return db.query_one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))


def get_payment_for_invoice(invoice_id):
    return db.query_one("SELECT * FROM payments WHERE invoice_id = ? ORDER BY created_at DESC LIMIT 1", (invoice_id,))


def get_payment(payment_id):
    return db.query_one("SELECT * FROM payments WHERE id = ?", (payment_id,))


def list_payments_for_business(business_id):
    return db.query_all("SELECT * FROM payments WHERE business_id = ? ORDER BY created_at DESC", (business_id,))


def list_payments_pending_review():
    return db.query_all(
        "SELECT * FROM payments WHERE status IN ('PROOF_UPLOADED', 'UNDER_REVIEW') ORDER BY created_at ASC"
    )


def upload_payment_proof(payment_id, business_id, proof_file_id, actor_user_id):
    payment = get_payment(payment_id)
    if payment is None or payment["business_id"] != business_id:
        raise ValueError("payment_not_found")
    if payment["status"] not in ("PAYMENT_PENDING", "REJECTED"):
        raise ValueError(f"invalid_state: payment is {payment['status']}, cannot upload proof")

    invoice = get_invoice(payment["invoice_id"])
    assessment = ai_payment_review.assess_payment_proof(payment_id, business_id, invoice["amount"])

    db.execute(
        "UPDATE payments SET status = 'UNDER_REVIEW', proof_file_id = ?, ai_extracted_amount = ?, "
        "ai_extracted_date = ?, ai_extracted_bank = ?, ai_reference = ?, ai_risk_flags_json = ?, "
        "ai_match_score = ?, duplicate_candidate = ?, updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE payments SET status = 'UNDER_REVIEW', proof_file_id = ?, ai_extracted_amount = ?, "
        "ai_extracted_date = ?, ai_extracted_bank = ?, ai_reference = ?, ai_risk_flags_json = ?, "
        "ai_match_score = ?, duplicate_candidate = ?, updated_at = now() WHERE id = ?",
        (proof_file_id, assessment["ai_extracted_amount"], assessment["ai_extracted_date"],
         assessment["ai_extracted_bank"], assessment["ai_reference"],
         json.dumps(assessment["ai_risk_flags"]), assessment["ai_match_score"],
         bool(assessment["duplicate_candidate"]), payment_id),
    )
    repo.write_audit(actor_user_id, business_id, "PAYMENT_PROOF_UPLOADED", f"payment_id={payment_id}",
                      project_id=invoice["project_id"])
    return assessment


def verify_payment(payment_id, business_id, actor_user_id, admin_notes=None):
    payment = get_payment(payment_id)
    if payment is None or payment["business_id"] != business_id:
        raise ValueError("payment_not_found")
    if payment["status"] not in ("UNDER_REVIEW", "PROOF_UPLOADED"):
        raise ValueError(f"invalid_state: payment is {payment['status']}, cannot verify")

    db.execute(
        "UPDATE payments SET status = 'VERIFIED', verified_by_user_id = ?, verified_at = datetime('now'), "
        "admin_notes = ?, updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE payments SET status = 'VERIFIED', verified_by_user_id = ?, verified_at = now(), "
        "admin_notes = ?, updated_at = now() WHERE id = ?",
        (actor_user_id, admin_notes, payment_id),
    )
    invoice = get_invoice(payment["invoice_id"])
    db.execute("UPDATE invoices SET status = 'PAID' WHERE id = ?", (invoice["id"],))
    projects_repo.set_project_status(invoice["project_id"], "PAID", actor_user_id, business_id,
                                      f"payment_id={payment_id} verified")
    repo.write_audit(actor_user_id, business_id, "PAYMENT_VERIFIED", f"payment_id={payment_id}",
                      project_id=invoice["project_id"])


def reject_payment(payment_id, business_id, actor_user_id, admin_notes=None):
    payment = get_payment(payment_id)
    if payment is None or payment["business_id"] != business_id:
        raise ValueError("payment_not_found")
    if payment["status"] not in ("UNDER_REVIEW", "PROOF_UPLOADED"):
        raise ValueError(f"invalid_state: payment is {payment['status']}, cannot reject")

    db.execute(
        "UPDATE payments SET status = 'REJECTED', admin_notes = ?, updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE payments SET status = 'REJECTED', admin_notes = ?, updated_at = now() WHERE id = ?",
        (admin_notes, payment_id),
    )
    invoice = get_invoice(payment["invoice_id"])
    repo.write_audit(actor_user_id, business_id, "PAYMENT_REJECTED", f"payment_id={payment_id}: {admin_notes or ''}",
                      project_id=invoice["project_id"] if invoice else None)


def has_verified_ai_admin_payment(business_id):
    """Section 22's activation gate: 'Never activate an unpaid tenant.'

    Bug fix: this used to be has_unpaid_ai_admin_invoice(), which returned False (= 'not unpaid' =
    OK to activate) whenever a business had NO AI Admin invoice/payment row at all — treating
    "never bought AI Admin" the same as "already paid for AI Admin", which let a business be
    activated without ever paying. "No invoice at all" must NEVER be treated as "already covered".

    K7 KOPI legacy-package fix (UI cleanup cycle): this used to accept a VERIFIED payment tied to
    EITHER catalog_key ('ai_admin_basic' OR 'ai_admin_pro'), regardless of the business's CURRENT
    `package` column. That is wrong whenever a business's package was ever changed after an
    earlier payment — reachable in practice via routes_admin.py's admin-only
    POST /business/<id>/package -> repo.set_business_package(), which updates `businesses.package`
    freely without touching any existing projects/invoices/payments (by design — those are
    historical records, never rewritten). A business currently on AI_ADMIN_BASIC but with an OLD
    VERIFIED payment against an ai_admin_pro project (e.g. from before an admin corrected the
    package, or from the now-fixed duplicate-checkout-flow bug) would incorrectly pass this gate
    on the strength of a payment for a DIFFERENT tier than what they currently have. Now requires
    a VERIFIED payment matching the business's CURRENT package specifically — a business whose
    package was changed after paying must have a NEW verified payment for the NEW tier; the OLD
    payment stays exactly as it is in the database (never deleted/modified), it simply no longer
    satisfies a gate for a package it was never actually for.

    Returns True ONLY when there is an explicit VERIFIED payment tied to an AI Admin project whose
    catalog_key matches THIS business's CURRENT package (ai_admin_basic for AI_ADMIN_BASIC,
    ai_admin_pro for AI_ADMIN_PRO) — the positive condition activate_tenant() now requires before
    allowing activation, rather than the absence of a negative one. A VERIFIED payment for a
    different, unrelated service (e.g. a website package) never counts here, since it isn't joined
    through an ai_admin_* project at all. A business currently on package='NONE' (or any other
    non-AI-Admin value) can never satisfy this gate, by construction — there is no catalog_key for
    'NONE' to match against.

    Note: this only gates the ACTIVATION step (business.status -> ACTIVE / WhatsApp-connection
    readiness), not the package field itself — a business may freely pick/upgrade its `package` to
    AI_ADMIN_BASIC/PRO and fill in onboarding data while payment is still pending; see
    repo.upgrade_business_package(). Already-ACTIVE tenants are unaffected: activate_tenant()
    returns early for a business that's already ACTIVE, so this gate only ever runs on the
    APPROVED -> ACTIVE transition, never re-checked against tenants activated before this fix."""
    business = db.query_one("SELECT package FROM businesses WHERE id = ?", (business_id,))
    if not business:
        return False
    catalog_key = {"AI_ADMIN_BASIC": "ai_admin_basic", "AI_ADMIN_PRO": "ai_admin_pro"}.get(business["package"])
    if not catalog_key:
        # package is 'NONE' (or some other non-AI-Admin value) — no historical AI Admin payment,
        # for any tier, can ever satisfy an activation gate for a package this business doesn't
        # currently have.
        return False
    rows = db.query_all(
        "SELECT p.status FROM payments p "
        "JOIN invoices i ON i.id = p.invoice_id "
        "JOIN projects pr ON pr.id = i.project_id "
        "WHERE pr.business_id = ? AND pr.catalog_key = ?",
        (business_id, catalog_key),
    )
    return any(r["status"] == "VERIFIED" for r in rows)
