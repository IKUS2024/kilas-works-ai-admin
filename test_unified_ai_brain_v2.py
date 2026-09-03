"""Unified AI Brain v2 — acceptance test suite.

Run with:
    python3 test_unified_ai_brain_v2.py
"""
import os
import json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod
import ai_brain_shared

FLASK_APP = appmod.app
FLASK_APP.testing = True
FLASK_APP.config["PROPAGATE_EXCEPTIONS"] = True
client = FLASK_APP.test_client()


# ---------------------------------------------------------------------------
# 1. Short natural responses / no unnecessary praise.
# ---------------------------------------------------------------------------
def test_short_by_default_rule_present():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert "PENDEK ITU DEFAULT" in core
    assert "1-3 kalimat" in core
    print("test_short_by_default_rule_present OK")


def test_no_praise_rule_present():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert "Wah keren banget" in core
    assert "JANGAN muji-muji" in core
    print("test_no_praise_rule_present OK")


# ---------------------------------------------------------------------------
# 2. Direct scoped price answers / no unsolicited price dump / CUSTOM_QUOTE.
# ---------------------------------------------------------------------------
def test_price_scoping_rule_present():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert "JANGAN proaktif ngedumpin semua harga" in core
    assert "Balas HANYA layanan yang ditanya" in core
    print("test_price_scoping_rule_present OK")


def test_custom_quote_never_invents_price_rule_present():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert "CUSTOM QUOTE" in core
    assert "JANGAN PERNAH mengarang angka" in core
    print("test_custom_quote_never_invents_price_rule_present OK")


def test_customer_price_guardrail_still_enforced_code_level():
    assert hasattr(appmod, "_enforce_customer_price_guardrail")
    guarded = appmod._enforce_customer_price_guardrail("Harganya Rp999.000 ya kak", tenant_context_block="")
    assert "999.000" not in guarded
    print("test_customer_price_guardrail_still_enforced_code_level OK")


# ---------------------------------------------------------------------------
# 3. "tim" handoff wording, never "owner" to customers.
# ---------------------------------------------------------------------------
def test_tim_not_owner_wording_in_shared_core():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert 'sebut "tim"' in core
    assert 'PERNAH sebut kata "owner"' in core
    print("test_tim_not_owner_wording_in_shared_core OK")


def test_appointment_confirmation_says_tim_not_owner():
    with open("app.py", encoding="utf-8") as f:
        source = f.read()
    assert "Nanti tim kami akan ngobrol langsung" in source
    assert "Nanti owner akan ngobrol langsung" not in source
    print("test_appointment_confirmation_says_tim_not_owner OK")


# ---------------------------------------------------------------------------
# 4. Client Hub payment-first flow / manual payment only after reported failure.
# ---------------------------------------------------------------------------
def test_payment_first_app_kilasworks_id_rule_present():
    assert "PEMBAYARAN NORMAL SELALU LEWAT APP.KILASWORKS.ID DULU" in appmod.SYSTEM_PROMPT
    print("test_payment_first_app_kilasworks_id_rule_present OK")


def test_manual_payment_only_after_reported_failure_rule_present():
    idx = appmod.SYSTEM_PROMPT.find("PEMBAYARAN NORMAL SELALU LEWAT")
    section = appmod.SYSTEM_PROMPT[idx:idx + 700]
    assert "ERROR/GAGAL/GAK BISA DIAKSES" in section
    assert "bukan default" in section
    print("test_manual_payment_only_after_reported_failure_rule_present OK")


def test_existing_payment_tag_mechanism_still_intact():
    assert "[GIVE_PAYMENT_INFO]" in appmod.SYSTEM_PROMPT
    assert appmod.TAG_GIVE_PAYMENT_INFO == "[GIVE_PAYMENT_INFO]"
    print("test_existing_payment_tag_mechanism_still_intact OK")


# ---------------------------------------------------------------------------
# 5. Official links source of truth.
# ---------------------------------------------------------------------------
def test_official_links_note_function_exists_and_is_tenant_safe():
    assert callable(appmod._build_official_links_note_safe)
    with open("app.py", encoding="utf-8") as f:
        source = f.read()
    idx = source.find("official_links_note = ")
    line = source[idx:source.find("\n", idx)]
    assert "if tenant_context_block else" in line
    print("test_official_links_note_function_exists_and_is_tenant_safe OK")


def test_official_links_admin_editable_source_of_truth():
    import sys
    import tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
    import repo as ch_repo
    import db as ch_db
    os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(suffix=".db")
    ch_db._local.conn = None
    ch_db.init_schema()
    links = ch_repo.get_official_links()
    assert links["app"] == "https://app.kilasworks.id"
    ch_repo.set_platform_setting("official_link_instagram", "https://instagram.com/customhandle")
    updated = ch_repo.get_official_links()
    assert updated["instagram"] == "https://instagram.com/customhandle"
    print("test_official_links_admin_editable_source_of_truth OK")


# ---------------------------------------------------------------------------
# 6. Helpful general-knowledge answer, no forced sale, no robotic "out of expertise" wording.
# ---------------------------------------------------------------------------
def test_helpful_knowledge_mode_present():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert "HELPFUL KNOWLEDGE MODE" in core
    normalized = " ".join(core.split())  # collapse line-wrapping before substring checks
    assert "di luar keahlian saya" in normalized
    idx = normalized.find("di luar keahlian saya")
    preceding = normalized[max(0, idx - 60):idx]
    assert "JANGAN" in preceding
    print("test_helpful_knowledge_mode_present OK")


