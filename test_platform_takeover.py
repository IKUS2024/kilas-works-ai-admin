"""Platform Inbox / Human Takeover regression tests — Kilas Works' OWN WhatsApp number
(tenant_id=None), backed by client-hub/platform_inbox_service.py + the
platform_wa_conversation_state table (migration 0016_platform_takeover).

This file exists specifically to prove the test-harness fix (_test_bootstrap.py) did not
accidentally weaken app.py's `_get_conversation_mode_safe()` fail-safe design while making it
possible to test the REAL AI_ACTIVE path (previously every webhook-driven test silently hit the
fail-safe branch because Client Hub's DB didn't exist in the test process at all).

Covers exactly the 3 scenarios requested:
  1. AI_ACTIVE (the default / no takeover row) -> Kilas Works' own AI may respond normally.
  2. HUMAN_TAKEOVER (explicitly set, e.g. after a manual reply from the Client Hub Inbox) -> AI
     stays completely silent for that customer.
  3. A genuine DB/read failure (Client Hub unreachable / query error) -> _get_conversation_mode_safe
     still fails SAFE to HUMAN_TAKEOVER, exactly as before this test-harness fix — the AI never
     talks over a possible human operator just because a health check failed.

Run with:
    python3 test_platform_takeover.py
"""
import os
import sys
import json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "kilas-global-123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as chdb  # noqa: E402
import platform_inbox_service  # noqa: E402

client = appmod.app.test_client()


def reset_state():
    appmod.conversations.clear()
    appmod.customer_names.clear()
    appmod.followup_state.clear()
    chdb.execute("DELETE FROM platform_wa_conversation_state")


def _text_payload(from_number, text, phone_number_id="kilas-global-123"):
    return {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": phone_number_id},
            "messages": [{"id": f"wamid.{from_number}", "from": from_number,
                          "type": "text", "text": {"body": text}}],
        }}]}]
    }


# ---------------------------------------------------------------------------
# 1. AI_ACTIVE (default, no takeover row at all) -> Kilas Works AI may respond
# ---------------------------------------------------------------------------
def test_ai_active_default_kilas_ai_may_respond():
    reset_state()
    number = "628700111001"
    assert platform_inbox_service.get_state(number) == "AI_ACTIVE", \
        "no row yet must default to AI_ACTIVE, not silently block"

    with patch.object(appmod, "call_claude", return_value="Halo Kak, ada yang bisa dibantu?"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook", data=json.dumps(_text_payload(number, "halo")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_post.called, "AI_ACTIVE must let the bot actually reply"
    print("test_ai_active_default_kilas_ai_may_respond OK")


# ---------------------------------------------------------------------------
# 2. HUMAN_TAKEOVER (explicitly set) -> AI stays silent
# ---------------------------------------------------------------------------
def test_human_takeover_ai_stays_silent():
    reset_state()
    number = "628700111002"
    platform_inbox_service.start_human_takeover(number, actor_user_id=None)
    assert platform_inbox_service.get_state(number) == "HUMAN_TAKEOVER"

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook", data=json.dumps(_text_payload(number, "halo, masih di sini?")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_human_takeover_ai_stays_silent OK")


def test_return_to_ai_resumes_normal_replies():
    """Regression guard: after a human hands the conversation back, the AI must resume using
    conversation history — not stay permanently silent."""
    reset_state()
    number = "628700111003"
    platform_inbox_service.start_human_takeover(number, actor_user_id=None)
    assert platform_inbox_service.get_state(number) == "HUMAN_TAKEOVER"
    platform_inbox_service.return_to_ai(number, actor_user_id=None)
    assert platform_inbox_service.get_state(number) == "AI_ACTIVE"

    with patch.object(appmod, "call_claude", return_value="Siap Kak, lanjut ya."), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook", data=json.dumps(_text_payload(number, "masih lanjut ya kak")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_post.called, "returning to AI_ACTIVE must let the bot reply again"
    print("test_return_to_ai_resumes_normal_replies OK")


# ---------------------------------------------------------------------------
# 3. Client Hub package unavailable -> fail closed for both Kilas + tenants
# ---------------------------------------------------------------------------
def test_client_hub_unavailable_fails_closed_for_kilas_and_tenant():
    """If Client Hub cannot be loaded at all, there is no trustworthy takeover state.

    Both Kilas Works' own number and tenant numbers must therefore fail closed to
    HUMAN_TAKEOVER rather than risk AI + human double replies.
    """
    reset_state()
    number = "628700111005"

    with patch.object(appmod, "_CLIENT_HUB_AVAILABLE", False):
        assert appmod._get_conversation_mode_safe(None, number) == "HUMAN_TAKEOVER", \
            "Kilas Works must fail closed when Client Hub is unavailable"
        assert appmod._get_conversation_mode_safe("tenant-test-001", number) == "HUMAN_TAKEOVER", \
            "tenant conversations must also fail closed when Client Hub is unavailable"

    print("test_client_hub_unavailable_fails_closed_for_kilas_and_tenant OK")


# ---------------------------------------------------------------------------
# 4. A genuine DB/read failure still fails safe to HUMAN_TAKEOVER
# ---------------------------------------------------------------------------
def test_genuine_read_failure_fails_safe_to_human_takeover():
    reset_state()
    number = "628700111004"

    # Simulate exactly the failure this whole test-harness fix was about — a broken/unreachable
    # Client Hub DB read — WITHOUT touching _get_conversation_mode_safe() itself, so this proves
    # the EXISTING fail-safe except-block still does its job.
    with patch.object(platform_inbox_service, "get_state", side_effect=RuntimeError("simulated DB outage")):
        mode = appmod._get_conversation_mode_safe(None, number)
    assert mode == "HUMAN_TAKEOVER", \
        "a genuine read failure must fail SAFE to HUMAN_TAKEOVER, never silently assume AI_ACTIVE"

    # And end-to-end via the real webhook: the AI must not reply while this failure is happening.
    with patch.object(platform_inbox_service, "get_state", side_effect=RuntimeError("simulated DB outage")), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook", data=json.dumps(_text_payload(number, "halo")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_genuine_read_failure_fails_safe_to_human_takeover OK")


if __name__ == "__main__":
    test_ai_active_default_kilas_ai_may_respond()
    test_human_takeover_ai_stays_silent()
    test_return_to_ai_resumes_normal_replies()
    test_client_hub_unavailable_fails_closed_for_kilas_and_tenant()
    test_genuine_read_failure_fails_safe_to_human_takeover()
    print("ALL PLATFORM TAKEOVER TESTS PASSED")
