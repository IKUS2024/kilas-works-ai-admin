"""Gap-fix Area I — landing page polish regression tests:
- 'Konsultasi' nav CTA text renamed to 'Tanya Kilas Works', same WhatsApp destination (unchanged
  per FINAL PRODUCT DECISIONS: wa.me/6282213039137, never replaced).
- 'Jadwalkan Live Demo' scheduled-demo button removed entirely (ties to Area C).
- 'Coba Demo AI Admin' now points to https://kilasworks.id/demo (not the raw Render URL).
- Masuk/Daftar contrast improved (no longer fully transparent background).
- Basic mobile-polish media query coverage added.
- Meta Ads kept dormant/secondary (present but de-emphasized) per FINAL PRODUCT DECISIONS #1 —
  never deleted.

Run with:
    python3 test_landing_page_polish.py
"""
import os
import re

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
LANDING_PATH = os.path.join(REPO_ROOT, "landing-page-kilasworks.html")


def _read():
    with open(LANDING_PATH, encoding="utf-8") as f:
        return f.read()


def test_konsultasi_renamed_to_tanya_kilas_works_same_whatsapp_number():
    html = _read()
    assert ">Konsultasi<" not in html, "old exact 'Konsultasi' nav label text must be gone"
    assert "Tanya Kilas Works" in html
    assert "wa.me/6282213039137" in html, "WhatsApp CTA number must be unchanged per final decisions"
    print("test_konsultasi_renamed_to_tanya_kilas_works_same_whatsapp_number OK")


def test_jadwalkan_live_demo_removed():
    html = _read()
    assert "Jadwalkan Live Demo" not in html
    assert "live%20demo%20AI%20Admin" not in html
    print("test_jadwalkan_live_demo_removed OK")


def test_coba_demo_ai_admin_points_to_kilasworks_id():
    """Demo domain integration cycle: the primary demo CTA now points to the dedicated,
    professional demo subdomain (https://demo.kilasworks.id), which host-aware-redirects to the
    existing /demo implementation server-side (see app.py's health_check() route) — no demo code
    is duplicated, this is purely a link-destination change."""
    html = _read()
    assert "Coba Demo Kilas Brain" in html  # 2026 rebrand: public flagship name is now Kilas Brain
    match = re.search(r'href="([^"]+)"[^>]*>\s*Coba Demo Kilas Brain', html)
    assert match, "Coba Demo Kilas Brain link not found"
    assert match.group(1) == "https://demo.kilasworks.id", match.group(1)
    assert "kilas-works-ai-admin.onrender.com" not in html, "raw Render URL must no longer be exposed publicly"
    print("test_coba_demo_ai_admin_points_to_kilasworks_id OK")


def test_masuk_daftar_contrast_improved():
    html = _read()
    match = re.search(r'<a class="nav-cta" href="https://app\.kilasworks\.id"[^>]*>', html)
    assert match, "Masuk / Daftar button not found"
    tag = match.group(0)
    assert "background:transparent" not in tag, "must no longer be a fully transparent ghost button"
    print("test_masuk_daftar_contrast_improved OK")


def test_mobile_media_queries_present():
    html = _read()
    assert html.count("@media") >= 2, "at least one additional mobile breakpoint expected beyond the original 860px one"
    assert "max-width:480px" in html
    print("test_mobile_media_queries_present OK")


def test_meta_ads_still_present_and_not_over_featured_card():
    """FINAL PRODUCT DECISIONS #1 (superseded in part by the Brand/Landing hero rework task):
    Meta Ads must never be deleted, and its SERVICE CARD must not be the oversized "wide" featured
    card (that visual prominence is reserved for AI WhatsApp Admin, the flagship product). The
    EARLIER "never mention Meta Ads in the hero subcopy" restriction is intentionally REVERSED by
    the hero rework task, which explicitly requires the subcopy to summarize the full service
    ecosystem including Meta Ads — so mentioning it in hero-sub is now correct, expected
    behavior, not a regression."""
    html = _read()
    assert "Meta Ads" in html, "Meta Ads card must NOT be deleted"
    meta_ads_idx = html.find(">Meta Ads<")
    card_start = html.rfind('<div class="service-card', 0, meta_ads_idx)
    card_tag = html[card_start:card_start + 40]
    assert "wide" not in card_tag, card_tag
    print("test_meta_ads_still_present_and_not_over_featured_card OK")


def test_html_tags_balanced():
    html = _read()
    for tag in ("div", "section", "header", "footer"):
        opens = len(re.findall(rf"<{tag}\b", html))
        closes = len(re.findall(rf"</{tag}>", html))
        assert opens == closes, f"<{tag}> imbalance: {opens} opens vs {closes} closes"
    print("test_html_tags_balanced OK")


if __name__ == "__main__":
    test_konsultasi_renamed_to_tanya_kilas_works_same_whatsapp_number()
    test_jadwalkan_live_demo_removed()
    test_coba_demo_ai_admin_points_to_kilasworks_id()
    test_masuk_daftar_contrast_improved()
    test_mobile_media_queries_present()
    test_meta_ads_still_present_and_not_over_featured_card()
    test_html_tags_balanced()
    print("ALL LANDING PAGE POLISH TESTS PASSED")
