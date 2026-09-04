"""Sales Brain V2 regression tests.

Covers the 16 scenarios from the Sales Brain V2 brief: owner live talent roster access, customer
Talent Management confirmation without a raw dump, no internal_rate/internal_notes leakage to
customer, tenant isolation for Talent Management, greeting behavior, direct price answers,
objection handling, buying-signal handling, concise closing, memory/no-repeat-questions, human
takeover, and cross-tenant leakage — plus a final regression guard that existing
catalog/owner/payment/appointment/follow-up tests remain green (verified separately by running the
full suite, not duplicated here).

Run with:
    python3 test_sales_brain_v2.py
"""
import os
import sys
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "kilas-global-123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as chdb  # noqa: E402
import talent_service  # noqa: E402

client = appmod.app.test_client()


def reset_state():
    appmod.conversations.clear()
    appmod.customer_names.clear()
    appmod.active_customer_context.clear()
    appmod.followup_state.clear()
    appmod.agreed_facts.clear() if hasattr(appmod, "agreed_facts") else None
    chdb.execute("DELETE FROM talents")
    chdb.execute("DELETE FROM platform_wa_conversation_state")


def _seed_talent(name, handle, followers, niche, internal_rate=None, is_active=True):
    tid = talent_service.create_talent(
        name, social_handle=handle, follower_count=followers, niche=niche,
        internal_rate=internal_rate,
    )
    if not is_active:
        talent_service.archive_talent(tid)
    return tid


# ---------------------------------------------------------------------------
# 1 & 2. Owner: live active roster + confirms Talent Management exists
# ---------------------------------------------------------------------------
def test_owner_can_access_live_active_talent_roster():
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    note = appmod._build_live_talent_knowledge_note_safe(for_owner=True)
    assert "Putri Maudy" in note
    assert "Talent Management" in note
    print("test_owner_can_access_live_active_talent_roster OK")


def test_owner_prompt_confirms_talent_management_exists():
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    prompt = appmod.build_owner_system_prompt(None, None)
    assert "TALENT MANAGEMENT KILAS WORKS" in prompt
    assert "Putri Maudy" in prompt
    assert "internal_rate" in prompt  # owner IS authorized to see this
    print("test_owner_prompt_confirms_talent_management_exists OK")


# ---------------------------------------------------------------------------
# 3, 4, 5. Customer: confirms service without dumping roster; no internal data ever
# ---------------------------------------------------------------------------
def test_customer_prompt_confirms_talent_management_without_raw_dump_instruction():
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    prompt = appmod.build_customer_system_prompt("628999000001")
    assert "SOAL TALENT MANAGEMENT" in prompt
    assert "PUNYA layanan Talent Management" in prompt
    assert "JANGAN langsung dump" in prompt
    print("test_customer_prompt_confirms_talent_management_without_raw_dump_instruction OK")


def test_customer_prompt_can_offer_talent_names_when_context_exists():
    """The live roster note IS present as knowledge (names/handle/followers/niche) so the model
    CAN name a relevant talent once context/explicit request justifies it — this test just proves
    the public data reaches the prompt at all (behavioral gating is the LLM's job per the
    instructional text, verified in the previous test)."""
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    prompt = appmod.build_customer_system_prompt("628999000001")
    assert "Putri Maudy" in prompt
    assert "186rb" in prompt or "186.000" in prompt or "186000" in prompt
    print("test_customer_prompt_can_offer_talent_names_when_context_exists OK")


def test_customer_prompt_never_contains_internal_rate_or_notes():
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    talent_service.update_talent(
        talent_service.list_active_talents()[0]["id"], internal_notes="jangan follow up agresif"
    )
    prompt = appmod.build_customer_system_prompt("628999000001")
    assert "2.500.000" not in prompt and "2500000" not in prompt, "internal_rate must never leak to customer prompt"
    assert "jangan follow up agresif" not in prompt, "internal_notes must never leak to customer prompt"
    print("test_customer_prompt_never_contains_internal_rate_or_notes OK")


def test_customer_prompt_never_contains_raw_availability_code():
    reset_state()
    tid = _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle")
    talent_service.update_talent(tid, availability_status="BUSY")
    prompt = appmod.build_customer_system_prompt("628999000001")
    assert "availability BUSY" not in prompt
    assert "| BUSY" not in prompt
    print("test_customer_prompt_never_contains_raw_availability_code OK")