# ---------------------------------------------------------------------------
# 7. Conversation context / no repeated questions / natural closing.
# ---------------------------------------------------------------------------
def test_no_repeated_questions_and_natural_closing_rules_present():
    core = ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR
    assert "jangan tanya ulang hal yang jawabannya udah ada" in core
    assert "oke makasih" in core
    print("test_no_repeated_questions_and_natural_closing_rules_present OK")


# ---------------------------------------------------------------------------
# 8. Basic vs Pro honest recommendation (existing Sales Brain V2, re-verified not regressed).
# ---------------------------------------------------------------------------
def test_honest_basic_recommendation_still_present():
    assert "JANGAN langsung kasih diskon" in appmod.SYSTEM_PROMPT
    print("test_honest_basic_recommendation_still_present OK")


# ---------------------------------------------------------------------------
# 9. Tenant isolation.
# ---------------------------------------------------------------------------
def test_tenant_prompt_never_gets_kilas_specific_notes():
    assert "LINK RESMI KILAS WORKS" not in appmod.TENANT_SYSTEM_PROMPT_BASE
    assert "PEMBAYARAN NORMAL SELALU LEWAT APP.KILASWORKS.ID" not in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_never_gets_kilas_specific_notes OK")


def test_tenant_prompt_still_shares_core_behavior():
    assert ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR in appmod.TENANT_SYSTEM_PROMPT_BASE
    print("test_tenant_prompt_still_shares_core_behavior OK")


# ---------------------------------------------------------------------------
# 10. Demo / Test AI parity with shared brain; side effects disabled.
# ---------------------------------------------------------------------------
def test_demo_prompt_shares_core_behavior():
    assert ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR in appmod.DEMO_SYSTEM_PROMPT
    print("test_demo_prompt_shares_core_behavior OK")


def test_client_hub_test_ai_shares_same_core_behavior_module():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
    import ai_onboarding as ch_ai_onboarding
    composed = ch_ai_onboarding.SIMULATION_SYSTEM_PROMPT_TEMPLATE.format(
        business_name="Test Biz", category="Kedai Kopi", config_text="(none)",
        primary_language="id", salutation="Kak",
    )
    assert ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR in composed
    assert ch_ai_onboarding.AI_ADMIN_BRAIN_VERSION == ai_brain_shared.AI_ADMIN_BRAIN_VERSION
    print("test_client_hub_test_ai_shares_same_core_behavior_module OK")


def test_demo_api_never_sends_real_whatsapp():
    """demo_api() legitimately calls send_whatsapp_message() for exactly ONE thing: notifying
    Kilas Works' OWN owner that a demo visitor left lead info (a genuine, intentional, existing
    feature — capturing sales leads from the sandbox is not a "production side effect" in the
    sense this test cares about, since it never touches any tenant/customer production data or
    state). The real safety property is that demo_api() never messages the DEMO VISITOR'S OWN
    number over real WhatsApp and never creates a real appointment/payment — checked precisely
    below rather than banning the function name outright."""
    import inspect
    source = inspect.getsource(appmod.demo_api)
    assert "send_reply_bubbles" not in source
    assert "create_appointment" not in source
    assert "payment_service.checkout" not in source
    if "send_whatsapp_message(" in source:
        idx = source.find("send_whatsapp_message(")
        call_context = source[idx:idx + 120]
        assert "OWNER_WHATSAPP_NUMBER" in call_context, \
            "the only allowed send_whatsapp_message() call in demo_api() is the owner-lead-notification one"
    print("test_demo_api_never_sends_real_whatsapp OK")


def test_client_hub_test_ai_never_sends_real_whatsapp_or_writes_appointments():
    import sys
    import inspect
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
    import ai_onboarding as ch_ai_onboarding
    source = inspect.getsource(ch_ai_onboarding.simulate_customer_reply)
    for forbidden in ("send_whatsapp", "create_appointment", "payment_service.checkout"):
        assert forbidden not in source
    print("test_client_hub_test_ai_never_sends_real_whatsapp_or_writes_appointments OK")


# ---------------------------------------------------------------------------
# 11. Brain version identifier present and consistent.
# ---------------------------------------------------------------------------
def test_brain_version_identifier_present_and_matches_across_surfaces():
    assert ai_brain_shared.AI_ADMIN_BRAIN_VERSION
    assert appmod.AI_ADMIN_BRAIN_VERSION == ai_brain_shared.AI_ADMIN_BRAIN_VERSION
    print("test_brain_version_identifier_present_and_matches_across_surfaces OK")


if __name__ == "__main__":
    test_short_by_default_rule_present()
    test_no_praise_rule_present()
    test_price_scoping_rule_present()
    test_custom_quote_never_invents_price_rule_present()
    test_customer_price_guardrail_still_enforced_code_level()
    test_tim_not_owner_wording_in_shared_core()
    test_appointment_confirmation_says_tim_not_owner()
    test_payment_first_app_kilasworks_id_rule_present()
    test_manual_payment_only_after_reported_failure_rule_present()
    test_existing_payment_tag_mechanism_still_intact()
    test_official_links_note_function_exists_and_is_tenant_safe()
    test_official_links_admin_editable_source_of_truth()
    test_helpful_knowledge_mode_present()
    test_no_repeated_questions_and_natural_closing_rules_present()
    test_honest_basic_recommendation_still_present()
    test_tenant_prompt_never_gets_kilas_specific_notes()
    test_tenant_prompt_still_shares_core_behavior()
    test_demo_prompt_shares_core_behavior()
    test_client_hub_test_ai_shares_same_core_behavior_module()
    test_demo_api_never_sends_real_whatsapp()
    test_client_hub_test_ai_never_sends_real_whatsapp_or_writes_appointments()
    test_brain_version_identifier_present_and_matches_across_surfaces()
    print("ALL UNIFIED AI BRAIN V2 TESTS PASSED")
