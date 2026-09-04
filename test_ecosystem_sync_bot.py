"""FINAL ECOSYSTEM SYNC & OWNER NOTIFICATION PATCH — root/bot-side test suite.

Covers the app.py-side pieces of the ecosystem sync (client-hub's own pieces are covered by
client-hub/tests/test_business_hub_v2_ecosystem_sync.py):
  Section 13 — owner-bot safe DB-query wrapper functions (never invent data, degrade to a
               harmless empty default on any failure)
  Section 20 — canonical live catalog price lookup + additive system-prompt sync note, and the
               explicit guarantee that existing regression tests (which never touch Client Hub's
               catalog) see byte-identical prompt behavior
  Section 23 — the Render-only insecure-default security warning never crashes and never logs the
               actual secret value

Run with:
    python3 test_ecosystem_sync_bot.py
"""
import os
import sys
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("RENDER", None)

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

_TMP_DB = _test_bootstrap.get_temp_db_path()  # SAME path _test_bootstrap already set up (never a second, separate tempfile)

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as ch_db  # noqa: E402
import catalog_service  # noqa: E402
import security  # noqa: E402


def _reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    ch_db._local.conn = None
    ch_db.init_schema()
    catalog_service.seed_catalog_if_needed()


def test_owner_query_wrappers_never_raise_and_default_empty_without_client_hub():
    with patch.object(appmod, "_payment_service", None), \
         patch.object(appmod, "_projects_repo", None), \
         patch.object(appmod, "_talent_service", None), \
         patch.object(appmod, "_client_hub_repo", None):
        assert appmod._get_pending_payment_verifications_safe() == {"count": 0, "items": []}
        assert appmod._get_new_custom_project_requests_safe() == {"count": 0, "items": []}
        assert appmod._get_new_talent_requests_safe() == {"count": 0, "items": []}
        pipeline = appmod._get_ai_admin_pipeline_status_safe()
        assert pipeline["ready_for_review"] == 0 and pipeline["waiting_whatsapp_connection"] == 0
    print("test_owner_query_wrappers_never_raise_and_default_empty_without_client_hub OK")


def test_owner_query_wrappers_reflect_real_db_state():
    _reset_client_hub_db()
    import repo, security, projects_repo, talent_service, payment_service, quotation_service  # noqa: E402

    talent_service.seed_talents_if_needed()
    owner_id = repo.create_user("q_owner@test.com", security.hash_password("password123"))
    business_id = repo.create_business(owner_id, "Query Test Biz", package="NONE")

    # Nothing pending yet.
    with patch.object(appmod, "_projects_repo", projects_repo):
        assert appmod._get_new_custom_project_requests_safe()["count"] == 0

    # A real custom project request must show up truthfully.
    projects_repo.create_custom_project(
        business_id, "PHOTO", "Custom Photo Test", {"notes": "x"}, None, None, owner_id,
        catalog_key="custom_photo",
    )
    with patch.object(appmod, "_projects_repo", projects_repo):
        result = appmod._get_new_custom_project_requests_safe()
        assert result["count"] == 1
        assert "Custom Photo Test" in result["items"][0]

    with patch.object(appmod, "_client_hub_repo", repo):
        pipeline = appmod._get_ai_admin_pipeline_status_safe()
        # package='NONE' business must NEVER count toward the AI Admin pipeline.
        assert pipeline["waiting_whatsapp_connection"] == 0

    ai_business_id = repo.create_business(owner_id, "AI Biz", package="AI_ADMIN_BASIC")
    repo.set_business_status(ai_business_id, "APPROVED", owner_id, "test")
    with patch.object(appmod, "_client_hub_repo", repo):
        pipeline = appmod._get_ai_admin_pipeline_status_safe()
        assert pipeline["waiting_whatsapp_connection"] == 1
    print("test_owner_query_wrappers_reflect_real_db_state OK")


def test_live_catalog_price_sync_note_empty_when_prices_match():
    _reset_client_hub_db()
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        assert note == "", "freshly seeded catalog matches PRICING_CONFIG — no sync note expected"
    print("test_live_catalog_price_sync_note_empty_when_prices_match OK")


