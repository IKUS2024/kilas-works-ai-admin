"""Knowledge architecture regression suite — Tests A-F from the bug report.

ROOT CAUSE (see _build_active_service_categories_safe()'s own docstring in app.py): the owner's
"jasa kita apa aja" instruction pointed only at PRICING_TEXT_BLOCK, a static hardcoded dict that
never included Talent Management (no fixed price). This file proves the fix: a single, live,
canonical service-category list (read straight from Client Hub's service_catalog table) is now
wired into both the owner and customer prompts, and the recommendation-logic guidance is explicit
about when Talent Management should/shouldn't be suggested.

Tests G and H (Admin Dashboard catalog-editor removal) live in
client-hub/tests/test_catalog_editor_removed.py instead — they need Client Hub's OWN Flask app
object, which this file's bridge-import pattern deliberately does not load in-process (see
_test_bootstrap.py's own docstring for why: root app.py and client-hub/app.py share the module
name "app", and importing both in one process risks the exact shadowing bug documented there).

Run with:
    python3 test_knowledge_architecture.py
"""
import os
import sys

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as chdb  # noqa: E402
import talent_service  # noqa: E402
import catalog_service  # noqa: E402


def reset_state():
    chdb.execute("DELETE FROM talents")
    catalog_service.seed_catalog_if_needed()  # only runs once at client-hub/app.py's OWN module
    # import time (never loaded in this process — see module docstring), so a top-level test that
    # never triggers that import must seed it explicitly, same fix already applied in
    # client-hub/tests/test_ai_admin_single_purchase_path.py's own reset_db().


def _seed_talent(name, handle, followers, niche):
    return talent_service.create_talent(name, social_handle=handle, follower_count=followers, niche=niche)


# ---------------------------------------------------------------------------
# TEST A — owner "Layanan kita apa aja?" -> ALL active categories, including Talent Management.
# ---------------------------------------------------------------------------
def test_A_owner_service_listing_includes_talent_management():
    reset_state()
    prompt = appmod.build_owner_system_prompt(None, None)
    assert "DAFTAR KATEGORI LAYANAN AKTIF KILAS WORKS" in prompt
    assert "Talent Management" in prompt
    assert "AI Admin WhatsApp" in prompt
    assert "Website" in prompt
    # The explicit instruction connecting a general "jasa kita apa aja" question to this block.
    assert "DAFTAR KATEGORI LAYANAN AKTIF" in prompt and "WAJIB pakai blok" in prompt
    print("test_A_owner_service_listing_includes_talent_management OK")


# ---------------------------------------------------------------------------
# TEST B — customer "Kilas Works ada jasa apa aja?" -> all main categories mentioned, no price.
# ---------------------------------------------------------------------------
def test_B_customer_service_listing_all_categories_no_price():
    reset_state()
    prompt = appmod.build_customer_system_prompt("628999900001")
    assert "DAFTAR KATEGORI LAYANAN AKTIF KILAS WORKS" in prompt
    assert "Talent Management" in prompt

    # Isolate just the category-list block itself and confirm it carries no Rupiah figure — this
    # block specifically is what a "list everything" answer should be grounded in, and it must be
    # price-free (the surrounding prompt legitimately has prices elsewhere as background
    # knowledge/for the code-level guardrail to reason about, but THIS block must not).
    start = prompt.find("DAFTAR KATEGORI LAYANAN AKTIF KILAS WORKS")
    end = prompt.find("\n\n", start + 50)
    block = prompt[start:end if end != -1 else start + 600]
    assert not appmod.CUSTOMER_PRICE_DISCLOSURE_PATTERN.search(block), block

    assert "LISTING vs RECOMMENDING" in prompt
    print("test_B_customer_service_listing_all_categories_no_price OK")


# ---------------------------------------------------------------------------
# TEST C — customer needs a model/talent for a shoot -> Talent Management recommendation allowed.
# ---------------------------------------------------------------------------
def test_C_talent_recommendation_allowed_for_relevant_need():
    prompt = appmod.SYSTEM_PROMPT
    assert "butuh talent/model" in prompt
    assert "buat shooting" in prompt or "UGC talent" in prompt
    print("test_C_talent_recommendation_allowed_for_relevant_need OK")