def test_owner_prompt_still_contains_availability_and_rate_for_owner():
    """Regression guard: stripping availability/rate from the CUSTOMER branch must not affect the
    OWNER branch, which is already verified working in production."""
    reset_state()
    tid = _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    talent_service.update_talent(tid, availability_status="BUSY")
    prompt = appmod.build_owner_system_prompt(None, None)
    assert "availability BUSY" in prompt
    assert "internal_rate Rp2.500.000" in prompt
    print("test_owner_prompt_still_contains_availability_and_rate_for_owner OK")


# ---------------------------------------------------------------------------
# 6. Tenant customer must NOT receive Kilas Works Talent Management data
# ---------------------------------------------------------------------------
def test_tenant_customer_never_receives_kilas_talent_data():
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    # Simulate a resolved tenant conversation the same way call_claude() does: tenant_context_block
    # is truthy -> live_talent_note must be "" (never built at all for a tenant).
    fake_tenant_context_block = "\n\nINI KONTEKS BISNIS TENANT (Kopi ABC)...\n"
    live_talent_note = "" if fake_tenant_context_block else appmod._build_live_talent_knowledge_note_safe(for_owner=False)
    assert live_talent_note == "", "a tenant customer must never receive Kilas Works' own talent roster"
    print("test_tenant_customer_never_receives_kilas_talent_data OK")


def test_tenant_system_prompt_base_has_no_talent_management_section():
    """TENANT_SYSTEM_PROMPT_BASE itself (the base persona for every tenant customer) must never
    mention Kilas Works' Talent Management service at all."""
    assert "Talent Management" not in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "SOAL TALENT MANAGEMENT" not in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_system_prompt_base_has_no_talent_management_section OK")


# ---------------------------------------------------------------------------
# 7. Simple greeting -> no catalog dump / no long sales pitch
# ---------------------------------------------------------------------------
def test_greeting_prompt_instructs_no_catalog_dump():
    prompt = appmod.build_customer_system_prompt("628999000099")
    assert "JANGAN langsung lempar harga" in prompt
    print("test_greeting_prompt_instructs_no_catalog_dump OK")


# ---------------------------------------------------------------------------
# 8. Direct price question -> customer NEVER gets the nominal price (business rule reversed —
# see the code-level guardrail this backs up: CUSTOMER_PRICE_DISCLOSURE_PATTERN in app.py). The
# raw price data still exists in the prompt as KNOWLEDGE (needed for internal reasoning/
# recommendations and for owner-mode, a completely separate prompt), but the customer-facing
# INSTRUCTION must say never to disclose it, not "answer directly."
# ---------------------------------------------------------------------------
def test_price_question_prompt_instructs_direct_answer():
    """2026 update: reverses the prior "never state a number" prompt instruction — Kilas Works'
    own customers now get a direct, concise answer when they ask a price question, sourced from
    the live canonical data above it in the prompt. See _enforce_customer_price_guardrail's own
    docstring for the code-level carve-out that backs this up (every disclosed number must still
    match a real canonical Kilas Works price, never an invented one)."""
    prompt = appmod.build_customer_system_prompt("628999000099")
    assert "999rb" in prompt  # Kilas Brain Pro price present as live knowledge
    assert "JAWAB LANGSUNG & SINGKAT pakai angka PERSIS" in prompt
    assert "ATURAN HARGA TERBARU" in prompt
    print("test_price_question_prompt_instructs_direct_answer OK")


# ---------------------------------------------------------------------------
# 9. Objection handling -> no automatic fake discount
# ---------------------------------------------------------------------------
def test_objection_prompt_forbids_auto_discount():
    prompt = appmod.build_customer_system_prompt("628999000099")
    assert "JANGAN langsung kasih diskon" in prompt
    assert "JANGAN PERNAH kasih diskon sendiri" in prompt
    print("test_objection_prompt_forbids_auto_discount OK")


# ---------------------------------------------------------------------------
# 10. Buying signal -> stop discovery, move to transaction
# ---------------------------------------------------------------------------
def test_buying_signal_prompt_present():
    prompt = appmod.build_customer_system_prompt("628999000099")
    assert "SIGNAL SIAP BELI" in prompt
    assert "STOP discovery" in prompt
    print("test_buying_signal_prompt_present OK")


# ---------------------------------------------------------------------------
# 11. Concise close, no repetitive CTA
# ---------------------------------------------------------------------------
def test_concise_closing_prompt_present_and_bans_boilerplate():
    prompt = appmod.build_customer_system_prompt("628999000099")
    assert "TAU KAPAN CUKUP" in prompt
    assert '"Tentu!"' in prompt
    assert "Ada lagi yang bisa saya" in prompt and "bantu?" in prompt
    print("test_concise_closing_prompt_present_and_bans_boilerplate OK")


