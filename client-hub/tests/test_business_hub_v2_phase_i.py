"""Kilas Works Client Hub — Business Hub V2, PHASE I test suite.

Covers Section 27/33: landing page + WhatsApp catalog PDF both mention Talent Management,
marketing-only (no full price dump on the landing page, no invented number for a CUSTOM_QUOTE
service in either place). Does NOT touch the live production bot's message-handling logic —
generate_katalog_pdf.py only reads ../app.py's PRICING_CONFIG dict and client-hub/talent_service.py's
SEED_TALENTS list; it does not execute or modify any webhook/bot behavior.

ADDITIVE — every earlier test file is untouched. Run with:
    cd client-hub && python3 tests/test_business_hub_v2_phase_i.py
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import talent_service  # noqa: E402


def test_landing_page_mentions_talent_management_without_prices():
    with open(os.path.join(REPO_ROOT, "landing-page-kilasworks.html"), encoding="utf-8") as f:
        html = f.read()
    assert "Talent Management" in html
    idx = html.find("Talent Management")
    snippet = html[idx:idx + 600]
    assert "Custom Quote" in snippet or "custom" in snippet.lower()
    # marketing-only: no talent names/handles/follower counts on the public landing page
    for talent in talent_service.SEED_TALENTS:
        assert talent["name"] not in snippet
        assert talent["social_handle"] not in snippet
    print("test_landing_page_mentions_talent_management_without_prices OK")


def test_katalog_pdf_talent_section_has_no_invented_price():
    import pypdf
    katalog_path = os.path.join(REPO_ROOT, "katalog.pdf")
    reader = pypdf.PdfReader(katalog_path)
    full_text = "\n".join(page.extract_text() for page in reader.pages)
    assert "TALENT MANAGEMENT" in full_text
    idx = full_text.find("TALENT MANAGEMENT")
    section_text = full_text[idx:idx + 800]
    assert "Custom quote" in section_text
    # every seeded talent's name and handle appear (this IS the internal/WA catalog, unlike the
    # public landing page — but still never an invented rupiah figure for talent pricing)
    for talent in talent_service.SEED_TALENTS:
        assert talent["name"] in section_text
        assert talent["social_handle"] in section_text
    assert "Rp" not in section_text, "talent pricing must never show an invented rupiah figure"
    print("test_katalog_pdf_talent_section_has_no_invented_price OK")


def test_katalog_pdf_still_has_all_prior_sections():
    import pypdf
    katalog_path = os.path.join(REPO_ROOT, "katalog.pdf")
    reader = pypdf.PdfReader(katalog_path)
    full_text = "\n".join(page.extract_text() for page in reader.pages)
    for expected_section in (
        "AI WHATSAPP ADMIN", "CONTENT PACKAGES", "META ADS", "WEBSITE",
        "DOMAIN", "EVENT PHOTO", "TALENT MANAGEMENT",
    ):
        assert expected_section in full_text, f"missing section: {expected_section}"
    print("test_katalog_pdf_still_has_all_prior_sections OK")


if __name__ == "__main__":
    test_landing_page_mentions_talent_management_without_prices()
    test_katalog_pdf_talent_section_has_no_invented_price()
    test_katalog_pdf_still_has_all_prior_sections()
    print("\nALL BUSINESS HUB V2 PHASE I TESTS PASSED")
