import os, re, json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import app as appmod

client = appmod.app.test_client()


def reset_all():
    appmod.appointments.clear()
    appmod._appointment_id_counter = 0
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.active_customer_context.clear()
    appmod.meeting_requests.clear()
    appmod.payment_state.clear()
    appmod.followup_state.clear()
    appmod.pending_owner_questions.clear()
    appmod.lead_stage.clear()
    appmod.customer_language.clear()


sent_log = []


def fake_send_whatsapp_message(to, text):
    sent_log.append((to, text))
    return True, None


def fake_send_reply_bubbles(to, msg_id, text):
    for part in text.split("|||"):
        sent_log.append((to, part))
    return True, None


_msg_counter = [0]


def customer_payload(number, text, msg_id=None):
    if msg_id is None:
        _msg_counter[0] += 1
        msg_id = f"wamid.lang.{_msg_counter[0]}"
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id, "from": number, "type": "text", "text": {"body": text},
        }]}}]}]
    }


def send_customer_message(number, text, ai_reply):
    global sent_log
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        return client.post("/webhook", data=json.dumps(customer_payload(number, text)), content_type="application/json")


# ---------- 1. SYSTEM_PROMPT contains the key language-layer instructions ----------
def test_system_prompt_contains_language_instructions():
    p = appmod.SYSTEM_PROMPT
    assert "AUTO-DETECT" in p
    assert "[SET_LANG:" in p
    assert "JANGAN PERNAH nanya" in p and "mau pakai bahasa apa" in p
    assert "JANGAN PERNAH nerjemahin" in p
    print("test_system_prompt_contains_language_instructions OK")


# ---------- 2. Owner-facing prompt untouched (no language-layer text added) ----------
def test_owner_prompt_untouched():
    p = appmod.SYSTEM_PROMPT_OWNER_BASE
    assert "AUTO-DETECT" not in p
    assert "[SET_LANG:" not in p
    print("test_owner_prompt_untouched OK")


# ---------- 3. Full English customer: [SET_LANG: lang=en] stored, tag stripped from reply ----------
def test_full_english_customer():
    reset_all()
    number = "628900000001"
    ai_reply = ("Hi! Sure — I can help with that. Are you mainly looking for faster customer "
                "replies, lead handling, or appointment booking?[SET_LANG: lang=en]")
    resp = send_customer_message(number, "Hi, I'm interested in your AI Admin package.", ai_reply)
    assert resp.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_EN
    sent_texts = [t for n, t in sent_log if n == number]
    assert any("[SET_LANG" in t for t in sent_texts) is False, sent_texts
    assert any("Are you mainly looking for" in t for t in sent_texts), sent_texts
    print("test_full_english_customer OK")


# ---------- 4. Mixed Indonesian-English customer: dominant language still detected & stored ----------
def test_mixed_indonesian_english_customer():
    reset_all()
    number = "628900000002"
    ai_reply = ("Halo kak! Boleh tau kebutuhannya lebih ke content atau AI admin ya, biar "
                "aku bisa rekomendasiin package yang pas.[SET_LANG: lang=id]")
    resp = send_customer_message(number, "Halo kak, mau nanya about AI Admin package dong, harganya berapa ya?", ai_reply)
    assert resp.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_ID
    sent_texts = [t for n, t in sent_log if n == number]
    assert not any("[SET_LANG" in t for t in sent_texts), sent_texts
    print("test_mixed_indonesian_english_customer OK")


# ---------- 5. Customer switches language mid-conversation: preference updates, not stuck ----------
def test_customer_switch_language_mid_chat():
    reset_all()
    number = "628900000003"
    ai_reply_1 = "Halo Kak! Mau tanya soal apa nih, content atau AI admin?[SET_LANG: lang=id]"
    resp1 = send_customer_message(number, "halo kak mau tanya", ai_reply_1)
    assert resp1.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_ID

    ai_reply_2 = "Sure! We can definitely help with appointment booking too.[SET_LANG: lang=en]"
    resp2 = send_customer_message(number, "Actually can we continue in English please?", ai_reply_2)
    assert resp2.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_EN
    sent_texts = [t for n, t in sent_log if n == number]
    assert not any("[SET_LANG" in t for t in sent_texts), sent_texts
    print("test_customer_switch_language_mid_chat OK")


# ---------- 6. English meeting flow: [MEETING_PREFERENCE] logic untouched by language layer ----------
def test_english_meeting_flow():
    reset_all()
    number = "628900000004"
    appmod.customer_names[number] = "John"
    ai_reply = ("Got it, let me check the team's schedule for that "
                "day.[MEETING_PREFERENCE: mode=online|day=besok][SET_LANG: lang=en]")
    resp = send_customer_message(number, "Can we do an online meeting tomorrow?", ai_reply)
    assert resp.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_EN
    req = appmod.meeting_requests.get(number)
    assert req is not None, "meeting request should still be created regardless of language"
    assert req["status"] == appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION
    assert req["mode"] == "online"
    sent_texts = [t for n, t in sent_log if n == number]
    assert not any("[SET_LANG" in t or "[MEETING_PREFERENCE" in t for t in sent_texts), sent_texts
    print("test_english_meeting_flow OK")


