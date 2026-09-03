"""Real payment-proof vision extraction — regression tests (Part B/L of the request).

Run with:
    cd client-hub && python3 tests/test_payment_vision_extraction.py
"""
import os
import sys
import json
import base64
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import ai_payment_review


def _fake_response(text, stop_reason="end_turn", status_code=200):
    resp = type("R", (), {})()
    resp.status_code = status_code
    resp.raise_for_status = (lambda: None) if status_code == 200 else _raise
    resp.json = lambda: {"content": [{"text": text}], "stop_reason": stop_reason}
    return resp


def _raise():
    raise Exception("HTTP error")


VALID_VISION_JSON = json.dumps({
    "amount": 999000, "currency": "IDR", "bank": "BCA", "transaction_date": "2026-09-03",
    "transaction_time": "08:42", "reference": "TRX123456789", "sender_name": "Budi Santoso",
    "receiver_name": "Kilas Works", "status_text": "Berhasil", "readable": True,
})


# ---------------------------------------------------------------------------
# 1/2/3 — JPG/PNG actually passed into the vision request, correct MIME type.
# ---------------------------------------------------------------------------
def test_jpg_image_passed_into_vision_request():
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _fake_response(VALID_VISION_JSON)

    fake_bytes = b"\xff\xd8\xff\xe0fakejpegdata"
    with patch.object(ai_payment_review.requests, "post", side_effect=fake_post):
        result = ai_payment_review.extract_payment_proof_fields(fake_bytes, "image/jpeg")

    content = captured["payload"]["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"] == base64.b64encode(fake_bytes).decode("ascii")
    assert result["ai_extracted_amount"] == 999000
    print("test_jpg_image_passed_into_vision_request OK")


def test_png_image_passed_into_vision_request():
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _fake_response(VALID_VISION_JSON)

    fake_bytes = b"\x89PNGfakepngdata"
    with patch.object(ai_payment_review.requests, "post", side_effect=fake_post):
        ai_payment_review.extract_payment_proof_fields(fake_bytes, "image/png")

    content = captured["payload"]["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["media_type"] == "image/png"
    print("test_png_image_passed_into_vision_request OK")


def test_unsupported_mime_type_never_calls_vision_api():
    with patch.object(ai_payment_review.requests, "post") as mock_post:
        result = ai_payment_review.extract_payment_proof_fields(b"fake pdf bytes", "application/pdf")
    mock_post.assert_not_called()
    assert result["readable"] is False
    assert result["ai_extracted_amount"] is None
    print("test_unsupported_mime_type_never_calls_vision_api OK")


# ---------------------------------------------------------------------------
# 4/5 — valid vision result extracts amount; bank/date/time/reference survive.
# ---------------------------------------------------------------------------
def test_valid_vision_result_extracts_all_fields():
    with patch.object(ai_payment_review.requests, "post", return_value=_fake_response(VALID_VISION_JSON)):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert result["ai_extracted_amount"] == 999000
    assert result["ai_extracted_bank"] == "BCA"
    assert result["ai_extracted_date"] == "2026-09-03 08:42"
    assert result["ai_reference"] == "TRX123456789"
    assert result["sender_name"] == "Budi Santoso"
    assert result["receiver_name"] == "Kilas Works"
    assert result["status_text"] == "Berhasil"
    assert result["readable"] is True
    print("test_valid_vision_result_extracts_all_fields OK")


def test_json_inside_markdown_fence_still_parses():
    fenced = f"```json\n{VALID_VISION_JSON}\n```"
    with patch.object(ai_payment_review.requests, "post", return_value=_fake_response(fenced)):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert result["ai_extracted_amount"] == 999000
    print("test_json_inside_markdown_fence_still_parses OK")


# ---------------------------------------------------------------------------
# 6 — Rp999.000 (and other Indonesian formats) normalize to 999000.
# ---------------------------------------------------------------------------
def test_rupiah_amount_normalization():
    cases = {
        "Rp999.000": 999000, "Rp 999.000": 999000, "999.000": 999000, "999,000": 999000,
        "IDR 999,000": 999000, "Rp1.000.000": 1000000, 999000: 999000, 999000.0: 999000,
        None: None, "": None, "no digits here": None,
    }
    for raw, expected in cases.items():
        assert ai_payment_review.normalize_rupiah_amount(raw) == expected, (raw, expected)
    print("test_rupiah_amount_normalization OK")


# ---------------------------------------------------------------------------
# 7/8 — invoice vs detected amount match/mismatch (via assess_payment_proof).
# ---------------------------------------------------------------------------
def test_invoice_999000_vs_detected_999000_match():
    assessment = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": 999000, "ai_extracted_date": None,
                                         "ai_extracted_bank": "BCA", "ai_reference": None, "readable": True},
    )
    assert "AMOUNT_MISMATCH" not in assessment["ai_risk_flags"]
    print("test_invoice_999000_vs_detected_999000_match OK")


def test_invoice_999000_vs_detected_990000_mismatch():
    assessment = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": 990000, "ai_extracted_date": None,
                                         "ai_extracted_bank": "BCA", "ai_reference": None, "readable": True},
    )
    assert "AMOUNT_MISMATCH" in assessment["ai_risk_flags"]
    print("test_invoice_999000_vs_detected_990000_mismatch OK")


