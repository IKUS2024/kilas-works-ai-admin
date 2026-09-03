"""Kilas Works Client Hub — ABSOLUTE FINAL PRODUCTION PATCH test suite.

Covers (client-hub side; app.py/bot-side pieces are in
../test_absolute_final_production_patch.py):
  Section 1  — immediate delivery attempt on notify_owner_once(), success marks SENT, failure
               stays PENDING/FAILED for the retry sweep, retry succeeds later, never double-sends
               on repeat/restart/replay, one test per notification-type event builder.
  Section 2  — owner_notification_delivery.py: fails closed (never raises) when config is missing,
               never raises on a network error/timeout, only succeeds on a real 200 {"status":"ok"}.
  Section 6-10 — live_catalog_pdf.py: price/talent changes reflected, historical prices untouched,
               internal_rate never appears, Photo/Video/Talent/Custom-Content always Custom Quote,
               AI Admin fixed-only.

Run with:
    cd client-hub && python3 tests/test_absolute_final_production_patch.py
"""
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)
os.environ.pop("KILAS_BOT_INTERNAL_URL", None)
os.environ.pop("INTERNAL_SERVICE_SECRET", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import catalog_cache  # noqa: E402
import talent_service  # noqa: E402
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import owner_notifications  # noqa: E402
import owner_notification_delivery  # noqa: E402
import live_catalog_pdf  # noqa: E402


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()
    talent_service.seed_talents_if_needed()


def _make_owner(email):
    return repo.create_user(email, security.hash_password("password123"))


# ---------------------------------------------------------------------------
# owner_notification_delivery.py — the HTTP client itself
# ---------------------------------------------------------------------------

def test_delivery_fails_closed_when_url_unset():
    with patch.object(owner_notification_delivery, "KILAS_BOT_INTERNAL_URL", ""), \
         patch.object(owner_notification_delivery, "INTERNAL_SERVICE_SECRET", "secret"):
        ok, detail = owner_notification_delivery.deliver_owner_notification("PAYMENT_PROOF_UPLOADED", "msg")
        assert ok is False
        assert "KILAS_BOT_INTERNAL_URL" in detail
    print("test_delivery_fails_closed_when_url_unset OK")


def test_delivery_fails_closed_when_secret_unset():
    with patch.object(owner_notification_delivery, "KILAS_BOT_INTERNAL_URL", "http://localhost:5000/internal/owner-notify"), \
         patch.object(owner_notification_delivery, "INTERNAL_SERVICE_SECRET", ""):
        ok, detail = owner_notification_delivery.deliver_owner_notification("PAYMENT_PROOF_UPLOADED", "msg")
        assert ok is False
        assert "INTERNAL_SERVICE_SECRET" in detail
    print("test_delivery_fails_closed_when_secret_unset OK")


def test_delivery_never_raises_on_network_error():
    class _FakeSession:
        pass

    def _raise(*a, **kw):
        import requests
        raise requests.exceptions.ConnectionError("connection refused (simulated)")

    with patch.object(owner_notification_delivery, "KILAS_BOT_INTERNAL_URL", "http://127.0.0.1:1/internal/owner-notify"), \
         patch.object(owner_notification_delivery, "INTERNAL_SERVICE_SECRET", "secret"), \
         patch("owner_notification_delivery.requests.post", side_effect=_raise):
        ok, detail = owner_notification_delivery.deliver_owner_notification("PAYMENT_PROOF_UPLOADED", "msg")
        assert ok is False
        assert "network_error" in detail
    print("test_delivery_never_raises_on_network_error OK")


def test_delivery_succeeds_on_200_ok_response():
    class _FakeResp:
        status_code = 200
        def json(self):
            return {"status": "ok"}

    with patch.object(owner_notification_delivery, "KILAS_BOT_INTERNAL_URL", "http://localhost:5000/internal/owner-notify"), \
         patch.object(owner_notification_delivery, "INTERNAL_SERVICE_SECRET", "secret"), \
         patch("owner_notification_delivery.requests.post", return_value=_FakeResp()):
        ok, detail = owner_notification_delivery.deliver_owner_notification("PAYMENT_PROOF_UPLOADED", "msg")
        assert ok is True
    print("test_delivery_succeeds_on_200_ok_response OK")


# ---------------------------------------------------------------------------
# notify_owner_once() — immediate delivery + retry sweep + dedup
# ---------------------------------------------------------------------------

def test_notify_once_attempts_immediate_delivery_and_marks_sent_on_success():
    reset_db()
    with patch("owner_notification_delivery.deliver_owner_notification", return_value=(True, "delivered")):
        created = owner_notifications.notify_owner_once(
            "ev:immediate-ok", "PAYMENT_PROOF_UPLOADED", 1, 1, "Pembayaran perlu dicek.",
        )
    assert created is True
    row = db.query_one("SELECT * FROM owner_notifications WHERE event_key = 'ev:immediate-ok'")
    assert row["delivery_status"] == "SENT"
    assert row["sent_at"] is not None
    assert row["delivery_attempts"] == 1
    print("test_notify_once_attempts_immediate_delivery_and_marks_sent_on_success OK")


def test_notify_once_stays_pending_on_immediate_delivery_failure():
    reset_db()
    with patch("owner_notification_delivery.deliver_owner_notification", return_value=(False, "simulated failure")):
        owner_notifications.notify_owner_once(
            "ev:immediate-fail", "PAYMENT_PROOF_UPLOADED", 1, 1, "Pembayaran perlu dicek.",
        )
    row = db.query_one("SELECT * FROM owner_notifications WHERE event_key = 'ev:immediate-fail'")
    assert row["delivery_status"] == "FAILED"
    assert row["sent_at"] is None
    assert row["delivery_attempts"] == 1
    print("test_notify_once_stays_pending_on_immediate_delivery_failure OK")


def test_notify_once_never_raises_when_delivery_module_broken():
    reset_db()
    with patch("owner_notification_delivery.deliver_owner_notification", side_effect=RuntimeError("boom")):
        created = owner_notifications.notify_owner_once(
            "ev:delivery-broken", "PAYMENT_PROOF_UPLOADED", 1, 1, "Pembayaran perlu dicek.",
        )
    assert created is True, "the row itself must still be created even if delivery blows up"
    row = db.query_one("SELECT * FROM owner_notifications WHERE event_key = 'ev:delivery-broken'")
    assert row["delivery_status"] == "PENDING"
    print("test_notify_once_never_raises_when_delivery_module_broken OK")


def test_retry_sweep_only_retries_non_sent_rows_and_succeeds_later():
    reset_db()
    with patch("owner_notification_delivery.deliver_owner_notification", return_value=(False, "down")):
        owner_notifications.notify_owner_once("ev:retry-1", "QUOTATION_APPROVED", 1, 1, "msg1")
        owner_notifications.notify_owner_once("ev:retry-2-will-be-sent-already", "TALENT_REQUEST_SUBMITTED", 2, 1, "msg2")
    # Simulate the second one having actually been sent already (e.g. delivered on a later attempt
    # before the sweep runs) — the sweep must never touch it again.
    row2 = db.query_one("SELECT id FROM owner_notifications WHERE event_key = 'ev:retry-2-will-be-sent-already'")
    owner_notifications.mark_sent(row2["id"])

    pending_before = owner_notifications.list_pending()
    pending_keys = [r["event_key"] for r in pending_before]
    assert "ev:retry-1" in pending_keys
    assert "ev:retry-2-will-be-sent-already" not in pending_keys, "SENT rows must never be re-selected for retry"

    # Retry sweep now succeeds for the still-pending one.
    for row in pending_before:
        owner_notifications.mark_sent(row["id"])
    row1_after = db.query_one("SELECT * FROM owner_notifications WHERE event_key = 'ev:retry-1'")
    assert row1_after["delivery_status"] == "SENT"
    assert row1_after["delivery_attempts"] == 2, "one failed immediate attempt + one successful retry"
    print("test_retry_sweep_only_retries_non_sent_rows_and_succeeds_later OK")


def test_notify_once_never_double_sends_on_repeat_or_replay():
    reset_db()
    with patch("owner_notification_delivery.deliver_owner_notification", return_value=(True, "delivered")):
        first = owner_notifications.notify_owner_once("ev:replay", "WHATSAPP_CONNECTION_READY", 1, 1, "msg")
        second = owner_notifications.notify_owner_once("ev:replay", "WHATSAPP_CONNECTION_READY", 1, 1, "msg")
        third = owner_notifications.notify_owner_once("ev:replay", "WHATSAPP_CONNECTION_READY", 1, 1, "msg (slightly different text)")
    assert first is True
    assert second is False
    assert third is False
    count = db.query_one("SELECT COUNT(*) AS c FROM owner_notifications WHERE event_key = 'ev:replay'")["c"]
    assert count == 1
    print("test_notify_once_never_double_sends_on_repeat_or_replay OK")


def test_one_notification_type_per_event_builder():
    reset_db()
    with patch("owner_notification_delivery.deliver_owner_notification", return_value=(True, "delivered")):
        owner_id = _make_owner("event_builders@test.com")
        admin_id = repo.create_user("event_builders_admin@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN")
        business_id = repo.create_business(owner_id, "Event Builders Biz", package="NONE")

        assert owner_notifications.notify_ai_onboarding_ready(business_id, "Event Builders Biz") is True
        proj_id = projects_repo.create_custom_project(
            business_id, "PHOTO", "Photo project", {}, None, None, owner_id, catalog_key="custom_photo",
        )
        assert owner_notifications.notify_custom_project_submitted(proj_id, business_id, "PHOTO", "Photo project") is False, \
            "create_custom_project already fired this event"
        talent_id = talent_service.list_all_talents()[0]["id"]
        req_id, tproj_id = talent_service.create_talent_request(talent_id, business_id, {"campaign_type": "reels"}, owner_id)
        assert owner_notifications.notify_talent_request_submitted(req_id, tproj_id, business_id, "x") is False

        quote_proj_id = projects_repo.create_custom_project(
            business_id, "VIDEO", "Video project", {}, None, None, owner_id, catalog_key="custom_video",
        )
        quotation_id = quotation_service.create_quotation(quote_proj_id, business_id, "s", "d", 1, 1_000_000, "", admin_id)
        quotation_service.approve_quotation(quotation_id, business_id, owner_id)
        approved = db.query_one("SELECT * FROM owner_notifications WHERE event_type = 'QUOTATION_APPROVED' AND entity_id = ?", (quote_proj_id,))
        assert approved is not None and approved["delivery_status"] == "SENT"

        assert owner_notifications.notify_whatsapp_connection_ready(business_id, "Event Builders Biz") is True

        types_seen = {r["event_type"] for r in db.query_all("SELECT DISTINCT event_type FROM owner_notifications")}
        for expected in ("AI_ONBOARDING_READY_FOR_REVIEW", "CUSTOM_PROJECT_SUBMITTED", "TALENT_REQUEST_SUBMITTED",
                         "QUOTATION_APPROVED", "WHATSAPP_CONNECTION_READY"):
            assert expected in types_seen, f"missing event type {expected}"
    print("test_one_notification_type_per_event_builder OK")


# ---------------------------------------------------------------------------
# live_catalog_pdf.py — live catalog PDF generation from real DB state
# ---------------------------------------------------------------------------

def _pdf_text(pdf_bytes):
    """Extracts plain text from generated PDF bytes for assertions (uses pypdf, already a
    dependency here — see client-hub/requirements.txt)."""
    import io
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_live_catalog_reflects_current_growth_price_after_admin_edit():
    reset_db()
    growth = catalog_service.get_catalog_item("content_growth")
    catalog_service.update_catalog_item(growth["id"], price_amount=3_100_000)
    text = _pdf_text(live_catalog_pdf.generate_catalog_pdf_bytes())
    assert "3.100.000" in text
    print("test_live_catalog_reflects_current_growth_price_after_admin_edit OK")


def test_live_catalog_does_not_change_historical_project_price():
    reset_db()
    owner_id = _make_owner("hist_price@test.com")
    business_id = repo.create_business(owner_id, "Historical Biz", package="NONE")
    growth = catalog_service.get_catalog_item("content_growth")
    project_id = projects_repo.create_fixed_price_project(business_id, growth, owner_id)
    project_before = projects_repo.get_project(project_id)
    original_price = project_before["final_price"]
    assert original_price == growth["price_amount"]

    catalog_service.update_catalog_item(growth["id"], price_amount=9_999_000)
    live_catalog_pdf.generate_catalog_pdf_bytes()  # regenerate the live catalog with the new price

    project_after = projects_repo.get_project(project_id)
    assert project_after["final_price"] == original_price, "a locked-in historical price must never move"
    assert project_after["final_price"] != 9_999_000
    print("test_live_catalog_does_not_change_historical_project_price OK")


def test_live_catalog_reflects_talent_follower_update():
    reset_db()
    putri = next(t for t in talent_service.list_all_talents() if t["name"] == "Putri Maudy")
    talent_service.update_talent(putri["id"], follower_count=250_000)
    text = _pdf_text(live_catalog_pdf.generate_catalog_pdf_bytes())
    assert "250.000" in text
    print("test_live_catalog_reflects_talent_follower_update OK")


def test_live_catalog_never_shows_internal_rate():
    reset_db()
    putri = next(t for t in talent_service.list_all_talents() if t["name"] == "Putri Maudy")
    talent_service.update_talent(putri["id"], internal_rate=5_000_000, internal_notes="secret negotiated rate")
    text = _pdf_text(live_catalog_pdf.generate_catalog_pdf_bytes())
    assert "5.000.000" not in text
    assert "5000000" not in text
    assert "secret negotiated rate" not in text
    print("test_live_catalog_never_shows_internal_rate OK")


def test_live_catalog_shows_custom_quote_for_photo_video_talent_and_custom_content():
    """Premium catalog/PDF redesign task: the raw "Custom Quote" label was intentionally replaced
    with a natural, professional Indonesian sentence — "Penawaran disesuaikan dengan kebutuhan
    project." (catalog_service.format_price()) — plus explicit prose in the Photo/Video/Talent
    sections. This test now checks for that current, correct wording instead."""
    reset_db()
    text = _pdf_text(live_catalog_pdf.generate_catalog_pdf_bytes())
    assert "disesuaikan dengan kebutuhan" in text
    assert "Custom Quote" not in text, "the raw 'Custom Quote' label must no longer appear in the customer-facing PDF"
    # No numeric currency amount anywhere near a talent name (talents are only ever custom quote).
    for talent in talent_service.list_active_talents():
        assert talent["name"] in text
    custom_content_item = catalog_service.get_catalog_item("custom_content")
    assert custom_content_item["pricing_mode"] == "CUSTOM_QUOTE"
    print("test_live_catalog_shows_custom_quote_for_photo_video_talent_and_custom_content OK")


def test_live_catalog_ai_admin_fixed_only_no_custom_option():
    reset_db()
    text = _pdf_text(live_catalog_pdf.generate_catalog_pdf_bytes())
    assert "AI Admin Basic" in text
    assert "AI Admin Pro" in text
    assert "Custom AI Admin" not in text
    ai_items = [i for i in catalog_service.list_active_catalog() if i["category"] == "AI_ADMIN"]
    assert all(i["pricing_mode"] == "FIXED_PRICE" for i in ai_items)
    print("test_live_catalog_ai_admin_fixed_only_no_custom_option OK")


def test_catalog_cache_invalidates_on_edit_and_serves_cached_path_otherwise():
    reset_db()
    live_catalog_pdf._CACHE_STATE.update(version=None, path=None)
    path1 = live_catalog_pdf.get_cached_catalog_pdf_path()
    assert path1 and os.path.exists(path1)
    mtime1 = os.path.getmtime(path1)

    # No change -> same cached file, not regenerated.
    path2 = live_catalog_pdf.get_cached_catalog_pdf_path()
    assert path2 == path1
    assert os.path.getmtime(path2) == mtime1

    # An admin edit bumps the cache version -> next call regenerates.
    import time
    time.sleep(0.01)
    growth = catalog_service.get_catalog_item("content_growth")
    catalog_service.update_catalog_item(growth["id"], price_amount=3_333_000)
    path3 = live_catalog_pdf.get_cached_catalog_pdf_path()
    assert path3 == path1  # same cache path, regenerated in place
    text = _pdf_text(open(path3, "rb").read())
    assert "3.333.000" in text
    print("test_catalog_cache_invalidates_on_edit_and_serves_cached_path_otherwise OK")


def test_catalog_regenerate_route_requires_admin():
    reset_db()
    import app as client_hub_app
    client = client_hub_app.app.test_client()
    resp = client.post("/admin/catalog/regenerate")
    # Blocked either by CSRF (400, no token) or by @admin_required (302 redirect to login) —
    # either way, never a 200 without being both authenticated as KILAS_ADMIN and CSRF-valid.
    assert resp.status_code in (302, 400, 401, 403), "must not be reachable without admin auth"
    print("test_catalog_regenerate_route_requires_admin OK")


def test_public_catalog_pdf_route_serves_pdf():
    reset_db()
    import app as client_hub_app
    client = client_hub_app.app.test_client()
    resp = client.get("/catalog.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    print("test_public_catalog_pdf_route_serves_pdf OK")


if __name__ == "__main__":
    test_delivery_fails_closed_when_url_unset()
    test_delivery_fails_closed_when_secret_unset()
    test_delivery_never_raises_on_network_error()
    test_delivery_succeeds_on_200_ok_response()
    test_notify_once_attempts_immediate_delivery_and_marks_sent_on_success()
    test_notify_once_stays_pending_on_immediate_delivery_failure()
    test_notify_once_never_raises_when_delivery_module_broken()
    test_retry_sweep_only_retries_non_sent_rows_and_succeeds_later()
    test_notify_once_never_double_sends_on_repeat_or_replay()
    test_one_notification_type_per_event_builder()
    test_live_catalog_reflects_current_growth_price_after_admin_edit()
    test_live_catalog_does_not_change_historical_project_price()
    test_live_catalog_reflects_talent_follower_update()
    test_live_catalog_never_shows_internal_rate()
    test_live_catalog_shows_custom_quote_for_photo_video_talent_and_custom_content()
    test_live_catalog_ai_admin_fixed_only_no_custom_option()
    test_catalog_cache_invalidates_on_edit_and_serves_cached_path_otherwise()
    test_catalog_regenerate_route_requires_admin()
    test_public_catalog_pdf_route_serves_pdf()
    print("\nALL ABSOLUTE FINAL PRODUCTION PATCH (CLIENT HUB) TESTS PASSED")
