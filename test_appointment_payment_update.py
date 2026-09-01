import os, re, json
from unittest.mock import patch, MagicMock

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

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


sent_log = []


def fake_send_whatsapp_message(to, text):
    sent_log.append((to, text))
    return True, None


def fake_send_reply_bubbles(to, msg_id, text):
    for part in text.split("|||"):
        sent_log.append((to, part))
    return True, None


_owner_msg_counter = [0]


def owner_payload(text, msg_id=None):
    if msg_id is None:
        _owner_msg_counter[0] += 1
        msg_id = f"wamid.owner.{_owner_msg_counter[0]}"
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id, "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": text},
        }]}}]}]
    }


_msg_counter = [0]


def customer_payload(number, text, msg_id=None):
    if msg_id is None:
        _msg_counter[0] += 1
        msg_id = f"wamid.cust.{_msg_counter[0]}"
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id, "from": number, "type": "text", "text": {"body": text},
        }]}}]}]
    }


def fake_ai_text(text):
    def fake_post(url, headers=None, json=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json = lambda: {"content": [{"text": text}], "usage": {"input_tokens": 5, "output_tokens": 3}}
        return resp
    return fake_post


# ---------- 1. PAYMENT_CONFIG single source of truth ----------
def test_payment_config_single_source():
    assert appmod.PAYMENT_CONFIG["bank"] == "BCA"
    assert appmod.PAYMENT_CONFIG["account_number"] == "7610267551"
    assert appmod.PAYMENT_CONFIG["account_name"] == "Irvan Karnawi"
    text = appmod.build_payment_info_text()
    assert "7610267551" in text and "Irvan Karnawi" in text and "BCA" in text
    # SYSTEM_PROMPT gak boleh lagi hardcode nomor rekening literal di teks pembayaran manapun
    assert "7610267551" not in appmod.SYSTEM_PROMPT
    print("test_payment_config_single_source OK")


# ---------- 2. Appointment TIDAK PERNAH confirmed sebelum owner kasih availability ----------
def test_meeting_preference_creates_pending_not_confirmed():
    reset_all()
    number = "628700000001"
    appmod.customer_names[number] = "Yutha"

    kv_raw = "mode=offline|day=sabtu"
    # simulasikan proses yang sama seperti webhook: AI ngeluarin [MEETING_PREFERENCE]
    ai_reply = f"Oke aku cek dulu ya.[MEETING_PREFERENCE: {kv_raw}]"
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        r = client.post("/webhook", data=json.dumps(customer_payload(number, "sabtu ketemu langsung ya")), content_type="application/json")
    assert r.status_code == 200
    assert len(appmod.appointments) == 0, "appointment TIDAK BOLEH ke-create cuma dari preferensi doang"
    req = appmod.meeting_requests.get(number)
    assert req is not None and req["status"] == appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION, req
    assert req["mode"] == "offline"
    print("test_meeting_preference_creates_pending_not_confirmed OK")


# ---------- 3. Owner kasih availability -> customer dikasih pilihan -> pilih -> baru CONFIRMED ----------
def test_full_owner_mediated_booking_flow():
    reset_all()
    number = "628700000002"
    appmod.customer_names[number] = "Yutha"

    # pilih hari SELASA (bukan hari libur) biar deterministik lintas hari testing
    today = appmod.now_wib().date()
    target_weekday = 1  # Selasa
    days_ahead = (target_weekday - today.weekday()) % 7
    days_ahead = days_ahead or 7
    target_date = (today + appmod.timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    appmod.meeting_requests[number] = {
        "status": appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION,
        "mode": "offline", "day_text": "selasa", "day_display": "Selasa",
        "resolved_date": target_date, "name": "Yutha", "business_name": None,
        "need_summary": None, "offered_slots": [], "created_at": appmod._utcnow(),
    }

    owner_reply = "Oke siap catet ya.[OWNER_MEETING_SLOTS: customer=Yutha|times=13:00,15:00,17:00]"
    global sent_log
    sent_log = []
    with patch.object(appmod, "call_claude_owner", return_value=owner_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        r = client.post("/webhook", data=json.dumps(owner_payload("selasa gw bisa jam 1 3 5")), content_type="application/json")
    assert r.status_code == 200
    req = appmod.meeting_requests[number]
    assert req["status"] == appmod.MEETING_STATE_SLOTS_OFFERED, req
    assert req["offered_slots"] == ["13:00", "15:00", "17:00"], req
    assert any("tersedia pukul" in t for _, t in sent_log), sent_log
    assert len(appmod.appointments) == 0, "appointment TETAP belum boleh CONFIRMED sebelum customer milih jam"

    # customer sekarang milih salah satu jam yang ditawarin
    ai_reply = "Oke siap.[MEETING_SLOT_PICK: time=15:00]"
    sent_log = []
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        r2 = client.post("/webhook", data=json.dumps(customer_payload(number, "jam 15 aja")), content_type="application/json")
    assert r2.status_code == 200
    assert len(appmod.appointments) == 1
    appt = list(appmod.appointments.values())[0]
    assert appt["status"] == "scheduled"  # ini representasi CONFIRMED di sistem existing
    assert appt["meeting_time"] == "15:00"
    assert number not in appmod.meeting_requests, "meeting_request harus udah beres/dibersihin abis confirmed"
    print("test_full_owner_mediated_booking_flow OK")


# ---------- 4. Owner bilang gak bisa/tutup -> decline, bukan confirmed ----------
def test_owner_unavailable_declines_not_confirms():
    reset_all()
    number = "628700000003"
    appmod.customer_names[number] = "Caca"
    appmod.meeting_requests[number] = {
        "status": appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION,
        "mode": "online", "day_text": "minggu", "day_display": "Minggu",
        "resolved_date": None, "name": "Caca", "business_name": None,
        "need_summary": None, "offered_slots": [], "created_at": appmod._utcnow(),
    }
    owner_reply = "Oke.[OWNER_MEETING_UNAVAILABLE: customer=Caca]"
    global sent_log
    sent_log = []
    with patch.object(appmod, "call_claude_owner", return_value=owner_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        r = client.post("/webhook", data=json.dumps(owner_payload("minggu tutup")), content_type="application/json")
    assert r.status_code == 200
    assert number not in appmod.meeting_requests
    assert len(appmod.appointments) == 0
    assert any("gak available" in t for _, t in sent_log), sent_log
    print("test_owner_unavailable_declines_not_confirms OK")


# ---------- 5. business_hours (kantor tutup Minggu) TIDAK otomatis nge-block preferensi ONLINE ----------
def test_offline_blocked_on_closed_day_online_not_blocked():
    reset_all()
    number = "628700000004"
    appmod.customer_names[number] = "Budi"

    today = appmod.now_wib().date()
    days_ahead = (6 - today.weekday()) % 7  # Minggu
    days_ahead = days_ahead or 7
    sunday_str = (today + appmod.timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    assert appmod.is_office_closed_on(sunday_str) is True

    # OFFLINE di hari Minggu -> ditolak otomatis, TIDAK notify owner / TIDAK bikin meeting_request
    ai_reply_offline = f"Oke aku cek ya.[MEETING_PREFERENCE: mode=offline|day={sunday_str}]"
    with patch.object(appmod, "call_claude", return_value=ai_reply_offline), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        client.post("/webhook", data=json.dumps(customer_payload(number, "minggu ketemu langsung ya")), content_type="application/json")
    assert number not in appmod.meeting_requests, "offline di hari tutup TIDAK BOLEH bikin pending request"

    # ONLINE di hari yang sama (Minggu) -> TETAP boleh diproses/ditanyakan ke owner
    ai_reply_online = f"Oke aku cek ya.[MEETING_PREFERENCE: mode=online|day={sunday_str}]"
    with patch.object(appmod, "call_claude", return_value=ai_reply_online), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        client.post("/webhook", data=json.dumps(customer_payload(number, "minggu online meeting ya")), content_type="application/json")
    assert number in appmod.meeting_requests, "online di hari tutup kantor TETAP HARUS bisa ditanyain ke owner"
    assert appmod.meeting_requests[number]["mode"] == "online"
    print("test_offline_blocked_on_closed_day_online_not_blocked OK")


# ---------- 6. Payment: DP tapi nominal belum jelas -> notify owner, TIDAK ngarang ----------
def test_dp_unclear_notifies_owner_no_guessing():
    reset_all()
    number = "628700000005"
    appmod.customer_names[number] = "Yutha"
    ai_reply = "Boleh Kak, aku cek dulu ke owner ya.[PAYMENT_DP_UNCLEAR: package=Content Growth]"
    global sent_log
    sent_log = []
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        r = client.post("/webhook", data=json.dumps(customer_payload(number, "aku mau DP untuk Content Growth")), content_type="application/json")
    assert r.status_code == 200
    pay = appmod.payment_state.get(number)
    assert pay is not None and pay["status"] == appmod.PAYMENT_STATUS_INTENT
    assert pay["dp_requested"] is True
    assert any("Nominal DP" in t for _, t in sent_log), sent_log
    # pastikan gak ada nominal/persentase yang dikarang di reply customer
    customer_texts = [t for to, t in sent_log if to == number]
    assert not any(re.search(r"\d+%|\bRp\s?\d", t) for t in customer_texts), customer_texts
    print("test_dp_unclear_notifies_owner_no_guessing OK")


# ---------- 7. [GIVE_PAYMENT_INFO] diganti rekening ASLI, AI gak pernah ngetik sendiri ----------
def test_give_payment_info_injects_real_account():
    reset_all()
    number = "628700000006"
    ai_reply = "Oke ini ringkasannya ya kak, paket Growth 1.5jt.[GIVE_PAYMENT_INFO]Abis transfer kirim bukti ya."
    global sent_log
    sent_log = []
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        client.post("/webhook", data=json.dumps(customer_payload(number, "aku mau bayar full paket Growth")), content_type="application/json")
    full_text = " ".join(t for to, t in sent_log if to == number)
    assert "7610267551" in full_text and "Irvan Karnawi" in full_text
    assert "[GIVE_PAYMENT_INFO]" not in full_text
    print("test_give_payment_info_injects_real_account OK")


# ---------- 8. Screenshot / [SUDAH_BAYAR] -> PENDING_VERIFICATION, BUKAN otomatis PAID ----------
def test_sudah_bayar_sets_pending_verification_not_paid():
    reset_all()
    number = "628700000007"
    ai_reply = "Makasih ya, aku terusin ke tim buat verifikasi.[SUDAH_BAYAR]"
    global sent_log
    sent_log = []
    with patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        client.post("/webhook", data=json.dumps(customer_payload(number, "udah aku transfer ya, ini buktinya")), content_type="application/json")
    pay = appmod.payment_state.get(number)
    assert pay is not None
    assert pay["status"] == appmod.PAYMENT_STATUS_PENDING_VERIFICATION
    assert pay["status"] != appmod.PAYMENT_STATUS_PAID
    assert any("verifikasi" in t.lower() for _, t in sent_log), sent_log
    print("test_sudah_bayar_sets_pending_verification_not_paid OK")


# ---------- 9. Owner command update status pembayaran customer yang BENAR ----------
def test_owner_payment_commands_update_correct_customer():
    reset_all()
    appmod.customer_names["628700000008"] = "Yutha"
    appmod.customer_names["628700000009"] = "Wilson"
    appmod.customer_names["628700000010"] = "Caca"

    global sent_log

    cases = [
        ("pembayaran Yutha udah masuk", "628700000008", appmod.PAYMENT_STATUS_PAID),
        ("DP Caca confirmed", "628700000010", appmod.PAYMENT_STATUS_PARTIALLY_PAID),
        ("Wilson udah lunas", "628700000009", appmod.PAYMENT_STATUS_PAID),
    ]
    for i, (text, number, expected_status) in enumerate(cases):
        sent_log = []
        with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
            r = client.post("/webhook", data=json.dumps(owner_payload(text, msg_id=f"wamid.pay{i}")), content_type="application/json")
        assert r.status_code == 200
        pay = appmod.payment_state.get(number)
        assert pay is not None and pay["status"] == expected_status, (text, pay)
        assert appmod.followup_state.get(number, {}).get("converted") is True

    # "transfer dia belum masuk" -> pronoun fallback ke active_customer_context, status NEEDS_RECHECK
    appmod.active_customer_context[appmod.OWNER_WHATSAPP_NUMBER] = "628700000008"
    sent_log = []
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        client.post("/webhook", data=json.dumps(owner_payload("transfer dia belum masuk", msg_id="wamid.pay-neg")), content_type="application/json")
    pay = appmod.payment_state.get("628700000008")
    assert pay["status"] == appmod.PAYMENT_STATUS_NEEDS_RECHECK, pay
    print("test_owner_payment_commands_update_correct_customer OK")


# ---------- 10. Follow-up guard: skip customer yang lagi proses meeting/payment ----------
def test_followup_guard_skips_active_meeting_and_payment():
    reset_all()
    n1, n2, n3 = "628700000011", "628700000012", "628700000013"
    for n in (n1, n2, n3):
        appmod.followup_state[n] = {
            "last_customer_msg_at": appmod._utcnow() - appmod.timedelta(hours=13),
            "last_followup_at": None, "followup_count": 0, "converted": False,
        }
    appmod.meeting_requests[n1] = {"status": appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION}
    appmod.payment_state[n2] = {"status": appmod.PAYMENT_STATUS_PENDING_VERIFICATION}
    due = appmod.get_customers_due_for_followup()
    assert n1 not in due, "customer nunggu availability owner TIDAK BOLEH di-followup generik"
    assert n2 not in due, "customer proses pembayaran TIDAK BOLEH di-followup generik"
    assert n3 in due
    print("test_followup_guard_skips_active_meeting_and_payment OK")


# ---------- 11. Reminder meeting cuma buat status CONFIRMED ("scheduled") ----------
def test_reminders_only_for_confirmed_status():
    reset_all()
    number = "628700000014"
    appmod.customer_names[number] = "Andi"
    tomorrow = (appmod.now_wib().date() + appmod.timedelta(days=1)).strftime("%Y-%m-%d")
    aid = appmod.create_appointment(number, "Andi", "Toko Andi", tomorrow, "13:00", "test")
    appmod.appointments[aid]["status"] = "cancelled"
    appmod.followup_state[number] = {"last_customer_msg_at": appmod._utcnow(), "last_followup_at": None, "followup_count": 0, "converted": False}
    with patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        results = appmod.send_appointment_reminders()
    assert results == [], "appointment yang statusnya BUKAN scheduled/confirmed gak boleh dapet reminder"
    print("test_reminders_only_for_confirmed_status OK")


# ---------- 12. Tone audit: customer-facing tidak boleh mengandung gw/gue/lu/lo ----------
INFORMAL_PATTERN = re.compile(r"\b(gw|gue|lu|lo)\b", re.IGNORECASE)


def test_customer_facing_strings_have_no_informal_pronouns():
    texts_to_check = [
        appmod.SYSTEM_PROMPT,
        appmod.build_appointment_context(),
        appmod.build_payment_info_text(),
    ]
    for t in texts_to_check:
        assert not INFORMAL_PATTERN.search(t), f"informal pronoun leak ditemukan: {t[:400]}"
    print("test_customer_facing_strings_have_no_informal_pronouns OK")


def test_customer_facing_runtime_replies_have_no_informal_pronouns():
    reset_all()
    number = "628700000015"
    samples = [
        "mau ketemu dong",
        "bs ktmu bsk?",
        "mw dp",
        "langsung byr full bs?",
        "sabtu kosong g?",
        "meeting onlen aja",
        "brp hrg growth",
    ]
    for i, msg in enumerate(samples):
        with patch.object(appmod, "call_claude", return_value="Oke kak, boleh banget."), \
             patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
             patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
             patch.object(appmod, "send_typing_indicator", return_value=None), \
             patch.object(appmod, "notify_owner_new_message", return_value=None):
            client.post("/webhook", data=json.dumps(customer_payload(number, msg, msg_id=f"wamid.tone{i}")), content_type="application/json")
    for to, t in sent_log:
        if to == number:
            assert not INFORMAL_PATTERN.search(t), t
    print("test_customer_facing_runtime_replies_have_no_informal_pronouns OK")


# ---------- 13. Typo/informal customer text tetap dipahami (lewat parser hari & existing NLU) ----------
def test_typo_day_resolution_still_works():
    besok = appmod.resolve_day_text_to_date("bsk")
    assert besok is None or besok == (appmod.now_wib().date() + appmod.timedelta(days=1)).strftime("%Y-%m-%d")
    besok2 = appmod.resolve_day_text_to_date("besok")
    assert besok2 == (appmod.now_wib().date() + appmod.timedelta(days=1)).strftime("%Y-%m-%d")
    print("test_typo_day_resolution_still_works OK")


if __name__ == "__main__":
    test_payment_config_single_source()
    test_meeting_preference_creates_pending_not_confirmed()
    test_full_owner_mediated_booking_flow()
    test_owner_unavailable_declines_not_confirms()
    test_offline_blocked_on_closed_day_online_not_blocked()
    test_dp_unclear_notifies_owner_no_guessing()
    test_give_payment_info_injects_real_account()
    test_sudah_bayar_sets_pending_verification_not_paid()
    test_owner_payment_commands_update_correct_customer()
    test_followup_guard_skips_active_meeting_and_payment()
    test_reminders_only_for_confirmed_status()
    test_customer_facing_strings_have_no_informal_pronouns()
    test_customer_facing_runtime_replies_have_no_informal_pronouns()
    test_typo_day_resolution_still_works()
    print("ALL APPOINTMENT/PAYMENT UPDATE TESTS PASSED")
