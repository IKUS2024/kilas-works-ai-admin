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
import json
import os
import re
import base64

import requests

import db

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLIENT_HUB_MODEL = os.environ.get("CLIENT_HUB_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
VISION_MAX_TOKENS = int(os.environ.get("CLIENT_HUB_PAYMENT_VISION_MAX_TOKENS", "1024"))
ALLOWED_PROOF_MIME_TYPES = ("image/jpeg", "image/jpg", "image/png")

VISION_EXTRACTION_SYSTEM_PROMPT = """Kamu membantu tim finance membaca bukti transfer bank/e-wallet yang
diupload customer. Tugasmu HANYA membaca & ekstrak informasi yang BENERAN TERLIHAT di gambar — kamu BUKAN
yang memutuskan apakah pembayaran ini asli/valid, itu keputusan manusia.

ATURAN MUTLAK (WAJIB DIIKUTI PERSIS):
1. JANGAN PERNAH mengarang/menebak field yang gak kelihatan jelas di gambar. Kalau ragu atau gak
   kelihatan, isi null — JANGAN coba "membantu" dengan nebak nominal dari konteks lain, JANGAN
   ngambil angka dari nama file, JANGAN ngarang bank dari asumsi.
2. JANGAN PERNAH bilang bukti ini "asli", "palsu", "100% valid", atau "pasti terverifikasi" —
   kamu cuma baca apa yang ADA di gambar, keputusan validitas itu KELUAR dari scope kamu sepenuhnya.
3. Nominal transfer WAJIB dibaca PERSIS sesuai gambar (jangan tertukar sama nomor rekening/nomor
   referensi/tanggal). Kalau ada beberapa angka mirip nominal di gambar (misal saldo akhir vs nominal
   transfer), ambil yang JELAS berlabel "Nominal"/"Jumlah"/"Total Transfer"/"Amount", bukan saldo/nomor
   lain.
4. Balas HANYA dengan satu objek JSON valid, tanpa markdown code fence, tanpa teks lain sebelum/sesudah.

STRUKTUR JSON WAJIB (null kalau field itu gak kelihatan jelas di gambar):
{
  "amount": number|null (nominal transfer dalam Rupiah, angka murni tanpa "Rp"/titik/koma, misal 999000),
  "currency": string|null (default "IDR" kalau ini transfer Rupiah biasa),
  "bank": string|null (nama bank/e-wallet pengirim, misal "BCA", "GoPay", "Dana"),
  "transaction_date": string|null (format YYYY-MM-DD kalau kelihatan),
  "transaction_time": string|null (format HH:MM kalau kelihatan),
  "reference": string|null (nomor referensi/transaksi kalau ada),
  "sender_name": string|null (nama pengirim kalau kelihatan jelas),
  "receiver_name": string|null (nama penerima kalau kelihatan jelas),
  "status_text": string|null (teks status di bukti kalau ada, misal "Berhasil"/"Success"),
  "readable": boolean (true kalau gambar cukup jelas buat baca info dasar, false kalau blur/gak
    kebaca sama sekali)
}"""

REPAIR_VISION_SYSTEM_PROMPT = """Kamu memperbaiki output JSON yang tidak valid/rusak jadi valid.

Input yang kamu terima ADALAH OUTPUT ASLI (rusak) dari proses ekstraksi bukti transfer — bukan data baru.

ATURAN MUTLAK:
1. Perbaiki HANYA masalah FORMAT/STRUKTUR JSON-nya (kutip yang tidak ditutup, koma salah tempat, dll).
2. JANGAN mengubah/mengarang nilai field yang sudah ada di output rusak itu.
3. Kalau ada bagian yang terpotong dan gak bisa dipastikan lanjutannya, isi null untuk field itu.
4. Balas HANYA dengan objek JSON valid sesuai schema yang diberikan, tanpa teks lain."""


def _call_claude_vision(image_b64, image_mime, extra_instruction=None):
    """Real Claude vision call for payment-proof extraction — SAME raw Messages API request shape
    already used elsewhere in this codebase (see ../app.py's call_claude_tenant_owner() image
    handling: a "type": "image" content block with base64 source, alongside a text block). No new
    SDK/provider — this reuses the exact pattern, just for a different (finance-review) purpose.
    Returns (raw_text, stop_reason, error_str) — same contract as ai_onboarding._call_claude(), so
    truncation is detected via stop_reason == "max_tokens", never only inferred from a parse
    failure."""
    if not ANTHROPIC_API_KEY:
        return None, None, "ANTHROPIC_API_KEY_NOT_CONFIGURED"
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": image_mime, "data": image_b64}},
        {"type": "text", "text": extra_instruction or "Baca bukti transfer ini sesuai instruksi."},
    ]
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLIENT_HUB_MODEL,
                "max_tokens": VISION_MAX_TOKENS,
                "system": VISION_EXTRACTION_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"], data.get("stop_reason"), None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def _call_claude_text_repair(malformed_text):
    """Text-only repair call (no image needed — the repair prompt operates on the malformed JSON
    TEXT itself, not the original image) — same raw Messages API shape, matching ai_onboarding.py's
    own repair-call pattern (max 1 repair attempt, never a loop)."""
    if not ANTHROPIC_API_KEY:
        return None, None, "ANTHROPIC_API_KEY_NOT_CONFIGURED"
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLIENT_HUB_MODEL,
                "max_tokens": VISION_MAX_TOKENS,
                "system": REPAIR_VISION_SYSTEM_PROMPT,
                "messages": [{
                    "role": "user",
                    "content": (
                        f"SCHEMA yang wajib diikuti:\n{VISION_EXTRACTION_SYSTEM_PROMPT}\n\n"
                        f"OUTPUT RUSAK yang perlu diperbaiki:\n{malformed_text or '(kosong)'}"
                    ),
                }],
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"], data.get("stop_reason"), None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def _extract_json_object(text):
    """Strips a stray ```json fence if the model doesn't follow the no-markdown instruction
    exactly (same defensive pattern as ai_onboarding.py's own _extract_json_object)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


_RUPIAH_CLEAN_PATTERN = re.compile(r"[^\d]")


def normalize_rupiah_amount(value):
    """Normalizes common Indonesian receipt amount formats into a plain integer Rupiah value —
    Part F of the request. Handles "Rp999.000", "Rp 999.000", "999.000", "999,000", "IDR 999,000",
    already-numeric values, etc. Returns None (never guesses/defaults to 0) for anything that
    doesn't contain at least one digit."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    digits_only = _RUPIAH_CLEAN_PATTERN.sub("", text)
    if not digits_only:
        return None
    try:
        return int(digits_only)
    except ValueError:
        return None


