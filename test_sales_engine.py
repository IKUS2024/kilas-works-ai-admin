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
        msg_id = f"wamid.sales.{_msg_counter[0]}"
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id, "from": number, "type": "text", "text": {"body": text},
        }]}}]}]
    }


def send_customer_message(number, text, ai_reply):
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        return client.post("/webhook", data=json.dumps(customer_payload(number, text)), content_type="application/json")


# ---------- 1. Sales prompt contains the key consultative-flow instructions ----------
def test_sales_prompt_contains_key_instructions():
    p = appmod.SYSTEM_PROMPT
    assert "Understand" in p and "Diagnose" in p and "Recommend" in p and "Explain" in p
    assert "MAKSIMAL 1-2 pertanyaan" in p
    assert "1 rekomendasi" in p or "1 rekomendasi UTAMA" in p
    assert "JANGAN langsung kasih diskon" in p
    assert "fake urgency" in p
    assert "JANGAN bohong" in p
    assert "JANGAN otomatis upsell semua layanan" in p
    print("test_sales_prompt_contains_key_instructions OK")


# ---------- 2. Lead stage: COLD by default, WARM once it's not the first message ----------
def test_lead_stage_cold_then_warm():
    reset_all()
    number = "628800000001"
    assert appmod.lead_stage.get(number) is None  # belum ada history sama sekali

    r1 = send_customer_message(number, "halo", "Halo Kak, ada yang bisa aku bantu soal content, AI Admin, website, atau ads?")
    assert r1.status_code == 200
    # customer PERTAMA kali chat & belum ada sinyal HOT/CLOSING -> belum ke-bump sama sekali (tetap COLD secara default)
    stage_after_first = appmod.lead_stage.get(number)
    assert stage_after_first is None or stage_after_first["stage"] == appmod.LEAD_STAGE_COLD, stage_after_first

    # call_claude di-mock (gak beneran nulis ke `conversations`), jadi simulasikan manual history-nya
    # udah kesimpen dari pesan pertama tadi -> pesan KEDUA ini bukan lagi "customer baru".
    appmod.conversations[number] = [{"role": "user", "content": "halo"}]

    r2 = send_customer_message(number, "aku punya cafe baru", "Oke, sekarang yang paling pengen dibantu bagian konten, iklan, website, atau chat customer-nya dulu Kak?")
    assert r2.status_code == 200
    stage2 = appmod.lead_stage.get(number)
    assert stage2["stage"] == appmod.LEAD_STAGE_WARM, stage2
    print("test_lead_stage_cold_then_warm OK")


# ---------- 3. Lead stage HOT saat minta katalog / meeting / DP-unclear, owner dinotify SEKALI ----------
def test_lead_stage_hot_notifies_owner_once():
    reset_all()
    number = "628800000002"
    global sent_log
    sent_log = []
    send_customer_message(number, "halo", "Halo kak")  # COLD dulu
    r = send_customer_message(number, "boleh minta katalog?", "Nih kak.[KIRIM_KATALOG]")
    assert r.status_code == 200
    stage = appmod.lead_stage[number]
    assert stage["stage"] == appmod.LEAD_STAGE_HOT, stage
    assert stage["notified_hot"] is True
    hot_notifs = [t for to, t in sent_log if to == appmod.OWNER_WHATSAPP_NUMBER and "HOT" in t]
    assert len(hot_notifs) == 1, hot_notifs

    # pesan HOT lagi -> TIDAK notify owner kedua kalinya (anti-spam)
    send_customer_message(number, "boleh minta katalog lagi?", "Nih kak.[KIRIM_KATALOG]")
    hot_notifs2 = [t for to, t in sent_log if to == appmod.OWNER_WHATSAPP_NUMBER and "HOT" in t]
    assert len(hot_notifs2) == 1, "gak boleh notify HOT dua kali (anti-spam)"
    print("test_lead_stage_hot_notifies_owner_once OK")


# ---------- 4. LEADS_PANAS gak bikin notify HOT dobel (udah ada notify sendiri) ----------
def test_leads_panas_does_not_double_notify():
    reset_all()
    number = "628800000003"
    global sent_log
    sent_log = []
    r = send_customer_message(number, "aku udah yakin mau lanjut nih", "Oke siap kak, aku catet ya.[LEADS_PANAS]")
    assert r.status_code == 200
    owner_msgs = [t for to, t in sent_log if to == appmod.OWNER_WHATSAPP_NUMBER]
    leads_panas_msgs = [t for t in owner_msgs if "LEADS PANAS" in t]
    hot_msgs = [t for t in owner_msgs if "Lead HOT" in t]
    assert len(leads_panas_msgs) == 1
    assert len(hot_msgs) == 0, "LEADS_PANAS udah cukup, jangan double notify Lead HOT juga"
    stage = appmod.lead_stage[number]
    assert stage["stage"] == appmod.LEAD_STAGE_HOT
    assert stage["notified_hot"] is True
    print("test_leads_panas_does_not_double_notify OK")


