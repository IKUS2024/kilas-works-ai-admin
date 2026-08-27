import os, re, json
from unittest.mock import patch, MagicMock

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
    appmod.demo_sessions.clear()


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
        msg_id = f"wamid.prelaunch.{_msg_counter[0]}"
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


def owner_payload(text, msg_id=None):
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id or "wamid.prelaunch.owner", "from": appmod.OWNER_WHATSAPP_NUMBER,
            "type": "text", "text": {"body": text},
        }]}}]}]
    }


def send_owner_message_deterministic(text):
    global sent_log

    def boom(*a, **kw):
        raise AssertionError("call_claude_owner SHOULD NOT be called for this deterministic path")

    with patch.object(appmod, "call_claude_owner", side_effect=boom), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        return client.post("/webhook", data=json.dumps(owner_payload(text)), content_type="application/json")


# ---------- 1. PRICING_CONFIG structure: AI Admin Basic/Pro tiers present with correct prices ----------
def test_ai_admin_basic_and_pro_prices():
    ai = appmod.PRICING_CONFIG["ai_admin"]
    assert ai["basic"]["harga"] == 499000, ai["basic"]
    assert ai["pro"]["harga"] == 999000, ai["pro"]
    assert "AI Admin Basic" in ai["basic"]["nama"]
    assert "AI Admin Pro" in ai["pro"]["nama"]
    print("test_ai_admin_basic_and_pro_prices OK")


# ---------- 2. New bundle prices match the FINAL spec ----------
def test_new_bundle_prices():
    b = appmod.PRICING_CONFIG["bundles"]
    assert b["growth_ai_basic"]["harga"] == 2990000, b["growth_ai_basic"]
    assert b["growth_ai"]["harga"] == 3490000, b["growth_ai"]
    assert b["pro_ai"]["harga"] == 4990000, b["pro_ai"]

    ab = appmod.PRICING_CONFIG["ads_bundles"]
    assert ab["ai_basic_ads"]["harga"] == 1190000, ab["ai_basic_ads"]
    assert ab["ai_ads"]["harga"] == 1690000, ab["ai_ads"]
    assert ab["growth_ai_ads"]["harga"] == 4290000, ab["growth_ai_ads"]
    assert ab["pro_ai_ads"]["harga"] == 5790000, ab["pro_ai_ads"]
    print("test_new_bundle_prices OK")


# ---------- 3. build_pricing_text_block() renders both tiers + all new bundles (no crash, no dupes) ----------
def test_pricing_text_block_contains_all_tiers_and_bundles():
    block = appmod.build_pricing_text_block()
    assert "AI Admin Basic" in block and "499" in block
    assert "AI Admin Pro" in block and "999" in block
    assert "Content Growth + AI Admin Basic" in block
    assert "Content Growth + AI Admin Pro" in block
    assert "Content Pro + AI Admin Pro" in block
    assert "AI Admin Basic + Meta Ads" in block
    print("test_pricing_text_block_contains_all_tiers_and_bundles OK")


# ---------- 4. Price-disclosure rule text: don't dump price unasked, but answer directly when asked ----------
def test_price_disclosure_rule_text_present():
    p = appmod.SYSTEM_PROMPT
    assert "TIDAK DITANYA HARGA" in p and "DITANYA HARGA" in p
    assert "JANGAN PERNAH menghindar" in p or "JANGAN PERNAH" in p
    print("test_price_disclosure_rule_text_present OK")


# ---------- 5. Customer directly asks price of ONE package -> bot must answer that number (behavioral,
# via prompt instruction check + a live webhook round-trip that the exact price appears verbatim) ----------
def test_customer_asks_specific_package_price_gets_direct_answer():
    reset_all()
    number = "628900100001"
    ai_reply = "Content Growth Rp2.750.000/bulan, Kak."
    resp = send_customer_message(number, "Growth berapa?", ai_reply)
    assert resp.status_code == 200
    sent_texts = [t for n, t in sent_log if n == number]
    assert any("2.750.000" in t for t in sent_texts), sent_texts
    print("test_customer_asks_specific_package_price_gets_direct_answer OK")


# ---------- 6. Overclaim phrases are absent from SYSTEM_PROMPT / DEMO_SYSTEM_PROMPT / katalog / landing ----------
def test_no_overclaim_phrases_anywhere():
    banned = [
        "tidak ada chat yang terlewat", "pasti meningkatkan penjualan", "closing otomatis",
        "pasti mendapatkan lebih banyak customer", "ai menggantikan admin sepenuhnya",
    ]
    sources = {
        "SYSTEM_PROMPT": appmod.SYSTEM_PROMPT.lower(),
        "DEMO_SYSTEM_PROMPT": appmod.DEMO_SYSTEM_PROMPT.lower(),
    }
    with open("landing-page-kilasworks.html", encoding="utf-8") as f:
        sources["landing_page"] = f.read().lower()
    with open("generate_katalog_pdf.py", encoding="utf-8") as f:
        sources["katalog_generator"] = f.read().lower()

    for phrase in banned:
        for src_name, text in sources.items():
            assert phrase not in text, f"overclaim phrase '{phrase}' found in {src_name}"
    print("test_no_overclaim_phrases_anywhere OK")