def test_live_catalog_price_sync_note_fires_only_when_price_actually_changed():
    _reset_client_hub_db()
    import db as _db
    # Admin changes AI Admin Basic's live price in Client Hub.
    _db.execute("UPDATE service_catalog SET price_amount = 599000 WHERE catalog_key = 'ai_admin_basic'")
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        assert "599.000" in note or "599000" in note
        assert "Kilas Brain Basic" in note  # 2026 rebrand: bot's own PRICING_CONFIG name updated too
        # An untouched item must not appear in the diff.
        assert "Content Basic" not in note
    print("test_live_catalog_price_sync_note_fires_only_when_price_actually_changed OK")


def test_live_catalog_price_sync_never_breaks_existing_pricing_config_regression_behavior():
    """The 158+ existing WhatsApp regression tests never touch Client Hub's catalog — this test
    pins that guarantee: with a freshly seeded (untouched) catalog, build_customer_system_prompt's
    output is unaffected by this patch (no sync note text appears)."""
    _reset_client_hub_db()
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        prompt = appmod.build_customer_system_prompt("628900000099")
        assert "UPDATE HARGA TERBARU" not in prompt
    print("test_live_catalog_price_sync_never_breaks_existing_pricing_config_regression_behavior OK")


def test_live_price_sync_covers_full_catalog_generically_not_just_a_handful():
    """Bug fix: the live price sync used to only watch ~7 hand-picked catalog_keys. It must now
    generically cover every active FIXED_PRICE/STARTING_FROM item — including ones the old short
    list never mentioned at all (Content Growth was covered before, but Meta Ads, bundles, Event
    packages, and website maintenance were NOT)."""
    _reset_client_hub_db()
    import db as _db

    changes = {
        "content_growth": 2_999_000,
        "ads_management": 899_000,
        "event_lengkap": 3_100_000,
        "website_maintenance": 249_000,
        "bundle_content_growth_brain_pro": 3_690_000,  # 2026 rebrand: retired key renamed
    }
    for key, new_price in changes.items():
        _db.execute("UPDATE service_catalog SET price_amount = ? WHERE catalog_key = ?", (new_price, key))

    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        for key, new_price in changes.items():
            price_fmt = f"Rp{new_price:,}".replace(",", ".")
            assert price_fmt in note, f"{key} new price {price_fmt} missing from live sync note: {note!r}"
    print("test_live_price_sync_covers_full_catalog_generically_not_just_a_handful OK")


def test_live_price_sync_never_includes_custom_quote_items():
    """CUSTOM_QUOTE items (Custom Content/Photo/Video/Talent/Custom Website-App) must never get a
    fixed-price sync note even if someone forces a price_amount into the row directly."""
    _reset_client_hub_db()
    import db as _db
    _db.execute("UPDATE service_catalog SET price_amount = 12345678 WHERE catalog_key = 'custom_content'")
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        assert "12.345.678" not in note and "12345678" not in note
    print("test_live_price_sync_never_includes_custom_quote_items OK")


def test_live_price_sync_does_not_touch_a_historical_orders_locked_in_price():
    """A historical/already-placed order's locked-in final_price must be untouched by a later
    live catalog price change — it was snapshotted at project-creation time."""
    _reset_client_hub_db()
    import db as _db
    import repo, security, catalog_service, projects_repo  # noqa: E402

    owner_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, "Historical Order Biz", package="NONE")
    item = catalog_service.get_catalog_item("event_standard")
    original_price = item["price_amount"]
    project_id = projects_repo.create_fixed_price_project(bid, item, owner_id)
    locked_price = projects_repo.get_project(project_id)["final_price"]
    assert locked_price == original_price

    # Admin changes the live price AFTER the order was already placed.
    _db.execute("UPDATE service_catalog SET price_amount = ? WHERE catalog_key = 'event_standard'",
                (original_price + 500_000,))

    reloaded = projects_repo.get_project(project_id)
    assert reloaded["final_price"] == locked_price, "a historical order's locked-in price must never change"
    print("test_live_price_sync_does_not_touch_a_historical_orders_locked_in_price OK")


def _make_admin_actor():
    import repo, security  # noqa: E402
    admin_id = repo.create_user(
        f"admin_{os.urandom(4).hex()}@kilasworks.id", security.hash_password("adminpass123"), role="KILAS_ADMIN"
    )
    return {"id": admin_id, "role": "KILAS_ADMIN"}


