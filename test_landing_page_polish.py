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
    html = _read()
    assert "Coba Demo AI Admin" in html
    match = re.search(r'href="([^"]+)"[^>]*>\s*Coba Demo AI Admin', html)
    assert match, "Coba Demo AI Admin link not found"
    assert match.group(1) == "https://kilasworks.id/demo", match.group(1)
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


def test_meta_ads_still_present_but_deemphasized():
    """FINAL PRODUCT DECISIONS #1: do NOT delete Meta Ads architecture/data; keep it
    dormant/secondary, not prominently exposed in the primary flow."""
    html = _read()
    assert "Meta Ads" in html, "Meta Ads card must NOT be deleted"
    # De-emphasized: no longer the "wide" 2-column featured card.
    meta_ads_idx = html.find(">Meta Ads<")
    card_start = html.rfind('<div class="service-card', 0, meta_ads_idx)
    card_tag = html[card_start:card_start + 40]
    assert "wide" not in card_tag, card_tag
    # De-emphasized: no longer mentioned in the hero's primary one-line pitch.
    hero_sub_match = re.search(r'<p class="hero-sub">(.*?)</p>', html)
    assert hero_sub_match and "Meta Ads" not in hero_sub_match.group(1)
    print("test_meta_ads_still_present_but_deemphasized OK")


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
    test_meta_ads_still_present_but_deemphasized()
    test_html_tags_balanced()
    print("ALL LANDING PAGE POLISH TESTS PASSED")
