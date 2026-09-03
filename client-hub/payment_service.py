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
    checkout-ready — this is the one gate that keeps an unapproved custom quote from being paid.

    Bug fix (real production incident: "checkout_locked: project status is 'PAYMENT_PENDING', must
    be APPROVED" for a customer who had already legitimately started checkout once): the ONLY way
    a project's status ever becomes PAYMENT_PENDING is THIS function itself, a few lines below —
    meaning a project sitting at PAYMENT_PENDING has, by construction, already passed the
    APPROVED/CUSTOM_QUOTE-approval gate once. Revisiting checkout (refresh, back button, clicking
    "Lanjut ke Pembayaran" again, log out/in) must reuse the existing invoice, never be treated as
    invalid — the idempotent "reuse existing invoice" logic below already existed, but was
    unreachable because the OLD guard rejected PAYMENT_PENDING before ever reaching it. Any OTHER
    status (WAITING_FOR_QUOTE, DRAFT, PAID, COMPLETED, CANCELLED, etc.) is still correctly
    rejected — CUSTOM_QUOTE safety (Section C) is unchanged: a quote must still be APPROVED before
    its first checkout, exactly as before."""
    project = projects_repo.get_project(project_id)
    if project is None or project["business_id"] != business_id:
        raise ValueError("project_not_found")
    if project["status"] not in ("APPROVED", "PAYMENT_PENDING"):
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

    # PAYMENT_PENDING with NO existing invoice is a genuine data-integrity edge case (Section A:
    # "PAYMENT_PENDING + invoice unexpectedly missing -> recover safely and idempotently"). Rather
    # than crash or silently do nothing, fall through to the SAME invoice-creation path an
    # APPROVED project uses below — this is safe because final_price is already confirmed present
    # above, and creating exactly one invoice here is the correct recovery, not a workaround.

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
    if project["status"] != "PAYMENT_PENDING":
        projects_repo.set_project_status(project_id, "PAYMENT_PENDING", actor_user_id, business_id,
                                          f"checkout: {invoice_number}")
    return invoice_id


def get_invoice(invoice_id):
    return db.query_one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))


def get_latest_invoice_for_project(project_id):
    """Same query checkout()'s own idempotent-reuse logic uses — exposed separately so the
    checkout PAGE's GET handler can redirect straight to an already-existing invoice for a
    PAYMENT_PENDING project without needing to call checkout() itself (which would be a POST-style
    mutation on a plain page-load)."""
    return db.query_one(
        "SELECT * FROM invoices WHERE project_id = ? AND status != 'CANCELLED' ORDER BY created_at DESC",
        (project_id,),
    )


def get_payment_for_invoice(invoice_id):
    return db.query_one("SELECT * FROM payments WHERE invoice_id = ? ORDER BY created_at DESC LIMIT 1", (invoice_id,))


def get_latest_payment_for_project(project_id):
    """Dashboard fix (Section 1 of the payment-verification-strengthening request): a project's
    STATUS ('Disetujui'/APPROVED) and its PAYMENT status are genuinely different things read from
    different tables — a project can be APPROVED (quotation-wise, or checkout-ready) while its
    payment is still PAYMENT_PENDING or has no invoice/payment row at all yet. This is the one
    query the customer dashboard needs to show both correctly: the most recent invoice for this
    project (a project normally has exactly one, but this takes the latest defensively), and that
    invoice's payment. Returns None if there is no invoice for this project yet at all — the
    caller must treat that as "belum ada tagihan", never infer "already paid" from its absence."""
    invoice = db.query_one(
        "SELECT * FROM invoices WHERE project_id = ? ORDER BY created_at DESC LIMIT 1", (project_id,)
    )
    if invoice is None:
        return None, None
    payment = get_payment_for_invoice(invoice["id"])
    return invoice, payment


def get_payment(payment_id):
    return db.query_one("SELECT * FROM payments WHERE id = ?", (payment_id,))


def list_payments_for_business(business_id):
    return db.query_all("SELECT * FROM payments WHERE business_id = ? ORDER BY created_at DESC", (business_id,))


def list_payments_pending_review():
    return db.query_all(
        "SELECT * FROM payments WHERE status IN ('PROOF_UPLOADED', 'UNDER_REVIEW') ORDER BY created_at ASC"
    )


def upload_payment_proof(payment_id, business_id, proof_file_id, actor_user_id, proof_file_hash=None,
                          image_bytes=None, image_mime=None):
    payment = get_payment(payment_id)
    if payment is None or payment["business_id"] != business_id:
        raise ValueError("payment_not_found")
    if payment["status"] not in ("PAYMENT_PENDING", "REJECTED"):
        raise ValueError(f"invalid_state: payment is {payment['status']}, cannot upload proof")

    invoice = get_invoice(payment["invoice_id"])
    # Real vision extraction (Part B of the request) — only attempted for an actual supported
    # image (JPG/PNG); a PDF or unsupported type safely falls through to "unreadable" rather than
    # attempting a vision call the model can't use, exactly as extract_payment_proof_fields()
    # itself already handles internally for a mismatched MIME type.
    extracted_fields = None
    if image_bytes and image_mime in ai_payment_review.ALLOWED_PROOF_MIME_TYPES:
        extracted_fields = ai_payment_review.extract_payment_proof_fields(image_bytes, image_mime)
    assessment = ai_payment_review.assess_payment_proof(
        payment_id, business_id, invoice["amount"], extracted_fields=extracted_fields,
        proof_file_hash=proof_file_hash,
    )

    db.execute(
        "UPDATE payments SET status = 'UNDER_REVIEW', proof_file_id = ?, ai_extracted_amount = ?, "
        "ai_extracted_date = ?, ai_extracted_bank = ?, ai_reference = ?, ai_risk_flags_json = ?, "
        "ai_match_score = ?, duplicate_candidate = ?, proof_file_hash = ?, updated_at = datetime('now') "
        "WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE payments SET status = 'UNDER_REVIEW', proof_file_id = ?, ai_extracted_amount = ?, "
        "ai_extracted_date = ?, ai_extracted_bank = ?, ai_reference = ?, ai_risk_flags_json = ?, "
        "ai_match_score = ?, duplicate_candidate = ?, proof_file_hash = ?, updated_at = now() WHERE id = ?",
        (proof_file_id, assessment["ai_extracted_amount"], assessment["ai_extracted_date"],
         assessment["ai_extracted_bank"], assessment["ai_reference"],
         json.dumps(assessment["ai_risk_flags"]), assessment["ai_match_score"],
         bool(assessment["duplicate_candidate"]), proof_file_hash, payment_id),
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


def derive_review_status(payment):
    """Derives a richer, more specific DISPLAY status from a stored payment row — WITHOUT changing
    the underlying gating state machine (payments.status stays exactly PAYMENT_PENDING/
    UNDER_REVIEW/VERIFIED/REJECTED; verify_payment()/reject_payment() still gate off those exact
    values, completely unchanged by this function). This is purely a read-time refinement for
    display (Section 8/12 of the payment-verification-strengthening request) — VERIFIED means
    exactly what it always meant: a human approved it, never inferred from an AI check alone.

    VERIFIED/REJECTED/PAYMENT_PENDING pass through unchanged. UNDER_REVIEW is refined into one of:
      UNREADABLE           — the AI could not extract anything from the proof at all
      AMOUNT_MISMATCH      — extracted amount doesn't match the invoice (or DP) amount
      POSSIBLE_DUPLICATE   — same proof file hash or transaction reference seen on a different
                              payment (see ai_payment_review.py's duplicate checks)
      NEEDS_MANUAL_REVIEW  — some OTHER risk flag was raised (reserved for future flags, e.g.
                              SUSPICIOUS_VISUAL_ANOMALY once real vision extraction exists)
      AUTO_CHECK_PASSED    — no risk flags at all; STILL requires human approval — this status
                              name deliberately does NOT say "verified" or "approved", since it
                              never implies that (Section 5's "AI must never claim authenticity")

    Priority when multiple flags are present: UNREADABLE > AMOUNT_MISMATCH > POSSIBLE_DUPLICATE >
    NEEDS_MANUAL_REVIEW — the most actionable/blocking issue is surfaced first, so an admin's/
    customer's first glance shows the thing most likely to need action."""
    status = payment.get("status")
    if status in ("PAYMENT_PENDING", "VERIFIED", "REJECTED"):
        return status
    if status != "UNDER_REVIEW":
        return status  # unknown/future status — pass through unchanged, never hidden

    raw_flags = payment.get("ai_risk_flags_json")
    flags = []
    if raw_flags:
        try:
            flags = json.loads(raw_flags) if isinstance(raw_flags, str) else raw_flags
        except (ValueError, TypeError):
            flags = []

    if "UNREADABLE" in flags:
        return "UNREADABLE"
    if "AMOUNT_MISMATCH" in flags:
        return "AMOUNT_MISMATCH"
    if "DUPLICATE_REFERENCE_CANDIDATE" in flags or "DUPLICATE_FILE_CANDIDATE" in flags:
        return "POSSIBLE_DUPLICATE"
    if flags:
        return "NEEDS_MANUAL_REVIEW"
    return "AUTO_CHECK_PASSED"


def request_reupload(payment_id, business_id, actor_user_id, admin_notes=None):
    """Section 9/11's third admin action, distinct from reject_payment(): the proof itself wasn't
    necessarily WRONG (e.g. UNREADABLE, or a minor mismatch worth double-checking with the
    customer) — this asks for a fresh upload without recording it as a REJECTED payment. Reuses
    the exact same PAYMENT_PENDING transition upload_payment_proof() already accepts re-upload
    from, so the customer-facing re-upload flow is entirely unchanged — only the admin_notes/audit
    event differ, making REQUEST_REUPLOAD distinguishable from an actual REJECTED in the audit
    trail. The OLD proof file itself is never deleted — project_files rows are never removed by any
    action in this module, preserving it for audit exactly as Section 11 requires."""
    payment = get_payment(payment_id)
    if payment is None or payment["business_id"] != business_id:
        raise ValueError("payment_not_found")
    if payment["status"] not in ("UNDER_REVIEW", "PROOF_UPLOADED"):
        raise ValueError(f"invalid_state: payment is {payment['status']}, cannot request reupload")

    db.execute(
        "UPDATE payments SET status = 'PAYMENT_PENDING', admin_notes = ?, updated_at = datetime('now') "
        "WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE payments SET status = 'PAYMENT_PENDING', admin_notes = ?, updated_at = now() WHERE id = ?",
        (admin_notes, payment_id),
    )
    invoice = get_invoice(payment["invoice_id"])
    repo.write_audit(actor_user_id, business_id, "PAYMENT_REUPLOAD_REQUESTED", f"payment_id={payment_id}",
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