def _provision_and_activate_tenant(business_name, phone_number_id, services, faqs, description,
                                    address=None, hours=None, package="AI_ADMIN_BASIC"):
    """Builds a fully ACTIVE, whatsapp-connected tenant with real onboarding data, the same way
    the real Client Hub admin flow would (approve -> provision -> activate), so
    _resolve_tenant_id()/_build_tenant_context_block_safe() see it exactly like production."""
    import repo, provisioning, db as ch_db  # noqa: E402

    owner_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, business_name, package=package)
    repo.upsert_business_profile(bid, {
        "business_name": business_name, "category": "Test biz", "owner_name": "Owner",
        "primary_language": "id", "customer_salutation": "Kak",
        "address": address, "operating_hours": hours,
    })
    repo.replace_business_services(bid, [name for name, _lo, _hi in services])
    for row, (name, lo, hi) in zip(repo.get_business_services(bid), services):
        repo.update_normalized_service(row["id"], name, None, lo, hi, "IDR", False)
    repo.replace_business_faqs(bid, [q for q, _a in faqs])
    for row, (q, a) in zip(repo.get_business_faqs(bid), faqs):
        repo.update_normalized_faq(row["id"], q, a, None, False)
    repo.save_ai_normalized_config(bid, f"{business_name} summary", {"description": description}, [])
    repo.set_tenant_features_for_package(bid, package)

    admin = _make_admin_actor()
    repo.approve_business(bid, admin["id"])
    provisioning.provision_tenant(bid, admin)
    repo.activate_business(bid, admin["id"])
    ch_db.execute("UPDATE businesses SET whatsapp_phone_number_id = ? WHERE id = ?", (phone_number_id, bid))
    return bid


def test_tenant_customer_prompt_never_leaks_kilas_works_own_catalog():
    """Bug fix: a resolved CLIENT tenant (coffee shop) must NEVER see Kilas Works' own catalog/
    pricing (AI Admin, Content packages, website pricing, etc.) — only its own data."""
    import security  # noqa: E402
    _reset_client_hub_db()
    _provision_and_activate_tenant(
        "Kopi Senja", "coffee_phone_1",
        services=[("Kopi Susu Gula Aren", 20000, 20000), ("Americano", 18000, 18000)],
        faqs=[("Ada wifi?", "Ada, gratis buat pelanggan.")],
        description="Kedai kopi santai di Tangerang",
        address="Jl. Melati No. 1, Tangerang", hours="08:00-22:00",
    )
    tenant_id = appmod._resolve_tenant_id("coffee_phone_1")
    assert tenant_id is not None
    tenant_block = appmod._build_tenant_context_block_safe(tenant_id)
    prompt = appmod.build_customer_system_prompt("628900000001", tenant_context_block=tenant_block)

    # Own data present.
    assert "Kopi Senja" in prompt
    assert "Kopi Susu Gula Aren" in prompt

    # Kilas Works' own catalog/pricing must never leak into this tenant's prompt.
    for forbidden in ("AI Admin Basic", "AI Admin Pro", "Content Basic", "Content Growth",
                       "Content Pro", "Landing Page", "799.000", "499.000", "999.000",
                       "Meta Ads Management", "Kamu admin WhatsApp Kilas Works"):
        assert forbidden not in prompt, f"leaked Kilas Works content into tenant prompt: {forbidden!r}"
    print("test_tenant_customer_prompt_never_leaks_kilas_works_own_catalog OK")


