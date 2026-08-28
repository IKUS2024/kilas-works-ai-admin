"""Kilas Works Client Hub — Business Hub V2, PHASES F, G, H test suite.

Covers the pure-logic "future bot integration" modules built for:
  Phase F — WhatsApp product/quotation/payment knowledge + owner-as-sales-coordinator workflow
            (wa_project_bridge.py: classify_owner_message, parse_owner_offers,
            build_customer_facing_offer_message, customer_price_response,
            customer_payment_response), plus tenant_config_service.get_active_service_catalog /
            get_open_projects_summary.
  Phase G — multi-tenant WhatsApp activation contract functions (already covered by
            test_production_foundation.py's tenant resolution tests; this file adds coverage for
            the NEW Phase F/H additions to tenant_config_service specifically).
  Phase H — human takeover (wa_takeover_service.py) + tenant_config_service.get_conversation_mode.

None of this is wired into the live production bot (../app.py) — see BOT_INTEGRATION_GUIDE.md's
Patch 4/5/6 for the deliberate, unapplied integration plan. This suite only proves the pure logic
itself is correct, tenant-safe, and never invents a price or leaks internal wording — so that when
a future patch does wire it in, the underlying logic is already known-good.

ADDITIVE — every earlier test file is untouched. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_phase_fgh.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import projects_repo  # noqa: E402
import quotation_service  # noqa: E402
import talent_service  # noqa: E402
import wa_takeover_service  # noqa: E402
import wa_project_bridge as bridge  # noqa: E402
import tenant_config_service  # noqa: E402


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()
    talent_service.seed_talents_if_needed()


def _make_owner_and_business(email="owner@test.com"):
    user_id = repo.create_user(email, security.hash_password("password123"))
    business_id = repo.create_business(user_id, "Test Biz", package="AI_ADMIN_BASIC")
    return user_id, business_id


# ---------------------------------------------------------------------------
# PHASE F — owner message classification
# ---------------------------------------------------------------------------

def test_owner_action_requires_explicit_send_verb():
    assert bridge.classify_owner_message("bilang ke customer 3 juta bisa 3 video") == "OWNER_ACTION"
    assert bridge.classify_owner_message("kirim penawaran ke Rina 2 juta") == "OWNER_ACTION"
    print("test_owner_action_requires_explicit_send_verb OK")


def test_owner_message_without_send_verb_is_never_action():
    # thinking out loud / a note to self must NEVER trigger an outbound customer message
    assert bridge.classify_owner_message("customer ini budgetnya kecil kayaknya") == "OWNER_INTERNAL_NOTE"
    assert bridge.classify_owner_message("project Rina gimana progressnya?") == "OWNER_QUERY"
    assert bridge.classify_owner_message("") == "OWNER_INTERNAL_NOTE"
    print("test_owner_message_without_send_verb_is_never_action OK")


def test_parse_owner_offers_extracts_quantity_and_price_pairs():
    text = "bilang ke customer 3 juta bisa 3 video, kalau 5 video 4,2 juta, shooting satu hari"
    offers, notes = bridge.parse_owner_offers(text)
    assert {"quantity": 3, "price": 3_000_000} == {"quantity": offers[0]["quantity"], "price": offers[0]["price"]}
    assert {"quantity": 5, "price": 4_200_000} == {"quantity": offers[1]["quantity"], "price": offers[1]["price"]}
    assert "shooting satu hari" in notes[0]
    print("test_parse_owner_offers_extracts_quantity_and_price_pairs OK")


def test_parse_owner_offers_never_infers_missing_price():
    offers, notes = bridge.parse_owner_offers("nanti aku follow up lagi soal ini")
    assert offers == []
    assert notes  # kept as a note, never turned into a fabricated offer
    print("test_parse_owner_offers_never_infers_missing_price OK")


def test_customer_facing_message_never_leaks_owner_raw_wording_or_markers():
    offers, notes = bridge.parse_owner_offers(
        "bilang ke customer 3 juta bisa 3 video, kalau 5 video 4,2 juta, shooting satu hari"
    )
    message = bridge.build_customer_facing_offer_message(offers, notes)
    assert "Rp3.000.000" in message
    assert "Rp4.200.000" in message
    assert "shooting satu hari" in message
    # explicit prohibition list from the spec — none of these internal markers ever appear
    for forbidden in ("ACTION", "STATE", "DEBUG", "JSON", "PESAN_UNTUK_CUSTOMER", "bilang ke customer"):
        assert forbidden not in message
    print("test_customer_facing_message_never_leaks_owner_raw_wording_or_markers OK")


def test_customer_price_response_fixed_vs_custom_quote():
    reset_db()
    fixed_item = catalog_service.get_catalog_item("website_landing_page")
    custom_item = catalog_service.get_catalog_item("custom_video")
    fixed_resp = bridge.customer_price_response(fixed_item)
    custom_resp = bridge.customer_price_response(custom_item)
    assert "Rp799.000" in fixed_resp
    assert "custom quote" in custom_resp.lower()
    # never invents a number for a custom-quote item
    assert not any(ch.isdigit() for ch in custom_resp)
    print("test_customer_price_response_fixed_vs_custom_quote OK")


def test_customer_payment_response_always_routes_to_app_not_whatsapp():
    fixed_resp = bridge.customer_payment_response("FIXED_PRICE")
    custom_resp = bridge.customer_payment_response("CUSTOM_QUOTE")
    assert "app.kilasworks.id" in fixed_resp or "Business Hub" in fixed_resp
    assert "quotation" in custom_resp.lower() and "disetujui" in custom_resp.lower()
    print("test_customer_payment_response_always_routes_to_app_not_whatsapp OK")


# ---------------------------------------------------------------------------
# PHASE F — tenant_config_service additions
# ---------------------------------------------------------------------------

def test_get_active_service_catalog_matches_catalog_service():
    reset_db()
    from_bridge_contract = tenant_config_service.get_active_service_catalog()
    from_catalog_service = catalog_service.list_active_catalog()
    assert {i["catalog_key"] for i in from_bridge_contract} == {i["catalog_key"] for i in from_catalog_service}
    print("test_get_active_service_catalog_matches_catalog_service OK")


def test_get_open_projects_summary_excludes_terminal_and_is_tenant_scoped():
    reset_db()
    user_a, biz_a = _make_owner_and_business("owner_f1@test.com")
    user_b, biz_b = _make_owner_and_business("owner_f2@test.com")
    p1 = projects_repo.create_custom_project(biz_a, "VIDEO", "Video A", {}, 1_000_000, 2_000_000, user_a)
    p2 = projects_repo.create_custom_project(biz_a, "PHOTO", "Photo A", {}, 500_000, 800_000, user_a)
    projects_repo.set_project_status(p2, "COMPLETED", actor_user_id=user_a, business_id=biz_a)
    projects_repo.create_custom_project(biz_b, "VIDEO", "Video B", {}, 1_000_000, 2_000_000, user_b)

    summary_a = tenant_config_service.get_open_projects_summary(biz_a)
    ids_a = {s["project_id"] for s in summary_a}
    assert p1 in ids_a
    assert p2 not in ids_a, "COMPLETED projects must not show up as 'open'"
    assert len(summary_a) == 1, "must not leak business B's project into business A's summary"
    print("test_get_open_projects_summary_excludes_terminal_and_is_tenant_scoped OK")


# ---------------------------------------------------------------------------
# PHASE H — human takeover
# ---------------------------------------------------------------------------

def test_default_mode_is_ai_active_with_no_row():
    reset_db()
    user_id, business_id = _make_owner_and_business("owner_f3@test.com")
    assert wa_takeover_service.get_state(business_id, "6281111111111") == "AI_ACTIVE"
    assert not wa_takeover_service.is_human_takeover_active(business_id, "6281111111111")
    print("test_default_mode_is_ai_active_with_no_row OK")


def test_start_and_return_human_takeover_round_trip():
    reset_db()
    user_id, business_id = _make_owner_and_business("owner_f4@test.com")
    wa_takeover_service.start_human_takeover(business_id, "6281111111111", user_id)
    assert wa_takeover_service.is_human_takeover_active(business_id, "6281111111111")
    wa_takeover_service.return_to_ai(business_id, "6281111111111", user_id)
    assert not wa_takeover_service.is_human_takeover_active(business_id, "6281111111111")
    print("test_start_and_return_human_takeover_round_trip OK")


def test_human_takeover_is_scoped_per_business_and_per_customer():
    reset_db()
    user_a, biz_a = _make_owner_and_business("owner_f5@test.com")
    user_b, biz_b = _make_owner_and_business("owner_f6@test.com")
    wa_takeover_service.start_human_takeover(biz_a, "6281111111111", user_a)

    # same customer number, different tenant — must NOT be affected
    assert not wa_takeover_service.is_human_takeover_active(biz_b, "6281111111111")
    # same tenant, different customer — must NOT be affected
    assert not wa_takeover_service.is_human_takeover_active(biz_a, "6282222222222")
    print("test_human_takeover_is_scoped_per_business_and_per_customer OK")


def test_get_conversation_mode_contract_matches_wa_takeover_service():
    reset_db()
    user_id, business_id = _make_owner_and_business("owner_f7@test.com")
    assert tenant_config_service.get_conversation_mode(business_id, "6281111111111") == "AI_ACTIVE"
    wa_takeover_service.start_human_takeover(business_id, "6281111111111", user_id)
    assert tenant_config_service.get_conversation_mode(business_id, "6281111111111") == "HUMAN_TAKEOVER"
    print("test_get_conversation_mode_contract_matches_wa_takeover_service OK")


if __name__ == "__main__":
    test_owner_action_requires_explicit_send_verb()
    test_owner_message_without_send_verb_is_never_action()
    test_parse_owner_offers_extracts_quantity_and_price_pairs()
    test_parse_owner_offers_never_infers_missing_price()
    test_customer_facing_message_never_leaks_owner_raw_wording_or_markers()
    test_customer_price_response_fixed_vs_custom_quote()
    test_customer_payment_response_always_routes_to_app_not_whatsapp()
    test_get_active_service_catalog_matches_catalog_service()
    test_get_open_projects_summary_excludes_terminal_and_is_tenant_scoped()
    test_default_mode_is_ai_active_with_no_row()
    test_start_and_return_human_takeover_round_trip()
    test_human_takeover_is_scoped_per_business_and_per_customer()
    test_get_conversation_mode_contract_matches_wa_takeover_service()
    print("\nALL BUSINESS HUB V2 PHASE F/G/H TESTS PASSED")