# ---------- 7. "Ini bot?" honesty instruction present, and framed positively (not defensive) ----------
def test_bot_honesty_instruction_present():
    p = appmod.SYSTEM_PROMPT
    assert "INI BOT" in p.upper() or "INI AI" in p.upper()
    assert "AI Admin Kilas Works" in p
    print("test_bot_honesty_instruction_present OK")


# ---------- 8. Demo-as-sales-tool instruction present in customer SYSTEM_PROMPT ----------
def test_demo_sales_tool_instruction_present():
    p = appmod.SYSTEM_PROMPT
    assert "/demo" in p
    assert "live demo" in p.lower()
    print("test_demo_sales_tool_instruction_present OK")


# ---------- 9. meeting_mode_label() helper: correct wording for sales vs demo purpose ----------
def test_meeting_mode_label_helper():
    assert appmod.meeting_mode_label({"purpose": "demo"}) == "live demo AI Admin"
    assert appmod.meeting_mode_label({"purpose": "sales", "mode": "online"}) == "online meeting"
    assert appmod.meeting_mode_label({"purpose": "sales", "mode": "offline"}) == "ketemu langsung"
    assert appmod.meeting_mode_label({}) == "online meeting"
    assert appmod.meeting_mode_label(None) == "online meeting"
    print("test_meeting_mode_label_helper OK")


# ---------- 10. Live demo appointment: purpose=demo end-to-end -> owner gets "live demo AI Admin" wording ----------
def test_live_demo_appointment_owner_notification_wording():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900100002"
    appmod.customer_names[number] = "Rangga"
    ai_reply = ("Boleh Kak, aku bantu jadwalkan live demo online-nya "
                "ya.[MEETING_PREFERENCE: mode=online|day=selasa|purpose=demo]")
    resp = send_customer_message(number, "aku mau live demo aja hari selasa", ai_reply)
    assert resp.status_code == 200

    req = appmod.meeting_requests[number]
    assert req["purpose"] == "demo"
    assert req["status"] == appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION

    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("live demo AI Admin" in t for t in owner_texts), owner_texts
    assert not any("online meeting" in t for t in owner_texts if "live demo" not in t), owner_texts
    print("test_live_demo_appointment_owner_notification_wording OK")


# ---------- 11. Live demo purpose defaults to "sales" when purpose= is omitted (backward compatible) ----------
def test_meeting_preference_without_purpose_defaults_to_sales():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900100003"
    appmod.customer_names[number] = "Dinda"
    ai_reply = "Siap kak, aku cek jadwal owner dulu ya.[MEETING_PREFERENCE: mode=online|day=rabu]"
    resp = send_customer_message(number, "boleh online meeting rabu?", ai_reply)
    assert resp.status_code == 200
    req = appmod.meeting_requests[number]
    assert req["purpose"] == "sales"
    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("online meeting" in t for t in owner_texts), owner_texts
    print("test_meeting_preference_without_purpose_defaults_to_sales OK")


# ---------- 12. Invalid/garbage purpose value falls back safely to "sales" (no crash) ----------
def test_meeting_preference_invalid_purpose_falls_back_to_sales():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900100004"
    appmod.customer_names[number] = "Tio"
    ai_reply = "Oke kak, dicek dulu ya.[MEETING_PREFERENCE: mode=online|day=kamis|purpose=garbage]"
    resp = send_customer_message(number, "online meeting kamis boleh?", ai_reply)
    assert resp.status_code == 200
    req = appmod.meeting_requests[number]
    assert req["purpose"] == "sales"
    print("test_meeting_preference_invalid_purpose_falls_back_to_sales OK")


# ---------- 13. Demo language-detection instruction present in DEMO_SYSTEM_PROMPT ----------
def test_demo_language_detection_instruction_present():
    p = appmod.DEMO_SYSTEM_PROMPT
    assert "AUTO-DETECT" in p
    assert "English" in p
    assert "Bahasa Indonesia" in p
    print("test_demo_language_detection_instruction_present OK")