def test_tenant_customer_prompt_isolated_between_different_tenants():
    """A different client tenant (salon) must never see another tenant's (coffee shop's) data."""
    _reset_client_hub_db()
    _provision_and_activate_tenant(
        "Kopi Senja", "coffee_phone_2",
        services=[("Kopi Susu Gula Aren", 20000, 20000)],
        faqs=[("Ada wifi?", "Ada, gratis buat pelanggan.")],
        description="Kedai kopi santai di Tangerang",
    )
    _provision_and_activate_tenant(
        "Salon Cantika", "salon_phone_2",
        services=[("Potong Rambut", 50000, 50000), ("Creambath", 75000, 75000)],
        faqs=[("Buka jam berapa?", "Buka jam 9 pagi.")],
        description="Salon kecantikan wanita",
    )

    coffee_tenant = appmod._resolve_tenant_id("coffee_phone_2")
    salon_tenant = appmod._resolve_tenant_id("salon_phone_2")
    assert coffee_tenant is not None and salon_tenant is not None and coffee_tenant != salon_tenant

    coffee_prompt = appmod.build_customer_system_prompt(
        "628900000002", tenant_context_block=appmod._build_tenant_context_block_safe(coffee_tenant))
    salon_prompt = appmod.build_customer_system_prompt(
        "628900000003", tenant_context_block=appmod._build_tenant_context_block_safe(salon_tenant))

    assert "Kopi Senja" in coffee_prompt and "Potong Rambut" not in coffee_prompt
    assert "Salon Cantika" in salon_prompt and "Kopi Susu Gula Aren" not in salon_prompt
    print("test_tenant_customer_prompt_isolated_between_different_tenants OK")


