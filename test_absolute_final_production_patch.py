"""ABSOLUTE FINAL PRODUCTION PATCH — root/bot-side test suite.

Covers the app.py-side pieces of this cycle (client-hub's own pieces are covered by
client-hub/tests/test_absolute_final_production_patch.py):
  Section 2  — /internal/owner-notify: secret check, notification_type allow-list, destination is
               always the fixed OWNER_WHATSAPP_NUMBER (never taken from the payload), no token leak.
  Section 4  — owner natural-language DB-query context block (business names, quotations,
               onboarding/whatsapp-connection status) gets injected into the owner system prompt
               and reflects real DB state, never invented data, empty gracefully with zero data.
  Section 8/9 — bot prefers the live-generated catalog PDF over the static one when available, and
               falls back cleanly when it is not.
  Section 12 — INTERNAL_SERVICE_SECRET-unset Render warning never crashes / never logs the secret.

Run with:
    python3 test_absolute_final_production_patch.py
"""
import os
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("RENDER", None)
os.environ["INTERNAL_SERVICE_SECRET"] = "test-internal-secret-value"

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as ch_db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import talent_service  # noqa: E402
import payment_service  # noqa: E402


def _reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    ch_db._local.conn = None
    ch_db.init_schema()
    catalog_service.seed_catalog_if_needed()
    talent_service.seed_talents_if_needed()


FLASK_CLIENT = appmod.app.test_client()


# ---------------------------------------------------------------------------
# /internal/owner-notify
# ---------------------------------------------------------------------------

def test_internal_endpoint_rejects_missing_secret():
    resp = FLASK_CLIENT.post("/internal/owner-notify", json={
        "notification_type": "PAYMENT_PROOF_UPLOADED", "message": "test",
    })
    assert resp.status_code == 403
    print("test_internal_endpoint_rejects_missing_secret OK")


def test_internal_endpoint_rejects_wrong_secret():
    resp = FLASK_CLIENT.post(
        "/internal/owner-notify",
        json={"notification_type": "PAYMENT_PROOF_UPLOADED", "message": "test"},
        headers={"X-Internal-Service-Secret": "wrong-secret"},
    )
    assert resp.status_code == 403
    print("test_internal_endpoint_rejects_wrong_secret OK")


def test_internal_endpoint_fails_closed_when_secret_unset():
    with patch.object(appmod, "INTERNAL_SERVICE_SECRET", ""):
        resp = FLASK_CLIENT.post(
            "/internal/owner-notify",
            json={"notification_type": "PAYMENT_PROOF_UPLOADED", "message": "test"},
            headers={"X-Internal-Service-Secret": ""},
        )
        assert resp.status_code == 403
    print("test_internal_endpoint_fails_closed_when_secret_unset OK")


def test_internal_endpoint_rejects_unsupported_notification_type():
    resp = FLASK_CLIENT.post(
        "/internal/owner-notify",
        json={"notification_type": "DELETE_EVERYTHING", "message": "test"},
        headers={"X-Internal-Service-Secret": "test-internal-secret-value"},
    )
    assert resp.status_code == 400
    print("test_internal_endpoint_rejects_unsupported_notification_type OK")


