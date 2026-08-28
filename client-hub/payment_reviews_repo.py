"""Persistence for a Pro tenant's own customer payment-proof review workflow (migration 0013).

COMPLETELY SEPARATE from Kilas Works' own platform-billing verification (payment_service.py /
ai_payment_review.py / routes_admin.py's payment review page, all backed by the `payments` table
added in migration 0005). Those record a CLIENT BUSINESS paying KILAS WORKS for its own
subscription/project and are verified by a KILAS_ADMIN. This module records that CLIENT BUSINESS'S
OWN CUSTOMER paying the business directly (e.g. a coffee shop customer transferring for an order),
verified by that business's own owner over WhatsApp — different table, different notification
target, different owner-command handling, on purpose. No function here ever reads/writes the
`payments` table, and no function in payment_service.py ever reads/writes tenant_payment_reviews.

STRICT RULE (same one ai_payment_review.py already enforces for the platform-billing flow): no
function here returns or implies a verdict on whether a proof is genuine. amount_detected is a
best-effort AI reading of the image, always subordinate to the tenant owner's own manual decision.

STATUS VALUES: PENDING_OWNER_VERIFICATION -> CONFIRMED | REJECTED (owner-decided, one-way).
"""
import db

STATUSES = ("PENDING_OWNER_VERIFICATION", "CONFIRMED", "REJECTED")


def store_proof_image(business_id, content_bytes, mime_type, filename="bukti_transfer.jpg"):
    """Stores the raw proof-image bytes using the SAME project_files table/pattern Kilas Works'
    own checkout flow already uses for its (separate) PAYMENT_PROOF kind (see routes_payments.py)
    — project_id is left NULL since a tenant's own customer payment isn't tied to any Kilas Works
    Business Hub project. Returns the new project_files.id, to be stored as proof_file_id on the
    tenant_payment_reviews row."""
    return db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content) VALUES (?, NULL, 'TENANT_PAYMENT_PROOF', ?, ?, ?, ?)",
        (business_id, filename, mime_type or "application/octet-stream", len(content_bytes), content_bytes),
    )


def get_proof_file_scoped(proof_file_id, business_id):
    """Reads back a stored proof image, scoped by business_id — same isolation guarantee as
    get_review_scoped."""
    row = db.query_one(
        "SELECT * FROM project_files WHERE id = ? AND business_id = ? AND kind = 'TENANT_PAYMENT_PROOF'",
        (proof_file_id, business_id),
    )
    return dict(row) if row is not None else None


def create_review(business_id, customer_phone, customer_name, amount_claimed=None,
                   amount_detected=None, proof_file_id=None):
    """Always starts PENDING_OWNER_VERIFICATION — nothing in this module is ever allowed to insert
    a row that is already CONFIRMED/REJECTED (that transition only ever happens via
    update_status(), driven by an explicit owner decision)."""
    return db.insert_returning_id(
        "INSERT INTO tenant_payment_reviews "
        "(business_id, customer_phone, customer_name, amount_claimed, amount_detected, proof_file_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'PENDING_OWNER_VERIFICATION')",
        (business_id, customer_phone, customer_name, amount_claimed, amount_detected, proof_file_id),
    )


def get_review(review_id):
    row = db.query_one("SELECT * FROM tenant_payment_reviews WHERE id = ?", (review_id,))
    return dict(row) if row is not None else None


def get_review_scoped(review_id, business_id):
    """Same as get_review, but ALSO checks business_id — the one function callers should use right
    before mutating a review off of an id they didn't just look up themselves, so a tenant owner's
    command can never be pointed (accidentally or otherwise) at a different tenant's row."""
    row = db.query_one(
        "SELECT * FROM tenant_payment_reviews WHERE id = ? AND business_id = ?",
        (review_id, business_id),
    )
    return dict(row) if row is not None else None


def list_for_business(business_id, statuses=None, limit=50):
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        rows = db.query_all(
            f"SELECT * FROM tenant_payment_reviews WHERE business_id = ? AND status IN ({placeholders}) "
            f"ORDER BY id DESC LIMIT ?",
            (business_id, *statuses, limit),
        )
    else:
        rows = db.query_all(
            "SELECT * FROM tenant_payment_reviews WHERE business_id = ? ORDER BY id DESC LIMIT ?",
            (business_id, limit),
        )
    return [dict(r) for r in rows]


def list_pending_for_business(business_id, limit=50):
    return list_for_business(business_id, statuses=("PENDING_OWNER_VERIFICATION",), limit=limit)


def find_by_customer_name(business_id, name_fragment, statuses=("PENDING_OWNER_VERIFICATION",)):
    """This tenant's payment reviews (by default, only ones still awaiting a decision) whose
    customer_name contains name_fragment (case-insensitive) — used to resolve an owner command
    like 'Confirm pembayaran Budi.' Returns a list; more than one match means genuinely ambiguous
    (caller must ask, never guess)."""
    if not name_fragment:
        return []
    rows = list_for_business(business_id, statuses=statuses, limit=200)
    fragment = name_fragment.strip().lower()
    return [r for r in rows if fragment in (r.get("customer_name") or "").strip().lower()]


def update_status(review_id, status, owner_note=None, verified_by=None):
    if status not in STATUSES:
        raise ValueError(f"Unknown tenant_payment_reviews status: {status!r}")
    if status in ("CONFIRMED", "REJECTED"):
        db.execute(
            "UPDATE tenant_payment_reviews SET status = ?, owner_note = ?, verified_by = ?, "
            "verified_at = datetime('now') WHERE id = ?",
            (status, owner_note, verified_by, review_id),
        )
    else:
        db.execute(
            "UPDATE tenant_payment_reviews SET status = ?, owner_note = ? WHERE id = ?",
            (status, owner_note, review_id),
        )
