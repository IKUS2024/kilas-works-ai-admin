"""AI payment-proof assistance — Business Hub V2, Phase C (Section 13), hardened per the payment
verification strengthening cycle.

STRICT RULE from the master spec: the AI may extract/flag fields as a risk/review assistant, but it
must NEVER claim a payment is "definitely authentic." This module's return value has no
"authentic"/"verified"/"100% valid" field at all — only extracted candidate values and risk flags,
using neutral comparison wording ("data terlihat sesuai dengan invoice"), never an authenticity
verdict. The final decision is always made by a KILAS_ADMIN action in routes_admin.py, never by
this module — see payment_service.verify_payment()/reject_payment(), the only two functions that
ever set a payment to VERIFIED or REJECTED.

RISK FLAG VOCABULARY (stored in payments.ai_risk_flags_json, a JSON list of these strings):
  AMOUNT_MISMATCH              — extracted amount != invoice amount (or DP amount, if applicable)
  DUPLICATE_REFERENCE_CANDIDATE — same ai_reference already used on a different payment
  DUPLICATE_FILE_CANDIDATE      — same proof file (by SHA-256 hash) already used on a different payment
  UNREADABLE                    — nothing could be extracted from the proof at all
  SUSPICIOUS_VISUAL_ANOMALY     — placeholder category for a future real vision pass (font/spacing/
                                   crop/edit-area anomalies) — never raised by this V1 implementation
                                   (see _extract_fields_from_image()'s own docstring), but the review
                                   UI/derive_review_status() already knows how to display it once a
                                   real vision call starts including it, so wiring that in later is a
                                   change to ONE function, not a new pipeline.

V1 implementation note: real OCR/vision extraction of a transfer receipt image would call the same
Claude vision pattern already used elsewhere in this codebase (ai_onboarding.py, and the production
bot's own bukti-transfer reading). That real API call is NOT wired up in this phase — this module
provides the full pipeline shape (duplicate detection via both file hash and reference, amount/
invoice mismatch flags) using whatever ai_extracted_amount/ai_extracted_date/ai_reference values are
passed in, so the review pipeline and its safety rules (never claims authenticity) are complete and
tested now, and plugging in real vision extraction later is a single well-isolated function to
implement (`_extract_fields_from_image`) without touching anything downstream of it.
"""
import hashlib

import db


def compute_file_hash(file_bytes):
    """SHA-256 hex digest of the raw proof file bytes — the file-hash half of duplicate detection
    (Section 6 of the request). Deliberately a plain content hash, not a perceptual/image hash: a
    perceptual hash needs an image-processing dependency this codebase doesn't currently have, and
    would only additionally catch a re-COMPRESSED/re-SAVED copy of the same screenshot — a real but
    narrower gap than the exact-file-reuse case this already closes. Documented as a known
    limitation in the final report's NEEDS REVIEW section, not silently pretended to be solved."""
    return hashlib.sha256(file_bytes or b"").hexdigest()


def _extract_fields_from_image(image_bytes):
    """Placeholder for real Claude-vision extraction (see module docstring). Returns a dict with
    the same shape real extraction would produce, all None until wired up — callers must treat
    None as \"could not extract,\" never as \"amount is zero\" or similar wrong defaults."""
    return {
        "ai_extracted_amount": None,
        "ai_extracted_date": None,
        "ai_extracted_bank": None,
        "ai_reference": None,
    }


def assess_payment_proof(payment_id, business_id, invoice_amount, extracted_fields=None,
                          proof_file_hash=None):
    """Returns risk-assessment fields to store on the payments row. NEVER returns any field that
    could be read as "this proof is authentic" — only comparison flags and a bounded match_score
    that is explicitly documented (in the admin UI) as a review aid, not a verdict.

    extracted_fields: optional dict (ai_extracted_amount, ai_extracted_date, ai_extracted_bank,
    ai_reference) — pass this in once real image extraction exists; until then all fields are None
    and every flag that depends on them is simply not raised (never guessed).

    proof_file_hash: SHA-256 hex digest of the uploaded proof file's raw bytes (see
    compute_file_hash() above) — always available today (no AI needed), so this is the PRIMARY
    duplicate signal right now; ai_reference-based matching is an additional signal for once real
    extraction exists.
    """
    extracted_fields = extracted_fields or _extract_fields_from_image(None)
    risk_flags = []

    ai_extracted_amount = extracted_fields.get("ai_extracted_amount")
    if ai_extracted_amount is not None and invoice_amount is not None:
        if ai_extracted_amount != invoice_amount:
            risk_flags.append("AMOUNT_MISMATCH")

    duplicate_by_reference = _is_duplicate_reference(payment_id, business_id, extracted_fields.get("ai_reference"))
    duplicate_by_file = _is_duplicate_file_hash(payment_id, proof_file_hash)
    duplicate_candidate = duplicate_by_reference or duplicate_by_file
    if duplicate_by_reference:
        risk_flags.append("DUPLICATE_REFERENCE_CANDIDATE")
    if duplicate_by_file:
        risk_flags.append("DUPLICATE_FILE_CANDIDATE")

    # Nothing could be extracted at all (no real vision extraction wired up yet, or a genuinely
    # unreadable image once it is) — flag it explicitly rather than silently treating "no data" the
    # same as "clean, nothing to flag".
    if all(extracted_fields.get(k) is None for k in
           ("ai_extracted_amount", "ai_extracted_date", "ai_extracted_bank", "ai_reference")):
        risk_flags.append("UNREADABLE")

    # match_score is a simple, explainable heuristic — NOT a fraud-detection model. 1.0 only when
    # every extractable field agrees; None when nothing could be extracted (no false confidence).
    match_score = None
    if ai_extracted_amount is not None:
        match_score = 1.0 if ai_extracted_amount == invoice_amount else 0.0

    return {
        "ai_extracted_amount": ai_extracted_amount,
        "ai_extracted_date": extracted_fields.get("ai_extracted_date"),
        "ai_extracted_bank": extracted_fields.get("ai_extracted_bank"),
        "ai_reference": extracted_fields.get("ai_reference"),
        "ai_risk_flags": risk_flags,
        "ai_match_score": match_score,
        "duplicate_candidate": duplicate_candidate,
        "proof_file_hash": proof_file_hash,
    }


def _is_duplicate_reference(payment_id, business_id, reference):
    if not reference:
        return False
    existing = db.query_all(
        "SELECT id FROM payments WHERE ai_reference = ? AND id != ?",
        (reference, payment_id),
    )
    return len(existing) > 0


def _is_duplicate_file_hash(payment_id, proof_file_hash):
    """Deliberately NOT tenant/business-scoped: the exact same proof file being reused for a
    SECOND invoice is suspicious regardless of whether it's the same business trying twice or the
    file being reused across two different businesses entirely — both are real duplicate-proof
    fraud patterns this check should catch, not narrow away."""
    if not proof_file_hash:
        return False
    existing = db.query_all(
        "SELECT id FROM payments WHERE proof_file_hash = ? AND id != ?",
        (proof_file_hash, payment_id),
    )
    return len(existing) > 0
