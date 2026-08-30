"""Gap-fix Area D — normal client Submit auto-runs AI normalization; no manual 'Jalankan AI Setup'
click is required in the normal flow anymore. The manual button still exists and still works for
re-runs. Run with:
    cd client-hub && python3 tests/test_onboarding_auto_normalize.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the "no key configured" graceful-failure path
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()


def fresh_client():
    return FLASK_APP.test_client()


def _make_client_with_business(c, email, biz_name, package="AI_ADMIN_BASIC"):
    c.post("/register", data={"email": email, "password": "password123", "full_name": email})
    c.post("/business/create", data={"business_name": biz_name, "package": package})
    return db.query_one("SELECT id FROM businesses WHERE business_name = ?", (biz_name,))["id"]


def _run_full_wizard(c, bid, salutation="Kak"):
    c.post(f"/business/{bid}/wizard/basics", data={
        "business_name": "Kopi ABC", "category": "Kedai kopi", "short_description": "Kopi enak",
        "country": "Indonesia", "timezone": "Asia/Jakarta", "address": "Tangerang",
        "business_phone": "0812", "owner_name": "Budi",
    })
    c.post(f"/business/{bid}/wizard/services", data={"services_raw": "Kopi susu - 20rb\nEspresso - 18rb"})
    c.post(f"/business/{bid}/wizard/operations", data={
        "operating_hours": "08-20", "closed_days": "-", "online_or_offline": "offline",
        "appointment_rules_raw": "",
    })
    c.post(f"/business/{bid}/wizard/faq", data={"faq_raw": "Ada wifi? Ada, gratis."})
    c.post(f"/business/{bid}/wizard/style", data={
        "tone": "friendly", "primary_language": "id", "customer_salutation": salutation,
    })
    c.post(f"/business/{bid}/wizard/upload", data={})


# ---------------------------------------------------------------------------
# 1. Submit alone (no prior manual AI Setup click) triggers normalization automatically.
# ---------------------------------------------------------------------------
def test_submit_without_manual_ai_setup_auto_normalizes():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)

    ai_before = repo.get_ai_settings(bid)
    assert ai_before["ai_status"] == "PENDING", "sanity: AI Setup must NOT have run yet"

    c.post(f"/business/{bid}/submit-for-review", follow_redirects=True)

    ai_after = repo.get_ai_settings(bid)
    # No ANTHROPIC_API_KEY in this sandbox -> normalization fails gracefully, but the KEY POINT
    # is that it was ATTEMPTED automatically by Submit alone — status is no longer the untouched
    # "PENDING" it started at (it becomes FAILED here; in production with a real API key it would
    # become DONE — either way, no manual click was required to trigger the attempt).
    assert ai_after["ai_status"] in ("DONE", "FAILED"), ai_after
    assert ai_after["ai_status"] != "PENDING", "Submit must actually attempt normalization automatically"
    print("test_submit_without_manual_ai_setup_auto_normalizes OK")


# ---------------------------------------------------------------------------
# 2. Submit still blocks (never normalizes/submits) when required wizard steps are incomplete.
# ---------------------------------------------------------------------------
def test_submit_blocks_when_wizard_incomplete():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    c.post(f"/business/{bid}/wizard/basics", data={"business_name": "Kopi ABC", "owner_name": "Budi"})

    resp = c.post(f"/business/{bid}/submit-for-review", follow_redirects=True)
    assert resp.status_code == 200
    ai = repo.get_ai_settings(bid)
    assert ai["ai_status"] == "PENDING", "normalization must never run on an incomplete wizard"
    business = repo.get_business(bid)
    assert business["status"] not in ("READY_FOR_REVIEW",), business["status"]
    print("test_submit_blocks_when_wizard_incomplete OK")


# ---------------------------------------------------------------------------
# 3. Normalization failure during Submit preserves raw data and allows retry — never invents facts.
# ---------------------------------------------------------------------------
def test_submit_normalization_failure_preserves_raw_data_and_allows_retry():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)

    c.post(f"/business/{bid}/submit-for-review", follow_redirects=True)
    ai = repo.get_ai_settings(bid)
    assert ai["ai_status"] == "FAILED"
    assert ai["last_error"] == "ANTHROPIC_API_KEY_NOT_CONFIGURED"

    services = repo.get_business_services(bid)
    assert [s["raw_input"] for s in services] == ["Kopi susu - 20rb", "Espresso - 18rb"], \
        "raw client data must survive a Submit-triggered normalization failure untouched"
    faqs = repo.get_business_faqs(bid)
    assert len(faqs) == 1 and faqs[0]["raw_input"] == "Ada wifi? Ada, gratis."

    business = repo.get_business(bid)
    assert business["status"] != "READY_FOR_REVIEW", \
        "a FAILED normalization must never let the business slip through to READY_FOR_REVIEW"

    # Retry: clicking Submit again must be safe (not crash, not duplicate/corrupt data).
    c.post(f"/business/{bid}/submit-for-review", follow_redirects=True)
    services_after_retry = repo.get_business_services(bid)
    assert [s["raw_input"] for s in services_after_retry] == ["Kopi susu - 20rb", "Espresso - 18rb"]
    print("test_submit_normalization_failure_preserves_raw_data_and_allows_retry OK")


# ---------------------------------------------------------------------------
# 4. Manual "Jalankan AI Setup" button still works (backward compatible, not removed).
# ---------------------------------------------------------------------------
def test_manual_ai_setup_button_still_works_for_rerun():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    resp = c.post(f"/business/{bid}/ai-setup/run", follow_redirects=True)
    assert resp.status_code == 200
    ai = repo.get_ai_settings(bid)
    assert ai["ai_status"] == "FAILED"  # no API key in sandbox, but the ROUTE itself still works
    print("test_manual_ai_setup_button_still_works_for_rerun OK")


# ---------------------------------------------------------------------------
# 5. Submit does NOT re-run normalization if it already succeeded (idempotent — avoids wasted
#    API calls / avoids clobbering an admin's manual edits made after a successful run).
# ---------------------------------------------------------------------------
def test_submit_does_not_renormalize_if_already_done():
    reset_db()
    c = fresh_client()
    bid = _make_client_with_business(c, "owner1@test.com", "Kopi ABC")
    _run_full_wizard(c, bid)
    # Simulate a prior successful AI Setup run (as other tests in this codebase already do, to
    # avoid needing a live Claude API call in the sandbox).
    repo.save_ai_normalized_config(bid, "summary", {"description": "x"}, [])
    before = repo.get_ai_settings(bid)
    assert before["ai_status"] == "DONE"

    resp = c.post(f"/business/{bid}/submit-for-review", follow_redirects=True)
    assert resp.status_code == 200
    business = repo.get_business(bid)
    assert business["status"] == "READY_FOR_REVIEW"
    after = repo.get_ai_settings(bid)
    assert after["ai_status"] == "DONE"
    assert after["normalized_config"] == before["normalized_config"], \
        "Submit must not silently re-run/overwrite an already-successful normalized config"
    print("test_submit_does_not_renormalize_if_already_done OK")


if __name__ == "__main__":
    test_submit_without_manual_ai_setup_auto_normalizes()
    test_submit_blocks_when_wizard_incomplete()
    test_submit_normalization_failure_preserves_raw_data_and_allows_retry()
    test_manual_ai_setup_button_still_works_for_rerun()
    test_submit_does_not_renormalize_if_already_done()
    print("ALL ONBOARDING AUTO-NORMALIZE TESTS PASSED")