# ---------- 7. English payment flow: [GIVE_PAYMENT_INFO] still injects real PAYMENT_CONFIG ----------
def test_english_payment_flow():
    reset_all()
    number = "628900000005"
    ai_reply = ("Sure! Here's our bank account for the transfer:[GIVE_PAYMENT_INFO][SET_LANG: lang=en]")
    resp = send_customer_message(number, "How do I pay for this?", ai_reply)
    assert resp.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_EN
    sent_texts = [t for n, t in sent_log if n == number]
    assert any(appmod.PAYMENT_CONFIG["account_number"] in t for t in sent_texts), sent_texts
    assert any(appmod.PAYMENT_CONFIG["account_name"] in t for t in sent_texts), sent_texts
    assert not any("[GIVE_PAYMENT_INFO" in t or "[SET_LANG" in t for t in sent_texts), sent_texts
    print("test_english_payment_flow OK")


# ---------- 8. English sales objection ("too expensive"): lead-stage & prompt logic unaffected ----------
def test_english_sales_objection():
    reset_all()
    number = "628900000006"
    ai_reply = ("I totally understand — let's look at it from the value it brings instead of just "
                "the price. It replaces a big chunk of manual chat handling.[SET_LANG: lang=en]")
    resp = send_customer_message(number, "Hmm that's kinda expensive tbh, not sure if it's worth it", ai_reply)
    assert resp.status_code == 200
    assert appmod.customer_language.get(number) == appmod.LANGUAGE_EN
    # objection-handling instructions in SYSTEM_PROMPT are language-agnostic and untouched
    assert "JANGAN langsung kasih diskon" in appmod.SYSTEM_PROMPT
    sent_texts = [t for n, t in sent_log if n == number]
    assert not any("[SET_LANG" in t for t in sent_texts), sent_texts
    print("test_english_sales_objection OK")


# ---------- 9. Ambiguous/no [SET_LANG] tag: no crash, no preference stored ----------
def test_no_set_lang_tag_does_not_crash():
    reset_all()
    number = "628900000007"
    ai_reply = "😀👍"
    resp = send_customer_message(number, "😀", ai_reply)
    assert resp.status_code == 200
    assert number not in appmod.customer_language
    print("test_no_set_lang_tag_does_not_crash OK")


# ---------- 10. strip_tags() removes [SET_LANG: ...] from any raw text ----------
def test_strip_tags_removes_set_lang():
    raw = "Some reply text.[SET_LANG: lang=en]"
    cleaned = appmod.strip_tags(raw)
    assert "[SET_LANG" not in cleaned
    assert "Some reply text." in cleaned
    print("test_strip_tags_removes_set_lang OK")


# ---------- 11. build_language_context reflects stored preference for next turn ----------
def test_build_language_context_reflects_stored_preference():
    reset_all()
    number = "628900000008"
    ctx_before = appmod.build_language_context(number)
    assert "belum ada preferensi" in ctx_before
    appmod.customer_language[number] = appmod.LANGUAGE_EN
    ctx_after = appmod.build_language_context(number)
    assert "English" in ctx_after
    print("test_build_language_context_reflects_stored_preference OK")


# ---------- 12. Regression guard: PAYMENT_CONFIG untouched; PRICING_CONFIG matches current
# approved structure (updated by the pre-launch hardening cycle that added AI Admin Basic/Pro) ----------
def test_pricing_config_and_payment_config_untouched():
    assert set(appmod.PRICING_CONFIG.keys()) == {
        "ai_admin", "content_packages", "static_visual_note", "bundles",
        "meta_ads", "ads_bundles", "website", "domain_hosting", "event",
        "transport_acara", "custom_automation_redirect",
    }
    assert appmod.PAYMENT_CONFIG == {
        "bank": "BCA", "account_number": "7610267551", "account_name": "Irvan Karnawi",
    }
    print("test_pricing_config_and_payment_config_untouched OK")


if __name__ == "__main__":
    test_system_prompt_contains_language_instructions()
    test_owner_prompt_untouched()
    test_full_english_customer()
    test_mixed_indonesian_english_customer()
    test_customer_switch_language_mid_chat()
    test_english_meeting_flow()
    test_english_payment_flow()
    test_english_sales_objection()
    test_no_set_lang_tag_does_not_crash()
    test_strip_tags_removes_set_lang()
    test_build_language_context_reflects_stored_preference()
    test_pricing_config_and_payment_config_untouched()
    print("ALL LANGUAGE LAYER TESTS PASSED")