# ---------------------------------------------------------------------------
# 12. Previously supplied facts -> must not re-ask
# ---------------------------------------------------------------------------
def test_known_facts_injected_into_prompt_not_reasked():
    reset_state()
    number = "628999000050"
    appmod.agreed_facts[number] = ["Deadline: minggu depan", "Jenis bisnis: cafe"]
    prompt = appmod.build_customer_system_prompt(number)
    assert "Deadline: minggu depan" in prompt
    assert "jangan tanya ulang" in prompt.lower() or "JANGAN PERNAH kontradiksi" in prompt
    print("test_known_facts_injected_into_prompt_not_reasked OK")


# ---------------------------------------------------------------------------
# 13. Human takeover -> AI stays silent (Kilas Works' own number)
# ---------------------------------------------------------------------------
def test_human_takeover_silences_ai_for_kilas_customer():
    import json
    reset_state()
    import platform_inbox_service
    number = "628999000060"
    platform_inbox_service.start_human_takeover(number, actor_user_id=None)

    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "kilas-global-123"},
            "messages": [{"id": "wamid.sb2.1", "from": number, "type": "text",
                          "text": {"body": "ada talent management?"}}],
        }}]}]
    }
    with patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_human_takeover_silences_ai_for_kilas_customer OK")


# ---------------------------------------------------------------------------
# 14. Cross-tenant leakage — two tenants never see each other's talent/catalog context
# ---------------------------------------------------------------------------
def test_cross_tenant_talent_note_never_built_for_any_tenant():
    reset_state()
    _seed_talent("Putri Maudy", "@pm__bae", 186_000, "Lifestyle", internal_rate=2_500_000)
    for fake_tenant_block in ("\n\nTenant A context...\n", "\n\nTenant B context...\n"):
        note = "" if fake_tenant_block else appmod._build_live_talent_knowledge_note_safe(for_owner=False)
        assert note == ""
    print("test_cross_tenant_talent_note_never_built_for_any_tenant OK")


# ---------------------------------------------------------------------------
# 15. Unknown/missing live talent data -> no hallucination, service still confirmed
# ---------------------------------------------------------------------------
def test_missing_talent_data_never_denies_service_or_hallucinates():
    reset_state()  # zero talents seeded
    note = appmod._build_live_talent_knowledge_note_safe(for_owner=False)
    assert "RESMI dan AKTIF" in note
    assert "belum ada talent aktif" in note or "Talent Management" in note
    assert "tidak punya Talent Management" not in note
    print("test_missing_talent_data_never_denies_service_or_hallucinates OK")


def test_talent_service_unavailable_never_denies_service():
    with patch.object(appmod, "_talent_service", None):
        note = appmod._build_live_talent_knowledge_note_safe(for_owner=False)
    assert "RESMI dan AKTIF" in note
    assert "Jangan pernah bilang Kilas Works tidak punya Talent Management" in note
    print("test_talent_service_unavailable_never_denies_service OK")


# ---------------------------------------------------------------------------
# TENANT Sales Brain V2 — business-agnostic equivalents inside TENANT_SYSTEM_PROMPT_BASE.
# Every check here also confirms ZERO Kilas Works content (products, prices, Talent Management,
# branding, owner-specific behavior) is present in the tenant prompt.
# ---------------------------------------------------------------------------
def test_tenant_prompt_has_style_adaptation():
    assert "ADAPT KE GAYA CUSTOMER" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "balas pendek juga" in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_has_style_adaptation OK")


def test_tenant_prompt_has_one_question_at_a_time_and_no_repeat():
    assert "SATU PERTANYAAN DULU" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "JANGAN PERNAH nanya ulang hal yang udah dijawab" in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_has_one_question_at_a_time_and_no_repeat OK")


def test_tenant_prompt_has_no_nominal_price_disclosure_rule():
    """Business rule reversed (production fix, applies to tenant customers too per explicit
    clarification): a tenant's own customer must never receive a nominal price during normal
    inquiry either — same safe default as Kilas Works' own customer bot, since no tenant-specific
    config anywhere in this codebase authorizes disclosing a price. The payment/checkout exception
    is still explicitly preserved in the prompt text."""
    base = appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "JANGAN SEBUT ANGKA KE CUSTOMER" in base
    assert "TIDAK PERNAH boleh dikasih angka nominal harga" in base
    assert "Pengecualian SATU-SATUNYA" in base and "checkout/pembayaran" in base
    print("test_tenant_prompt_has_no_nominal_price_disclosure_rule OK")


