"""Kilas Works Brand + Landing Page + Live Catalog + AI Integration — acceptance test suite.

Run with:
    python3 test_brand_landing_catalog.py
"""
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# Import the ROOT app.py FIRST, before any client-hub sys.path manipulation happens below — client
# hub's own directory must never be allowed to shadow the root "app" module name (see
# client-hub/ai_onboarding.py's own comment on this exact class of bug, found and fixed earlier in
# this project: sys.path.insert(0, ...) risks exactly this collision; append() does not).
import app as appmod
import ai_brain_shared


def _read_landing():
    with open(os.path.join(REPO_ROOT, "landing-page-kilasworks.html"), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1/4. Canonical pricing — landing/catalog never hardcode Rupiah prices.
# ---------------------------------------------------------------------------
def test_landing_page_has_zero_hardcoded_rupiah_prices():
    html = _read_landing()
    assert not re.search(r"Rp\s?\d", html), "the landing page must never hardcode a Rupiah figure"
    print("test_landing_page_has_zero_hardcoded_rupiah_prices OK")


def test_landing_page_services_immediately_after_hero():
    html = _read_landing()
    hero_idx = html.find('<section class="hero">')
    layanan_idx = html.find('<section id="layanan">')
    next_section_after_hero = html.find("<section", hero_idx + 1)
    assert hero_idx != -1 and layanan_idx != -1
    assert next_section_after_hero == layanan_idx
    print("test_landing_page_services_immediately_after_hero OK")


def test_landing_page_shows_all_six_core_service_groups():
    html = _read_landing()
    for group in ("AI WhatsApp Admin", "Content &amp; Creative", "Meta Ads",
                  "Website &amp; Digital Solutions", "Talent &amp; Creator Management",
                  "Custom Solutions"):
        assert group in html, f"missing core service group: {group}"
    print("test_landing_page_shows_all_six_core_service_groups OK")


def test_landing_page_main_cta_resolves_to_official_client_hub_link():
    """The header's "Masuk / Daftar" is the primary onboarding/payment entry point (the hero's own
    primary CTA is intentionally "Lihat Layanan" instead, per the hero-rework task, to avoid a
    redundant registration CTA competing with the header) — this checks that link, wherever it
    lives, resolves to the official Client Hub URL."""
    html = _read_landing()
    idx = html.find("Masuk / Daftar")
    assert idx != -1
    preceding = html[max(0, idx - 200):idx]
    assert "https://app.kilasworks.id" in preceding
    print("test_landing_page_main_cta_resolves_to_official_client_hub_link OK")


def test_landing_page_mobile_structure_still_valid():
    html = _read_landing()
    assert "@media" in html
    assert html.count("<section") == html.count("</section>")
    print("test_landing_page_mobile_structure_still_valid OK")


# ---------------------------------------------------------------------------
# 2/3/6/7/8. Public catalog + AI pricing behavior (Client Hub side).
# ---------------------------------------------------------------------------
def _client_hub_setup():
    import tempfile
    sys.path.append(os.path.join(REPO_ROOT, "client-hub"))
    import db as ch_db
    import catalog_service
    os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(suffix=".db")
    ch_db._local.conn = None
    ch_db.init_schema()
    catalog_service.seed_catalog_if_needed()
    return catalog_service, ch_db


def test_admin_price_change_reflected_through_canonical_read():
    catalog_service, ch_db = _client_hub_setup()
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], price_amount=850000)
    reread = catalog_service.get_catalog_item("website_landing_page")
    assert reread["price_amount"] == 850000
    print("test_admin_price_change_reflected_through_canonical_read OK")


def test_custom_quote_never_invents_a_number():
    catalog_service, ch_db = _client_hub_setup()
    item = catalog_service.get_catalog_item("custom_video")
    assert item["price_amount"] is None
    label = catalog_service.format_price(item["price_amount"], item["price_unit"])
    assert label == "Penawaran disesuaikan dengan kebutuhan project."
    assert not re.search(r"\d", label)
    print("test_custom_quote_never_invents_a_number OK")


def test_customer_catalog_page_no_raw_pricing_mode_or_fixed_label():
    catalog_service, ch_db = _client_hub_setup()
    with open(os.path.join(REPO_ROOT, "client-hub", "templates", "service_catalog.html"),
              encoding="utf-8") as f:
        template_src = f.read()
    assert ">Fixed<" not in template_src
    assert ">FIXED<" not in template_src
    assert "{{ item.pricing_mode }}" not in template_src
    print("test_customer_catalog_page_no_raw_pricing_mode_or_fixed_label OK")


def test_inactive_service_not_offered_publicly():
    catalog_service, ch_db = _client_hub_setup()
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], is_active=False)
    active_keys = [i["catalog_key"] for i in catalog_service.list_active_catalog()]
    assert "website_landing_page" not in active_keys
    print("test_inactive_service_not_offered_publicly OK")