# ---------- 5. Lead stage CLOSING saat [GIVE_PAYMENT_INFO], owner dinotify sekali ----------
def test_lead_stage_closing_on_give_payment_info():
    reset_all()
    number = "628800000004"
    global sent_log
    sent_log = []
    ai_reply = "Oke ini ringkasannya kak.[GIVE_PAYMENT_INFO]Abis transfer kirim bukti ya."
    r = send_customer_message(number, "aku mau bayar full", ai_reply)
    assert r.status_code == 200
    stage = appmod.lead_stage[number]
    assert stage["stage"] == appmod.LEAD_STAGE_CLOSING, stage
    assert stage["notified_closing"] is True
    closing_msgs = [t for to, t in sent_log if to == appmod.OWNER_WHATSAPP_NUMBER and "CLOSING" in t]
    assert len(closing_msgs) == 1, closing_msgs
    print("test_lead_stage_closing_on_give_payment_info OK")


# ---------- 6. Stage gak pernah turun otomatis ----------
def test_lead_stage_never_downgrades():
    reset_all()
    number = "628800000005"
    appmod.bump_lead_stage(number, appmod.LEAD_STAGE_HOT)
    send_customer_message(number, "makasih ya", "Sama-sama kak")
    stage = appmod.lead_stage[number]
    assert stage["stage"] == appmod.LEAD_STAGE_HOT, "stage TIDAK BOLEH turun ke WARM/COLD otomatis"
    print("test_lead_stage_never_downgrades OK")


# ---------- 7. Objection "mahal" -> prompt tidak instruksikan diskon otomatis, tone tetap sopan ----------
def test_price_objection_no_auto_discount_instruction():
    p = appmod.SYSTEM_PROMPT
    assert "mahal" in p.lower()
    assert "JANGAN langsung kasih diskon" in p
    assert "JANGAN PERNAH kasih diskon sendiri tanpa izin" in p or "tanpa izin/instruksi eksplisit dari owner" in p
    print("test_price_objection_no_auto_discount_instruction OK")


# ---------- 8. Follow-up nudge instruction wajib kontekstual, larang generic "masih tertarik?" ----------
def test_followup_nudge_is_contextual_not_generic():
    reset_all()
    number = "628800000006"
    appmod.customer_names[number] = "Yutha"
    appmod.followup_state[number] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=13),
        "last_followup_at": None, "followup_count": 0, "converted": False,
    }
    captured = {}

    def fake_call_claude(num, text, memory_override=None):
        captured["instruction"] = text
        return "Halo Kak Yutha, kemarin sempat tanya soal Content Growth, ada yang mau dibandingin lagi?"

    with patch.object(appmod, "call_claude", side_effect=fake_call_claude), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles):
        r = client.get(f"/cron/followups?key={appmod.CRON_SECRET}")
    assert r.status_code == 200
    assert "masih tertarik" not in captured["instruction"].lower() or "JANGAN generic" in captured["instruction"]
    assert "sebut ULANG" in captured["instruction"] or "topik/paket/kebutuhan SPESIFIK" in captured["instruction"]
    print("test_followup_nudge_is_contextual_not_generic OK")


# ---------- 9. Bundle/paket: PRICING_CONFIG cocok sama struktur final yang disetujui (pre-launch
# hardening menambahkan AI Admin Basic/Pro + bundle turunannya secara EKSPLISIT diminta user — jadi
# guard ini sekarang mengunci struktur BARU itu, bukan lagi struktur lama sebelum AI Admin Basic ada) ----------
def test_no_new_bundle_or_package_added():
    expected_top_keys = {
        "ai_admin", "content_packages", "static_visual_note", "bundles", "meta_ads",
        "ads_bundles", "website", "domain_hosting", "event", "transport_acara", "custom_automation_redirect",
    }
    assert set(appmod.PRICING_CONFIG.keys()) == expected_top_keys, appmod.PRICING_CONFIG.keys()
    assert set(appmod.PRICING_CONFIG["ai_admin"].keys()) == {"basic", "pro"}
    assert set(appmod.PRICING_CONFIG["bundles"].keys()) == {"growth_ai_basic", "growth_ai", "pro_ai"}
    assert set(appmod.PRICING_CONFIG["ads_bundles"].keys()) == {
        "ai_basic_ads", "ai_ads", "growth_ai_ads", "pro_ai_ads", "ads_landing_page", "ad_spend_note",
    }
    print("test_no_new_bundle_or_package_added OK")