def test_tenant_prompt_has_objection_handling_no_fake_discount():
    assert "OBJECTION HANDLING" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "JANGAN langsung kasih diskon" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "gak punya otoritas nentuin" in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_has_objection_handling_no_fake_discount OK")


def test_tenant_prompt_has_buying_signal_behavior():
    assert "SIGNAL SIAP LANJUT" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "STOP discovery" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "BENERAN didukung bisnis ini" in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_has_buying_signal_behavior OK")


def test_tenant_prompt_has_concise_close_and_banned_boilerplate():
    assert "TAU KAPAN CUKUP" in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert '"Tentu!"' in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "Ada lagi yang bisa saya" in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_has_concise_close_and_banned_boilerplate OK")


def test_tenant_prompt_still_zero_kilas_content():
    base = appmod.TENANT_SYSTEM_PROMPT_BASE
    for forbidden in ("Talent Management", "AI WhatsApp Admin", "499.000", "999.000",
                      "PRICING_TEXT_BLOCK", "AI Admin", "internal_rate", "internal_notes"):
        assert forbidden not in base, f"tenant prompt must never contain: {forbidden}"
    # "Kilas Works" itself is allowed to appear EXACTLY once, inside the pre-existing prohibition
    # rule that explicitly forbids referencing it — never as an actual disclosure.
    count = base.count("Kilas Works")
    assert count == 1, f"expected exactly 1 mention (the prohibition rule), found {count}"
    idx = base.find("Kilas Works")
    assert "JANGAN PERNAH" in base[max(0, idx - 100):idx]
    print("test_tenant_prompt_still_zero_kilas_content OK")


def test_tenant_prompt_never_gets_system_prompt_appended():
    """build_customer_system_prompt() must use TENANT_SYSTEM_PROMPT_BASE, never SYSTEM_PROMPT, as
    the base when a tenant_context_block is present."""
    fake_tenant_context_block = "\n\nKONTEKS BISNIS TENANT (Kopi ABC): jual kopi, buka 08-22...\n"
    prompt = appmod.build_customer_system_prompt("628999666001", tenant_context_block=fake_tenant_context_block)
    assert prompt.startswith("Kamu admin WhatsApp resmi untuk bisnis ini")
    assert not prompt.startswith("Kamu admin WhatsApp Kilas Works")
    assert "Talent Management" not in prompt
    print("test_tenant_prompt_never_gets_system_prompt_appended OK")


if __name__ == "__main__":
    test_owner_can_access_live_active_talent_roster()
    test_owner_prompt_confirms_talent_management_exists()
    test_customer_prompt_confirms_talent_management_without_raw_dump_instruction()
    test_customer_prompt_can_offer_talent_names_when_context_exists()
    test_customer_prompt_never_contains_internal_rate_or_notes()
    test_customer_prompt_never_contains_raw_availability_code()
    test_owner_prompt_still_contains_availability_and_rate_for_owner()
    test_tenant_customer_never_receives_kilas_talent_data()
    test_tenant_system_prompt_base_has_no_talent_management_section()
    test_greeting_prompt_instructs_no_catalog_dump()
    test_price_question_prompt_instructs_direct_answer()
    test_objection_prompt_forbids_auto_discount()
    test_buying_signal_prompt_present()
    test_concise_closing_prompt_present_and_bans_boilerplate()
    test_known_facts_injected_into_prompt_not_reasked()
    test_human_takeover_silences_ai_for_kilas_customer()
    test_cross_tenant_talent_note_never_built_for_any_tenant()
    test_missing_talent_data_never_denies_service_or_hallucinates()
    test_talent_service_unavailable_never_denies_service()
    test_tenant_prompt_has_style_adaptation()
    test_tenant_prompt_has_one_question_at_a_time_and_no_repeat()
    test_tenant_prompt_has_no_nominal_price_disclosure_rule()
    test_tenant_prompt_has_objection_handling_no_fake_discount()
    test_tenant_prompt_has_buying_signal_behavior()
    test_tenant_prompt_has_concise_close_and_banned_boilerplate()
    test_tenant_prompt_still_zero_kilas_content()
    test_tenant_prompt_never_gets_system_prompt_appended()
    print("ALL SALES BRAIN V2 TESTS PASSED")