def extract_payment_proof_fields(image_bytes, image_mime):
    """Real payment-proof vision extraction (Part B of the request) — replaces the previous
    always-None placeholder (_extract_fields_from_image below). Returns a dict with the same
    REQUIRED shape assess_payment_proof() already expects (ai_extracted_amount/_date/_bank/
    ai_reference), PLUS the optional fields (sender_name/receiver_name/status_text/readable) kept
    ONLY for the current review cycle — see this function's own note on why they are never
    persisted to the database (Part C: no migration for optional metadata).

    Safe-failure (Part J): on any API/parse failure (including a failed repair attempt), returns
    an all-None/unreadable result rather than raising — the caller (payment_service.
    upload_payment_proof()) always proceeds to UNDER_REVIEW either way, since a human reviews
    every payment regardless; this function's only job is to give that human as much accurate,
    non-fabricated signal as possible, and "nothing readable" is itself valid, honest signal."""
    b64 = base64.b64encode(image_bytes).decode("ascii") if image_bytes else ""
    if not b64 or image_mime not in ALLOWED_PROOF_MIME_TYPES:
        return _empty_extraction_result(readable=False)

    raw_text, stop_reason, err = _call_claude_vision(b64, image_mime)
    if err:
        print(f"Payment proof vision extraction gagal ({err}) — fallback ke manual review.")
        return _empty_extraction_result(readable=False)

    parsed, parse_err = _safe_parse(raw_text)
    if parse_err or stop_reason == "max_tokens":
        repair_text, _repair_stop, repair_err = _call_claude_text_repair(raw_text)
        if repair_err:
            print(f"Payment proof vision repair call gagal ({repair_err}) — fallback ke manual review.")
            return _empty_extraction_result(readable=False)
        parsed, repair_parse_err = _safe_parse(repair_text)
        if repair_parse_err:
            print(f"Payment proof vision repair TETAP gagal di-parse ({repair_parse_err}) — fallback ke manual review.")
            return _empty_extraction_result(readable=False)

    if not isinstance(parsed, dict):
        return _empty_extraction_result(readable=False)

    return {
        "ai_extracted_amount": normalize_rupiah_amount(parsed.get("amount")),
        "ai_extracted_date": _combine_date_time(parsed.get("transaction_date"), parsed.get("transaction_time")),
        "ai_extracted_bank": _clean_str(parsed.get("bank")),
        "ai_reference": _clean_str(parsed.get("reference")),
        "sender_name": _clean_str(parsed.get("sender_name")),
        "receiver_name": _clean_str(parsed.get("receiver_name")),
        "status_text": _clean_str(parsed.get("status_text")),
        "currency": _clean_str(parsed.get("currency")) or "IDR",
        "readable": bool(parsed.get("readable", True)),
    }


def _empty_extraction_result(readable):
    return {
        "ai_extracted_amount": None, "ai_extracted_date": None, "ai_extracted_bank": None,
        "ai_reference": None, "sender_name": None, "receiver_name": None, "status_text": None,
        "currency": None, "readable": readable,
    }


def _clean_str(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _combine_date_time(date_str, time_str):
    date_str = _clean_str(date_str)
    time_str = _clean_str(time_str)
    if date_str and time_str:
        return f"{date_str} {time_str}"
    return date_str or time_str


def _safe_parse(text):
    try:
        return _extract_json_object(text), None
    except (ValueError, TypeError) as e:
        return None, str(e)


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
    ai_reference, plus optional readable/sender_name/receiver_name/status_text/currency once real
    vision extraction is used — see ai_payment_review.extract_payment_proof_fields()). Until wired
    up (or for a non-image proof, e.g. PDF), all required fields are None and every flag that
    depends on them is simply not raised (never guessed).

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

    # Nothing could be extracted at all — either no real vision call happened yet for this proof
    # (e.g. a non-image file), the model returned every field null, or it explicitly said
    # readable=False (a real vision result can say this even if a stray field happened to parse as
    # non-null, e.g. a guessed currency — the model's own "I could not read this clearly" signal
    # takes priority). Flag it explicitly rather than silently treating "no data" as "clean".
    explicitly_unreadable = extracted_fields.get("readable") is False
    all_required_fields_empty = all(extracted_fields.get(k) is None for k in
           ("ai_extracted_amount", "ai_extracted_date", "ai_extracted_bank", "ai_reference"))
    if explicitly_unreadable or all_required_fields_empty:
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