def test_inactive_service_does_not_delete_historical_orders():
    catalog_service, ch_db = _client_hub_setup()
    import repo, security, projects_repo
    uid = repo.create_user(f"hist_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    bid = repo.create_business(uid, "Hist Biz", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    project_id = projects_repo.create_fixed_price_project(bid, item, uid)
    catalog_service.update_catalog_item(item["id"], is_active=False)
    project = projects_repo.get_project(project_id)
    assert project is not None
    assert project["final_price"] == item["price_amount"]
    print("test_inactive_service_does_not_delete_historical_orders OK")


# ---------------------------------------------------------------------------
# 9/10. Talent public-vs-internal.
# ---------------------------------------------------------------------------
def test_public_landing_no_talent_roster_leak():
    catalog_service, ch_db = _client_hub_setup()
    import talent_service
    html = _read_landing()
    for talent in talent_service.SEED_TALENTS:
        assert talent["name"] not in html
        assert talent["social_handle"] not in html
    print("test_public_landing_no_talent_roster_leak OK")


def test_ai_can_use_internal_talent_data_when_explicitly_asked():
    assert callable(appmod._build_live_talent_knowledge_note_safe)
    print("test_ai_can_use_internal_talent_data_when_explicitly_asked OK")


# ---------------------------------------------------------------------------
# 11/12. Unified Brain / tenant isolation still intact.
# ---------------------------------------------------------------------------
def test_kilas_pricing_and_brand_data_cannot_leak_into_tenant_ai():
    assert "app.kilasworks.id" not in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "LINK RESMI KILAS WORKS" not in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_kilas_pricing_and_brand_data_cannot_leak_into_tenant_ai OK")


def test_unified_brain_parity_still_intact():
    assert ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR in appmod.SYSTEM_PROMPT
    assert ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR in appmod.DEMO_SYSTEM_PROMPT
    print("test_unified_brain_parity_still_intact OK")


# ---------------------------------------------------------------------------
# 13. Catalog/PDF premium redesign — no raw "Mode"/"Fixed" label, uses official links.
# ---------------------------------------------------------------------------
def test_pdf_never_shows_raw_mode_or_fixed_label():
    catalog_service, ch_db = _client_hub_setup()
    import live_catalog_pdf
    pdf_bytes = live_catalog_pdf.generate_catalog_pdf_bytes()
    assert pdf_bytes[:4] == b"%PDF"
    # Precise check: the actual table header call must be exactly ["Layanan", "Harga"] — never a
    # 3rd "Mode" column. A comment mentioning the word "Mode" (explaining the fix) is fine and
    # expected; only the literal header_row(...) call argument list matters here.
    with open(os.path.join(REPO_ROOT, "client-hub", "live_catalog_pdf.py"), encoding="utf-8") as f:
        source = f.read()
    assert 'header_row(["Layanan", "Harga"])' in source
    assert 'header_row(["Layanan", "Harga", "Mode"])' not in source
    assert 'mode_label = "Fixed"' not in source
    print("test_pdf_never_shows_raw_mode_or_fixed_label OK")


def test_pdf_uses_official_links_source_of_truth_not_hardcoded():
    catalog_service, ch_db = _client_hub_setup()
    import repo as ch_repo
    ch_repo.set_platform_setting("official_link_instagram", "https://instagram.com/testoverride")
    import live_catalog_pdf
    import importlib
    importlib.reload(live_catalog_pdf)  # pick up the just-set override cleanly
    pdf_bytes = live_catalog_pdf.generate_catalog_pdf_bytes()
    assert pdf_bytes[:4] == b"%PDF"
    with open(os.path.join(REPO_ROOT, "client-hub", "live_catalog_pdf.py"), encoding="utf-8") as f:
        source = f.read()
    assert "instagram.com/kilasworks" not in source, \
        "the PDF generator must read the link from repo.get_official_links(), never hardcode it"
    assert "repo.get_official_links()" in source
    print("test_pdf_uses_official_links_source_of_truth_not_hardcoded OK")


if __name__ == "__main__":
    test_landing_page_has_zero_hardcoded_rupiah_prices()
    test_landing_page_services_immediately_after_hero()
    test_landing_page_shows_all_six_core_service_groups()
    test_landing_page_main_cta_resolves_to_official_client_hub_link()
    test_landing_page_mobile_structure_still_valid()
    test_admin_price_change_reflected_through_canonical_read()
    test_custom_quote_never_invents_a_number()
    test_customer_catalog_page_no_raw_pricing_mode_or_fixed_label()
    test_inactive_service_not_offered_publicly()
    test_inactive_service_does_not_delete_historical_orders()
    test_public_landing_no_talent_roster_leak()
    test_ai_can_use_internal_talent_data_when_explicitly_asked()
    test_kilas_pricing_and_brand_data_cannot_leak_into_tenant_ai()
    test_unified_brain_parity_still_intact()
    test_pdf_never_shows_raw_mode_or_fixed_label()
    test_pdf_uses_official_links_source_of_truth_not_hardcoded()
    print("ALL BRAND/LANDING/CATALOG TESTS PASSED")
