"""AI payment-proof assistance — Business Hub V2, Phase C (Section 13).

STRICT RULE from the master spec: the AI may extract/flag fields as a risk/review assistant, but it
must NEVER claim a payment is "definitely authentic." This module's return value has no
"authentic"/"verified" field at all — only extracted candidate values and risk flags. The final
decision is always made by a KILAS_ADMIN action in routes_admin.py, never by this module.

V1 implementation note: real OCR/vision extraction of a transfer receipt image would call the same
Claude vision pattern already used elsewhere in this codebase (ai_onboarding.py, and the production
bot's own bukti-transfer reading). That real API call is NOT wired up in this phase — this module
provides the full pipeline shape (duplicate detection, amount/invoice mismatch flags) using
whatever ai_extracted_amount/ai_extracted_date/ai_reference values are passed in, so the review
pipeline and its safety rules (never claims authenticity) are complete and tested now, and plugging
in real vision extraction later is a single well-isolated function to implement
(`_extract_fields_from_image`) without touching anything downstream of it.
"""
import db


def _extract_fields_from_image(image_bytes):
    """Placeholder for real Claude-vision extraction (see module docstring). Returns a dict with
    the same shape real extraction would produce, all None until wired up — callers must treat
    None as "could not extract," never as "amount is zero" or similar wrong defaults."""
    return {
        "ai_extracted_amount": None,
        "ai_extracted_date": None,
        "ai_extracted_bank": None,
        "ai_reference": None,
    }


def assess_payment_proof(payment_id, business_id, invoice_amount, extracted_fields=None):
    """Returns risk-assessment fields to store on the payments row. NEVER returns any field that
    could be read as "this proof is authentic" — only comparison flags and a bounded match_score
    that is explicitly documented (in the admin UI) as a review aid, not a verdict.

    extracted_fields: optional dict (ai_extracted_amount, ai_extracted_date, ai_extracted_bank,
    ai_reference) — pass this in once real image extraction exists; until then all fields are None
    and every flag that depends on them is simply not raised (never guessed).
    """
    extracted_fields = extracted_fields or _extract_fields_from_image(None)
    risk_flags = []

    ai_extracted_amount = extracted_fields.get("ai_extracted_amount")
    if ai_extracted_amount is not None and invoice_amount is not None:
        if ai_extracted_amount != invoice_amount:
            risk_flags.append("AMOUNT_MISMATCH")

    duplicate_candidate = _is_duplicate_reference(payment_id, business_id, extracted_fields.get("ai_reference"))
    if duplicate_candidate:
        risk_flags.append("DUPLICATE_REFERENCE_CANDIDATE")

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
    }


def _is_duplicate_reference(payment_id, business_id, reference):
    if not reference:
        return False
    existing = db.query_all(
        "SELECT id FROM payments WHERE ai_reference = ? AND id != ?",
        (reference, payment_id),
    )
    return len(existing) > 0