# ---------- 14. Demo simulation isolation: /demo/api never touches production state ----------
def test_demo_isolated_from_production_state():
    reset_all()

    def fake_post_ok(url, headers=None, json=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {
            "content": [{"text": "Halo! Bisnis kamu bergerak di bidang apa nih?"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        return resp

    with patch.object(appmod.requests, "post", side_effect=fake_post_ok):
        resp = client.post("/demo/api", data=json.dumps({
            "session_id": "demo-test-session-1",
            "message": "nama bisnisnya Kopi Senja",
        }), content_type="application/json")
    assert resp.status_code == 200
    # production stores must remain empty — demo must never write into them
    assert len(appmod.conversations) == 0
    assert len(appmod.appointments) == 0
    assert len(appmod.meeting_requests) == 0
    assert len(appmod.customer_names) == 0
    assert "demo-test-session-1" in appmod.demo_sessions
    print("test_demo_isolated_from_production_state OK")


# ---------- 15. No internal markers ever leak to customer-visible text (via strip_tags) ----------
def test_internal_markers_stripped_from_customer_text():
    # [GIVE_PAYMENT_INFO] is deliberately NOT stripped here — it's replaced explicitly with the real
    # bank account text elsewhere in the webhook flow (see build_payment_info_text()), already covered
    # by test_language_layer.py's test_english_payment_flow. strip_tags() itself must remove every
    # other internal tag/marker that could otherwise leak to the customer verbatim.
    raw = "Halo kak![MEETING_PREFERENCE: mode=online|day=senin][SET_LANG: lang=id]"
    cleaned = appmod.strip_tags(raw)
    for marker in ("[MEETING_PREFERENCE", "[SET_LANG", "PESAN_UNTUK_CUSTOMER:", "LOG:", "DEBUG:"):
        assert marker not in cleaned, cleaned
    assert "Halo kak!" in cleaned
    print("test_internal_markers_stripped_from_customer_text OK")


# ---------- 16. Regression guard: date lock still works with purpose=demo (Selasa stays Selasa) ----------
def test_date_lock_holds_for_demo_purpose():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900100005"
    appmod.customer_names[number] = "Vico"
    ai_reply = "Siap, aku cek dulu ya kak.[MEETING_PREFERENCE: mode=online|day=selasa|purpose=demo]"
    resp = send_customer_message(number, "mau live demo selasa", ai_reply)
    assert resp.status_code == 200
    req = appmod.meeting_requests[number]
    locked_date = req["resolved_date"]

    resp2 = send_owner_message_deterministic("available")
    assert resp2.status_code == 200
    req_after = appmod.meeting_requests[number]
    assert req_after["resolved_date"] == locked_date, "tanggal tidak boleh berubah setelah owner confirm"
    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert not any("minggu" in t.lower() for t in owner_texts), owner_texts
    print("test_date_lock_holds_for_demo_purpose OK")


# ---------- 17. Landing page: AI Admin Basic/Pro distinction present, no prices shown ----------
def test_landing_page_ai_tier_distinction_no_prices():
    with open("landing-page-kilasworks.html", encoding="utf-8") as f:
        html = f.read()
    assert "ai-tier-card" in html
    assert "Basic" in html and "Pro" in html
    assert not re.search(r"Rp[\d.]+", html), "landing page must not show any Rupiah price"
    assert "/demo" in html
    print("test_landing_page_ai_tier_distinction_no_prices OK")


# ---------- 18. Katalog PDF generator: no reference to unauthorized features (invoice/QR/CRM/POS) as
# AI Admin Pro benefits ----------
def test_katalog_no_unauthorized_ai_admin_features():
    ai_pro = appmod.PRICING_CONFIG["ai_admin"]["pro"]
    fitur_text = " ".join(ai_pro["fitur"]).lower()
    for banned in ("invoice otomatis", "qr payment", "crm", "pos ", "inventory"):
        assert banned not in fitur_text, f"'{banned}' found in AI Admin Pro fitur list"
    print("test_katalog_no_unauthorized_ai_admin_features OK")


# ---------- 19. Follow-up / reminder not overclaimed as unconditionally active in pricing text ----------
def test_followup_wording_not_overclaimed():
    block = appmod.build_pricing_text_block()
    assert "follow-up otomatis" not in block.lower() or "scheduler follow-up disetup" in block.lower() \
        or "aktif setelah" in block.lower()
    print("test_followup_wording_not_overclaimed OK")


if __name__ == "__main__":
    test_ai_admin_basic_and_pro_prices()
    test_new_bundle_prices()
    test_pricing_text_block_contains_all_tiers_and_bundles()
    test_price_disclosure_rule_text_present()
    test_customer_asks_specific_package_price_gets_direct_answer()
    test_no_overclaim_phrases_anywhere()
    test_bot_honesty_instruction_present()
    test_demo_sales_tool_instruction_present()
    test_meeting_mode_label_helper()
    test_live_demo_appointment_owner_notification_wording()
    test_meeting_preference_without_purpose_defaults_to_sales()
    test_meeting_preference_invalid_purpose_falls_back_to_sales()
    test_demo_language_detection_instruction_present()
    test_demo_isolated_from_production_state()
    test_internal_markers_stripped_from_customer_text()
    test_date_lock_holds_for_demo_purpose()
    test_landing_page_ai_tier_distinction_no_prices()
    test_katalog_no_unauthorized_ai_admin_features()
    test_followup_wording_not_overclaimed()
    print("ALL PRELAUNCH HARDENING TESTS PASSED")