# ---------------------------------------------------------------------------
# TEST D — customer needs a website -> Talent Management must NOT be randomly recommended.
# ---------------------------------------------------------------------------
def test_D_talent_not_randomly_recommended_for_unrelated_need():
    prompt = appmod.SYSTEM_PROMPT
    assert "JANGAN random dorong Talent Management" in prompt
    assert "customer bilang" in prompt and "website" in prompt
    print("test_D_talent_not_randomly_recommended_for_unrelated_need OK")


# ---------------------------------------------------------------------------
# TEST E — admin adds/edits an active talent -> AI reads it immediately, no restart/deploy.
# ---------------------------------------------------------------------------
def test_E_newly_added_talent_appears_without_restart():
    reset_state()
    # Confirm the roster is empty BEFORE the "admin action" (same live process, same prompt-
    # building function — proves this is a live read, not something cached from process start).
    note_before = appmod._build_live_talent_knowledge_note_safe(for_owner=True)
    assert "Rina Baru" not in note_before

    # Simulate an admin adding a new talent via the dashboard (talent_service.create_talent is the
    # exact function routes_talent.py's admin "create" route calls).
    _seed_talent("Rina Baru", "@rinabaru", 250_000, "Beauty")

    note_after = appmod._build_live_talent_knowledge_note_safe(for_owner=True)
    assert "Rina Baru" in note_after, \
        "BUG: a newly-added talent did not appear without any restart/redeploy/prompt edit"
    print("test_E_newly_added_talent_appears_without_restart OK")


def test_E_edited_talent_field_reflects_immediately():
    reset_state()
    tid = _seed_talent("Budi Talent", "@buditalent", 100_000, "Fashion")
    talent_service.update_talent(tid, niche="Lifestyle")
    note = appmod._build_live_talent_knowledge_note_safe(for_owner=True)
    assert "niche Lifestyle" in note
    assert "niche Fashion" not in note
    print("test_E_edited_talent_field_reflects_immediately OK")


# ---------------------------------------------------------------------------
# TEST F — admin deactivates a talent -> no longer recommended/listed to the customer.
# ---------------------------------------------------------------------------
def test_F_deactivated_talent_excluded_from_customer_facing_note():
    reset_state()
    tid = _seed_talent("Akan Diarsip", "@akandiarsip", 50_000, "Travel")
    note_active = appmod._build_live_talent_knowledge_note_safe(for_owner=False)
    assert "Akan Diarsip" in note_active

    talent_service.archive_talent(tid)

    note_after = appmod._build_live_talent_knowledge_note_safe(for_owner=False)
    assert "Akan Diarsip" not in note_after, \
        "BUG: a deactivated talent is still being offered to customers"
    print("test_F_deactivated_talent_excluded_from_customer_facing_note OK")


def test_F_deactivated_talent_excluded_from_owner_active_count_but_reactivatable():
    reset_state()
    tid = _seed_talent("Owner Cek Ini", "@ownercekini", 75_000, "Food")
    talent_service.archive_talent(tid)
    assert not any(t["id"] == tid for t in talent_service.list_active_talents())
    talent_service.reactivate_talent(tid)
    assert any(t["id"] == tid for t in talent_service.list_active_talents())
    print("test_F_deactivated_talent_excluded_from_owner_active_count_but_reactivatable OK")


if __name__ == "__main__":
    test_A_owner_service_listing_includes_talent_management()
    test_B_customer_service_listing_all_categories_no_price()
    test_C_talent_recommendation_allowed_for_relevant_need()
    test_D_talent_not_randomly_recommended_for_unrelated_need()
    test_E_newly_added_talent_appears_without_restart()
    test_E_edited_talent_field_reflects_immediately()
    test_F_deactivated_talent_excluded_from_customer_facing_note()
    test_F_deactivated_talent_excluded_from_owner_active_count_but_reactivatable()
    print("ALL KNOWLEDGE ARCHITECTURE TESTS PASSED")