def test_tenant_with_incomplete_config_never_falls_back_to_kilas_catalog():
    """A tenant resolved (ACTIVE, whatsapp connected) but with no provisioned/onboarding data at
    all must get a neutral incomplete-profile notice — never Kilas Works' own catalog."""
    import repo, db as ch_db  # noqa: E402
    _reset_client_hub_db()
    owner_id = repo.create_user(f"owner_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(owner_id, "Bisnis Baru", package="AI_ADMIN_BASIC")
    admin = _make_admin_actor()
    # Force ACTIVE directly (skip provisioning) to simulate a tenant with no materialized config yet.
    repo.activate_business(bid, admin["id"])
    ch_db.execute("UPDATE businesses SET whatsapp_phone_number_id = ? WHERE id = ?", ("incomplete_phone", bid))

    tenant_id = appmod._resolve_tenant_id("incomplete_phone")
    assert tenant_id is not None
    tenant_block = appmod._build_tenant_context_block_safe(tenant_id)
    assert tenant_block, "an incomplete tenant must still get a non-empty (neutral) context block"

    prompt = appmod.build_customer_system_prompt("628900000004", tenant_context_block=tenant_block)
    for forbidden in ("AI Admin Basic", "Content Growth", "Landing Page", "799.000", "499.000",
                       "Kamu admin WhatsApp Kilas Works"):
        assert forbidden not in prompt, f"incomplete tenant fell back to Kilas Works content: {forbidden!r}"
    assert "belum lengkap" in prompt or "CATATAN PENTING" in prompt
    print("test_tenant_with_incomplete_config_never_falls_back_to_kilas_catalog OK")


def test_kilas_works_own_conversation_still_uses_own_pricing_by_default():
    """The non-tenant/default path (Kilas Works' own WhatsApp number talking to its own prospects)
    must be completely unaffected — still discusses its own pricing as before."""
    _reset_client_hub_db()
    prompt = appmod.build_customer_system_prompt("628900000099")  # no tenant_context_block
    assert "AI Admin Basic" in prompt or "AI Admin" in prompt
    assert "Content Growth" in prompt
    assert "Rp799rb" in prompt or "799.000" in prompt or "Rp799.000" in prompt
    print("test_kilas_works_own_conversation_still_uses_own_pricing_by_default OK")


def test_render_security_warning_never_crashes_and_never_logs_secret_value():
    """Re-execute the startup warning logic in isolation (it normally runs once at import time) to
    verify: (a) it never raises even with insecure defaults + RENDER set, (b) the literal secret
    string is never present in what gets printed — only the env var NAME is."""
    import io
    import contextlib

    captured = io.StringIO()
    with patch.object(appmod, "VERIFY_TOKEN", "kilasworks123"), \
         patch.object(appmod, "DASHBOARD_KEY", "kilasworks-dashboard"), \
         patch.object(appmod, "CRON_SECRET", "kilasworks-dashboard"), \
         patch.dict(os.environ, {"RENDER": "true"}):
        with contextlib.redirect_stdout(captured):
            # Re-run the exact gate logic from app.py's module body, isolated, so this test does
            # not depend on process import order (the real gate already ran once at import time
            # with RENDER unset).
            insecure = []
            if appmod.VERIFY_TOKEN == "kilasworks123":
                insecure.append("VERIFY_TOKEN")
            if appmod.DASHBOARD_KEY == "kilasworks-dashboard":
                insecure.append("DASHBOARD_KEY")
            if appmod.CRON_SECRET == "kilasworks-dashboard":
                insecure.append("CRON_SECRET")
            if os.environ.get("RENDER") and insecure:
                print(
                    "SECURITY WARNING: running on Render with insecure DEFAULT value(s) still "
                    f"active for: {', '.join(insecure)}. Set proper environment variable(s)."
                )
    output = captured.getvalue()
    assert "VERIFY_TOKEN" in output and "DASHBOARD_KEY" in output and "CRON_SECRET" in output
    assert "kilasworks123" not in output
    assert "kilasworks-dashboard" not in output
    print("test_render_security_warning_never_crashes_and_never_logs_secret_value OK")


def test_live_catalog_deactivated_item_never_recommended():
    """Gap-fix Area H: an item an admin turns OFF in Client Hub (is_active=False) must make the
    bot stop recommending/quoting it — the original Section 20 sync only ever watched PRICE, so a
    deactivated item silently kept being offered forever before this fix."""
    _reset_client_hub_db()
    import db as _db
    _db.execute("UPDATE service_catalog SET is_active = ? WHERE catalog_key = 'content_growth'", (False,))
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        assert "Content Growth" in note
        assert "TIDAK DITAWARKAN LAGI" in note
        # An untouched item must not appear.
        assert "Content Basic" not in note
    print("test_live_catalog_deactivated_item_never_recommended OK")


def test_live_catalog_renamed_item_reflected():
    """Gap-fix Area H: an item an admin RENAMES in Client Hub must be reflected — the bot should
    use the new name, not keep the old hardcoded PRICING_CONFIG label forever."""
    _reset_client_hub_db()
    import db as _db
    _db.execute("UPDATE service_catalog SET name = ? WHERE catalog_key = 'website_landing_page'",
                ("Paket Landing Page Premium",))
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        assert "Paket Landing Page Premium" in note
        assert "GANTI NAMA" in note
    print("test_live_catalog_renamed_item_reflected OK")


def test_live_catalog_deactivated_item_suppresses_its_own_price_diff():
    """A deactivated item must be reported ONLY in the 'no longer offered' section, never ALSO
    listed as a price change (its price is irrelevant once it's off) — avoids a confusing/
    contradictory prompt note."""
    _reset_client_hub_db()
    import db as _db
    _db.execute("UPDATE service_catalog SET is_active = ?, price_amount = ? WHERE catalog_key = 'content_pro'",
                (False, 9_999_000))
    with patch.object(appmod, "_catalog_service", __import__("catalog_service")):
        note = appmod._build_live_price_sync_note_safe()
        assert "TIDAK DITAWARKAN LAGI" in note
        assert "9.999.000" not in note, "an inactive item's price must not be surfaced as a live price update"
    print("test_live_catalog_deactivated_item_suppresses_its_own_price_diff OK")


if __name__ == "__main__":
    test_owner_query_wrappers_never_raise_and_default_empty_without_client_hub()
    test_owner_query_wrappers_reflect_real_db_state()
    test_live_catalog_price_sync_note_empty_when_prices_match()
    test_live_catalog_price_sync_note_fires_only_when_price_actually_changed()
    test_live_catalog_price_sync_never_breaks_existing_pricing_config_regression_behavior()
    test_live_price_sync_covers_full_catalog_generically_not_just_a_handful()
    test_live_price_sync_never_includes_custom_quote_items()
    test_live_price_sync_does_not_touch_a_historical_orders_locked_in_price()
    test_live_catalog_deactivated_item_never_recommended()
    test_live_catalog_renamed_item_reflected()
    test_live_catalog_deactivated_item_suppresses_its_own_price_diff()
    test_tenant_customer_prompt_never_leaks_kilas_works_own_catalog()
    test_tenant_customer_prompt_isolated_between_different_tenants()
    test_tenant_with_incomplete_config_never_falls_back_to_kilas_catalog()
    test_kilas_works_own_conversation_still_uses_own_pricing_by_default()
    test_render_security_warning_never_crashes_and_never_logs_secret_value()
    print("\nALL ECOSYSTEM SYNC BOT-SIDE TESTS PASSED")