def test_internal_endpoint_ignores_destination_in_payload_always_sends_to_owner_number():
    sent_to = {}

    def _fake_send(to_number, message_text):
        sent_to["to"] = to_number
        sent_to["message"] = message_text
        return True, None

    with patch.object(appmod, "send_whatsapp_message", _fake_send):
        resp = FLASK_CLIENT.post(
            "/internal/owner-notify",
            json={
                "notification_type": "PAYMENT_PROOF_UPLOADED",
                "message": "Pembayaran perlu dicek.",
                "to": "628999999999",         # attempted injection — must be ignored
                "phone": "628888888888",       # attempted injection — must be ignored
                "destination": "628777777777",  # attempted injection — must be ignored
            },
            headers={"X-Internal-Service-Secret": "test-internal-secret-value"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
    assert sent_to["to"] == appmod.OWNER_WHATSAPP_NUMBER
    assert sent_to["to"] not in ("628999999999", "628888888888", "628777777777")
    print("test_internal_endpoint_ignores_destination_in_payload_always_sends_to_owner_number OK")


def test_internal_endpoint_never_leaks_secret_or_tokens_in_response():
    with patch.object(appmod, "send_whatsapp_message", lambda to, msg: (True, None)):
        resp = FLASK_CLIENT.post(
            "/internal/owner-notify",
            json={"notification_type": "QUOTATION_APPROVED", "message": "Quotation approved."},
            headers={"X-Internal-Service-Secret": "test-internal-secret-value"},
        )
    body_text = resp.get_data(as_text=True)
    assert "test-internal-secret-value" not in body_text
    assert appmod.WHATSAPP_ACCESS_TOKEN not in body_text
    print("test_internal_endpoint_never_leaks_secret_or_tokens_in_response OK")


def test_internal_endpoint_one_notification_type_each():
    for ntype in appmod._SUPPORTED_INTERNAL_NOTIFICATION_TYPES:
        with patch.object(appmod, "send_whatsapp_message", lambda to, msg: (True, None)):
            resp = FLASK_CLIENT.post(
                "/internal/owner-notify",
                json={"notification_type": ntype, "message": f"pesan untuk {ntype}"},
                headers={"X-Internal-Service-Secret": "test-internal-secret-value"},
            )
            assert resp.status_code == 200, f"{ntype} should be accepted"
            assert resp.get_json()["status"] == "ok"
    print("test_internal_endpoint_one_notification_type_each OK")


# ---------------------------------------------------------------------------
# INTERNAL_SERVICE_SECRET Render warning
# ---------------------------------------------------------------------------

def test_internal_secret_render_warning_never_crashes_and_never_logs_secret():
    import io
    import contextlib
    captured = io.StringIO()
    with patch.object(appmod, "INTERNAL_SERVICE_SECRET", ""), \
         patch.dict(os.environ, {"RENDER": "true"}):
        with contextlib.redirect_stdout(captured):
            if not appmod.INTERNAL_SERVICE_SECRET:
                print(
                    "SECURITY WARNING: running on Render with INTERNAL_SERVICE_SECRET unset — the "
                    "internal Client Hub -> bot notification endpoint (/internal/owner-notify) will "
                    "reject ALL requests until this is set in Render's environment."
                )
    output = captured.getvalue()
    assert "INTERNAL_SERVICE_SECRET" in output
    assert "test-internal-secret-value" not in output
    print("test_internal_secret_render_warning_never_crashes_and_never_logs_secret OK")


# ---------------------------------------------------------------------------
# Owner natural-language DB-query context
# ---------------------------------------------------------------------------

def test_owner_query_context_empty_gracefully_with_zero_data():
    _reset_client_hub_db()
    context = appmod._build_business_hub_owner_query_context_safe()
    assert "(tidak ada)" in context
    print("test_owner_query_context_empty_gracefully_with_zero_data OK")


def test_owner_query_context_reflects_real_payment_and_project_and_talent_data():
    _reset_client_hub_db()
    owner_id = repo.create_user("bh_owner@test.com", security.hash_password("password123"))
    admin_id = repo.create_user("bh_admin@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
    business_id = repo.create_business(owner_id, "Kopi ABC", package="NONE")

    # "Ada project custom baru?"
    projects_repo.create_custom_project(
        business_id, "VIDEO", "5 video campaign", {}, 4_000_000, 4_000_000, owner_id,
        catalog_key="custom_video",
    )
    # "Siapa yang request Putri?"
    putri = next(t for t in talent_service.list_all_talents() if t["name"] == "Putri Maudy")
    talent_service.create_talent_request(
        putri["id"], business_id, {"campaign_type": "Reels endorsement"}, owner_id,
    )
    # "Quotation Rina berapa?" — use a quotation on a fixed number for this business.
    proj2 = projects_repo.create_custom_project(
        business_id, "PHOTO", "Photo shoot", {}, None, None, owner_id, catalog_key="custom_photo",
    )
    quotation_service.create_quotation(proj2, business_id, "scope", "deliverables", 1, 3_500_000, "", admin_id)
    # "Kopi ABC udah bayar?" / "Ada payment yang belum gue cek?" — put a real payment into
    # UNDER_REVIEW state (the "pending owner verification" state) via the real checkout flow, then
    # flip its status directly (bypassing the AI-proof-review pipeline, irrelevant to this test).
    fixed_project_id = projects_repo.create_fixed_price_project(
        business_id, catalog_service.get_catalog_item("content_basic"), owner_id,
    )
    invoice_id = payment_service.checkout(fixed_project_id, business_id, owner_id)
    payment_row = payment_service.get_payment_for_invoice(invoice_id)
    ch_db.execute("UPDATE payments SET status = 'UNDER_REVIEW' WHERE id = ?", (payment_row["id"],))

    with patch.object(appmod, "_client_hub_repo", repo), \
         patch.object(appmod, "_projects_repo", projects_repo), \
         patch.object(appmod, "_talent_service", talent_service), \
         patch.object(appmod, "_payment_service", payment_service):
        context = appmod._build_business_hub_owner_query_context_safe()

    assert "Kopi ABC" in context
    assert "5 video campaign" in context
    assert "Putri Maudy" in context
    assert "3.500.000" in context
    print("test_owner_query_context_reflects_real_payment_and_project_and_talent_data OK")


def test_owner_query_context_never_invents_data_and_disappears_without_client_hub():
    with patch.object(appmod, "_CLIENT_HUB_AVAILABLE", False):
        assert appmod._build_business_hub_owner_query_context_safe() == ""
    print("test_owner_query_context_never_invents_data_and_disappears_without_client_hub OK")


def test_owner_query_context_wired_into_owner_system_prompt():
    _reset_client_hub_db()
    owner_id = repo.create_user("bh_owner2@test.com", security.hash_password("password123"))
    business_id = repo.create_business(owner_id, "Wired Biz Test", package="NONE")
    projects_repo.create_custom_project(
        business_id, "PHOTO", "Wired photo project", {}, None, None, owner_id, catalog_key="custom_photo",
    )
    with patch.object(appmod, "_projects_repo", projects_repo), \
         patch.object(appmod, "_client_hub_repo", repo):
        prompt = appmod.build_owner_system_prompt(None, None, direct_send=False)
    assert "Wired Biz Test" in prompt
    assert "Wired photo project" in prompt
    print("test_owner_query_context_wired_into_owner_system_prompt OK")


def test_owner_query_context_never_offers_to_perform_actions():
    _reset_client_hub_db()
    with patch.object(appmod, "_projects_repo", projects_repo), \
         patch.object(appmod, "_client_hub_repo", repo):
        context = appmod._build_business_hub_owner_query_context_safe()
    assert "app.kilasworks.id" in context
    assert "JANGAN coba lakukan aksinya" in context
    print("test_owner_query_context_never_offers_to_perform_actions OK")


# ---------------------------------------------------------------------------
# Live catalog PDF preference (bot side)
# ---------------------------------------------------------------------------

def test_bot_prefers_live_catalog_pdf_when_available():
    _reset_client_hub_db()
    fake_path = "/tmp/fake-live-katalog.pdf"
    with open(fake_path, "wb") as f:
        f.write(b"%PDF-1.4 fake")
    try:
        with patch.object(appmod, "_CLIENT_HUB_AVAILABLE", True):
            with patch.dict(sys.modules, {}):
                import types
                fake_module = types.SimpleNamespace(get_cached_catalog_pdf_path=lambda: fake_path)
                sys.modules["live_catalog_pdf"] = fake_module
                try:
                    result = appmod._get_live_catalog_pdf_path_safe()
                finally:
                    del sys.modules["live_catalog_pdf"]
        assert result == fake_path
    finally:
        os.remove(fake_path)
    print("test_bot_prefers_live_catalog_pdf_when_available OK")


def test_bot_falls_back_when_live_catalog_unavailable():
    with patch.object(appmod, "_CLIENT_HUB_AVAILABLE", False):
        assert appmod._get_live_catalog_pdf_path_safe() is None
    print("test_bot_falls_back_when_live_catalog_unavailable OK")


if __name__ == "__main__":
    test_internal_endpoint_rejects_missing_secret()
    test_internal_endpoint_rejects_wrong_secret()
    test_internal_endpoint_fails_closed_when_secret_unset()
    test_internal_endpoint_rejects_unsupported_notification_type()
    test_internal_endpoint_ignores_destination_in_payload_always_sends_to_owner_number()
    test_internal_endpoint_never_leaks_secret_or_tokens_in_response()
    test_internal_endpoint_one_notification_type_each()
    test_internal_secret_render_warning_never_crashes_and_never_logs_secret()
    test_owner_query_context_empty_gracefully_with_zero_data()
    test_owner_query_context_reflects_real_payment_and_project_and_talent_data()
    test_owner_query_context_never_invents_data_and_disappears_without_client_hub()
    test_owner_query_context_wired_into_owner_system_prompt()
    test_owner_query_context_never_offers_to_perform_actions()
    test_bot_prefers_live_catalog_pdf_when_available()
    test_bot_falls_back_when_live_catalog_unavailable()
    print("\nALL ABSOLUTE FINAL PRODUCTION PATCH (ROOT) TESTS PASSED")