# ---------------------------------------------------------------------------
# 9 — unreadable amount -> manual review (explicit readable=False signal honored).
# ---------------------------------------------------------------------------
def test_explicit_unreadable_signal_triggers_manual_review_even_with_a_stray_field():
    """A vision result that says readable=False must be treated as unreadable even if some OTHER
    field happened to come back non-null (e.g. a guessed currency) — the model's own honesty
    signal takes priority over incidental partial data."""
    assessment = ai_payment_review.assess_payment_proof(
        1, 1, 999000, extracted_fields={"ai_extracted_amount": None, "ai_extracted_date": None,
                                         "ai_extracted_bank": None, "ai_reference": None,
                                         "currency": "IDR", "readable": False},
    )
    assert "UNREADABLE" in assessment["ai_risk_flags"]
    print("test_explicit_unreadable_signal_triggers_manual_review_even_with_a_stray_field OK")


# ---------------------------------------------------------------------------
# 10 — malformed AI response -> ONE repair attempt -> safe failure if still malformed.
# ---------------------------------------------------------------------------
def test_malformed_response_triggers_one_repair_attempt_then_succeeds():
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _fake_response('{"amount": 999000, "bank": "BCA"')  # malformed, unterminated
        return _fake_response(VALID_VISION_JSON)  # repair attempt succeeds

    with patch.object(ai_payment_review.requests, "post", side_effect=fake_post):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert call_count["n"] == 2, "must attempt exactly one repair, not zero, not a loop"
    assert result["ai_extracted_amount"] == 999000
    print("test_malformed_response_triggers_one_repair_attempt_then_succeeds OK")


def test_both_attempts_malformed_safe_failure_never_raises():
    def fake_post(url, headers=None, json=None, timeout=None):
        return _fake_response('{"amount": 999000, broken json here')

    with patch.object(ai_payment_review.requests, "post", side_effect=fake_post):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert result["readable"] is False
    assert result["ai_extracted_amount"] is None
    print("test_both_attempts_malformed_safe_failure_never_raises OK")


def test_no_infinite_retry_loop_max_two_calls():
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        return _fake_response("not json at all")

    with patch.object(ai_payment_review.requests, "post", side_effect=fake_post):
        ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert call_count["n"] == 2, f"must be exactly initial+1 repair, got {call_count['n']} calls"
    print("test_no_infinite_retry_loop_max_two_calls OK")


# ---------------------------------------------------------------------------
# 11 — AI API failure -> safe failure, never raises.
# ---------------------------------------------------------------------------
def test_api_failure_safe_failure_never_raises():
    with patch.object(ai_payment_review.requests, "post", side_effect=Exception("network down")):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert result["readable"] is False
    assert result["ai_extracted_amount"] is None
    print("test_api_failure_safe_failure_never_raises OK")


def test_missing_api_key_safe_failure():
    with patch.object(ai_payment_review, "ANTHROPIC_API_KEY", ""):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert result["readable"] is False
    print("test_missing_api_key_safe_failure OK")


# ---------------------------------------------------------------------------
# 12 — truncation (stop_reason=max_tokens) triggers repair, same as a parse failure.
# ---------------------------------------------------------------------------
def test_truncated_response_stop_reason_triggers_repair():
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _fake_response('{"amount": 999000, "bank": "B', stop_reason="max_tokens")
        return _fake_response(VALID_VISION_JSON)

    with patch.object(ai_payment_review.requests, "post", side_effect=fake_post):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert call_count["n"] == 2
    assert result["ai_extracted_amount"] == 999000
    print("test_truncated_response_stop_reason_triggers_repair OK")


# ---------------------------------------------------------------------------
# 13 — anti-hallucination: unreadable fields are null, never invented.
# ---------------------------------------------------------------------------
def test_partial_readability_only_visible_fields_extracted():
    partial_json = json.dumps({
        "amount": 999000, "currency": "IDR", "bank": None, "transaction_date": None,
        "transaction_time": None, "reference": None, "sender_name": None, "receiver_name": None,
        "status_text": None, "readable": True,
    })
    with patch.object(ai_payment_review.requests, "post", return_value=_fake_response(partial_json)):
        result = ai_payment_review.extract_payment_proof_fields(b"fakejpeg", "image/jpeg")
    assert result["ai_extracted_amount"] == 999000
    assert result["ai_extracted_bank"] is None
    assert result["ai_reference"] is None
    print("test_partial_readability_only_visible_fields_extracted OK")


if __name__ == "__main__":
    test_jpg_image_passed_into_vision_request()
    test_png_image_passed_into_vision_request()
    test_unsupported_mime_type_never_calls_vision_api()
    test_valid_vision_result_extracts_all_fields()
    test_json_inside_markdown_fence_still_parses()
    test_rupiah_amount_normalization()
    test_invoice_999000_vs_detected_999000_match()
    test_invoice_999000_vs_detected_990000_mismatch()
    test_explicit_unreadable_signal_triggers_manual_review_even_with_a_stray_field()
    test_malformed_response_triggers_one_repair_attempt_then_succeeds()
    test_both_attempts_malformed_safe_failure_never_raises()
    test_no_infinite_retry_loop_max_two_calls()
    test_api_failure_safe_failure_never_raises()
    test_missing_api_key_safe_failure()
    test_truncated_response_stop_reason_triggers_repair()
    test_partial_readability_only_visible_fields_extracted()
    print("ALL PAYMENT VISION EXTRACTION TESTS PASSED")