# ---------- 10. Tone tetap gak boleh gw/gue/lu/lo di seluruh sales prompt baru ----------
INFORMAL_PATTERN = re.compile(r"\b(gw|gue|lu|lo)\b", re.IGNORECASE)


def test_sales_prompt_has_no_informal_pronouns():
    assert not INFORMAL_PATTERN.search(appmod.SYSTEM_PROMPT), "sales prompt gak boleh ngandung gw/gue/lu/lo"
    print("test_sales_prompt_has_no_informal_pronouns OK")


# ---------- 11. Typo/informal customer text tetap diproses normal (webhook gak error) ----------
def test_typo_messages_still_processed_without_error():
    reset_all()
    number = "628800000007"
    typo_msgs = ["brp hrg growth sm ads", "bs bantu pket apa aja", "mw tanya2 dulu", "gmn caranya mulai"]
    for i, msg in enumerate(typo_msgs):
        r = send_customer_message(number, msg, "Oke kak, boleh cerita dikit soal bisnisnya?")
        assert r.status_code == 200
    print("test_typo_messages_still_processed_without_error OK")


# ---------- 12. Follow-up guard existing TETAP berlaku (protected feature) ----------
def test_followup_guard_still_skips_active_processes():
    reset_all()
    n1 = "628800000008"
    appmod.followup_state[n1] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=13),
        "last_followup_at": None, "followup_count": 0, "converted": False,
    }
    appmod.meeting_requests[n1] = {"status": appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION}
    due = appmod.get_customers_due_for_followup()
    assert n1 not in due
    print("test_followup_guard_still_skips_active_processes OK")


# ---------- 13. PRODUCTION MICRO-FIX — Meta error 131047, 8h gap / 23h safety / max 2 attempts ----------
def test_followup_allowed_at_8h_gap():
    reset_all()
    n = "628800000020"
    appmod.followup_state[n] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=8, minutes=1),
        "last_followup_at": None, "followup_count": 0, "converted": False,
    }
    assert n in appmod.get_customers_due_for_followup()
    print("test_followup_allowed_at_8h_gap OK")


def test_followup_not_yet_due_before_8h():
    reset_all()
    n = "628800000021"
    appmod.followup_state[n] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=5),
        "last_followup_at": None, "followup_count": 0, "converted": False,
    }
    assert n not in appmod.get_customers_due_for_followup()
    print("test_followup_not_yet_due_before_8h OK")


def test_second_followup_allowed_while_still_under_23h():
    reset_all()
    n = "628800000022"
    appmod.followup_state[n] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=20),
        "last_followup_at": appmod._utcnow() - appmod.timedelta(hours=9),
        "followup_count": 1, "converted": False,
    }
    assert n in appmod.get_customers_due_for_followup()
    print("test_second_followup_allowed_while_still_under_23h OK")


def test_followup_skipped_at_23h_or_more_since_customer_message():
    reset_all()
    n = "628800000023"
    appmod.followup_state[n] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=23),
        "last_followup_at": None, "followup_count": 0, "converted": False,
    }
    assert n not in appmod.get_customers_due_for_followup(), \
        "must NEVER attempt a free-text follow-up at/beyond the 23h WhatsApp safety boundary"
    print("test_followup_skipped_at_23h_or_more_since_customer_message OK")


def test_followup_max_attempts_is_2():
    reset_all()
    assert appmod.MAX_AUTO_FOLLOWUPS == 2
    n = "628800000024"
    appmod.followup_state[n] = {
        "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=9),
        "last_followup_at": appmod._utcnow() - appmod.timedelta(hours=9),
        "followup_count": 2, "converted": False,
    }
    assert n not in appmod.get_customers_due_for_followup(), "must stop after 2 attempts"
    print("test_followup_max_attempts_is_2 OK")


if __name__ == "__main__":
    test_sales_prompt_contains_key_instructions()
    test_lead_stage_cold_then_warm()
    test_lead_stage_hot_notifies_owner_once()
    test_leads_panas_does_not_double_notify()
    test_lead_stage_closing_on_give_payment_info()
    test_lead_stage_never_downgrades()
    test_price_objection_no_auto_discount_instruction()
    test_followup_nudge_is_contextual_not_generic()
    test_no_new_bundle_or_package_added()
    test_sales_prompt_has_no_informal_pronouns()
    test_typo_messages_still_processed_without_error()
    test_followup_guard_still_skips_active_processes()
    test_followup_allowed_at_8h_gap()
    test_followup_not_yet_due_before_8h()
    test_second_followup_allowed_while_still_under_23h()
    test_followup_skipped_at_23h_or_more_since_customer_message()
    test_followup_max_attempts_is_2()
    print("ALL SALES ENGINE TESTS PASSED")
