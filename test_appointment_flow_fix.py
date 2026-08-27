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


_owner_msg_counter = [0]


def owner_payload(text, msg_id=None):
    if msg_id is None:
        _owner_msg_counter[0] += 1
        msg_id = f"wamid.ownerfix.{_owner_msg_counter[0]}"
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
        msg_id = f"wamid.custfix.{_msg_counter[0]}"
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


def send_owner_message_deterministic(text):
    """Kirim pesan owner sambil MOCK call_claude_owner buat MELEDAK kalau ke-panggil — dipakai buat
    ngebuktiin path yang diklaim DETERMINISTIK (RULE 1/4/5/6) beneran gak pernah nyentuh AI sama sekali."""
    global sent_log

    def boom(*a, **kw):
        raise AssertionError("call_claude_owner SHOULD NOT be called for this deterministic path")

    with patch.object(appmod, "call_claude_owner", side_effect=boom), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        return client.post("/webhook", data=json.dumps(owner_payload(text)), content_type="application/json")


def send_owner_message_with_ai(text, owner_reply):
    global sent_log
    with patch.object(appmod, "call_claude_owner", return_value=owner_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        return client.post("/webhook", data=json.dumps(owner_payload(text)), content_type="application/json")


def find_upcoming_tuesday_sep_2026():
    """Cari tanggal Selasa terdekat (>=1 hari ke depan) dari 'hari ini' versi test, dipakai biar
    resolve_day_text_to_date('selasa') konsisten sama harapan test tanpa hardcode tanggal absolut."""
    today = appmod.now_wib().date()
    for i in range(1, 8):
        d = today + appmod.timedelta(days=i)
        if d.weekday() == 1:  # Selasa
            return d
    raise AssertionError("gak nemu Selasa dalam 7 hari ke depan (harusnya mustahil)")


# ---------- 0. ROOT CAUSE REPRO: exact bug scenario (Yutha, Selasa, online, owner jawab availability) ----------
def test_bug_repro_yutha_selasa_online_generic_confirm():
    global sent_log
    reset_all()
    sent_log = []
    number = "628800100001"
    appmod.customer_names[number] = "Yutha Halim"

    tuesday = find_upcoming_tuesday_sep_2026()
    ai_reply = "Siap, aku cek dulu ya kak.[MEETING_PREFERENCE: mode=online|day=selasa]"
    resp = send_customer_message(number, "Selasa online meeting boleh gak ya", ai_reply)
    assert resp.status_code == 200

    req = appmod.meeting_requests[number]
    assert req["status"] == appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION
    assert req["resolved_date"] == tuesday.strftime("%Y-%m-%d")
    assert req.get("requested_time") is None  # customer belum sebut jam

    # Owner cuma jawab GENERIK, tanpa nyebut jam sama sekali -> HARUS deterministik (AI gak boleh
    # dipanggil sama sekali), HARUS tetap nyebut Selasa (bukan Minggu / hari lain), HARUS nanya jam
    # SEKALI aja (bukan ngulang pertanyaan lama yang generik).
    resp2 = send_owner_message_deterministic("available")
    assert resp2.status_code == 200

    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("jam berapa" in t.lower() for t in owner_texts), owner_texts
    assert not any("minggu" in t.lower() for t in owner_texts), owner_texts
    assert any("selasa" in t.lower() for t in owner_texts), owner_texts
    # Tanggal TETAP terkunci ke Selasa yang sama, gak berubah gara-gara balesan generik owner.
    assert appmod.meeting_requests[number]["resolved_date"] == tuesday.strftime("%Y-%m-%d")
    assert appmod.meeting_requests[number]["status"] == appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION
    print("test_bug_repro_yutha_selasa_online_generic_confirm OK")


# ---------- RULE 1: customer minta jam EXACT, owner confirm generik -> LANGSUNG CONFIRMED ----------
def test_rule1_customer_exact_time_owner_generic_confirm():
    global sent_log
    reset_all()
    sent_log = []
    number = "628800100002"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa|time=09:00]"
    resp = send_customer_message(number, "Selasa jam 9 bisa?", ai_reply)
    assert resp.status_code == 200
    assert appmod.meeting_requests[number]["requested_time"] == "09:00"

    resp2 = send_owner_message_deterministic("available")
    assert resp2.status_code == 200

    # Appointment harus LANGSUNG jadi, TANPA nanya customer lagi "jam mana yang nyaman?"
    appt = appmod.get_latest_scheduled_appointment_for(number)
    assert appt is not None, "harus langsung CONFIRMED, bukan nunggu ronde lagi"
    assert appt["meeting_time"] == "09:00"
    assert number not in appmod.meeting_requests, "state pending harus udah kelar (bukan nyangkut lagi)"

    customer_texts = [t for n, t in sent_log if n == number]
    assert any("dikonfirmasi" in t.lower() for t in customer_texts), customer_texts
    assert not any("jam mana yang nyaman" in t.lower() for t in customer_texts), customer_texts
    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("dikonfirmasi" in t.lower() for t in owner_texts), owner_texts
    print("test_rule1_customer_exact_time_owner_generic_confirm OK")


# ---------- RULE 1 (varian tag AI): owner restate jam yang PERSIS sama via [OWNER_MEETING_SLOTS] ----------
def test_rule1_owner_restates_same_exact_time_via_tag():
    reset_all()
    number = "628800100003"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa|time=09:00]"
    send_customer_message(number, "Selasa jam 9 ya", ai_reply)
    assert appmod.meeting_requests[number]["requested_time"] == "09:00"

    owner_reply = "Oke bisa.[OWNER_MEETING_SLOTS: customer=Yutha|times=09:00]"
    resp = send_owner_message_with_ai("jam 9 bisa", owner_reply)
    assert resp.status_code == 200

    appt = appmod.get_latest_scheduled_appointment_for(number)
    assert appt is not None and appt["meeting_time"] == "09:00"
    assert number not in appmod.meeting_requests
    print("test_rule1_owner_restates_same_exact_time_via_tag OK")


# ---------- RULE 2: customer gak sebut jam, owner kasih SATU jam -> ditawarin ke customer, BUKAN langsung confirmed ----------
def test_rule2_owner_gives_single_new_time_offers_not_confirms():
    reset_all()
    number = "628800100004"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa]"
    send_customer_message(number, "Selasa aja", ai_reply)
    assert appmod.meeting_requests[number].get("requested_time") is None

    owner_reply = "Oke.[OWNER_MEETING_SLOTS: customer=Yutha|times=09:00]"
    resp = send_owner_message_with_ai("jam 9 bisa", owner_reply)
    assert resp.status_code == 200

    # BELUM confirmed — masih nunggu customer bilang cocok.
    assert appmod.get_latest_scheduled_appointment_for(number) is None
    req = appmod.meeting_requests[number]
    assert req["status"] == appmod.MEETING_STATE_SLOTS_OFFERED
    assert req["offered_slots"] == ["09:00"]
    print("test_rule2_owner_gives_single_new_time_offers_not_confirms OK")


# ---------- RULE 3: owner kasih beberapa slot -> ditawarin semua, customer pilih -> CONFIRMED ----------
def test_rule3_owner_gives_multiple_slots_customer_picks():
    global sent_log
    reset_all()
    sent_log = []
    number = "628800100005"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa]"
    send_customer_message(number, "Selasa aja", ai_reply)

    owner_reply = "Oke.[OWNER_MEETING_SLOTS: customer=Yutha|times=09:00,11:00]"
    send_owner_message_with_ai("jam 9 atau 11 bisa, teruskan", owner_reply)

    customer_texts = [t for n, t in sent_log if n == number]
    assert any("09.00" in t and "11.00" in t for t in customer_texts), customer_texts

    ai_pick_reply = "Sip.[MEETING_SLOT_PICK: time=09:00]"
    resp = send_customer_message(number, "jam 9 aja", ai_pick_reply)
    assert resp.status_code == 200
    appt = appmod.get_latest_scheduled_appointment_for(number)
    assert appt is not None and appt["meeting_time"] == "09:00"
    print("test_rule3_owner_gives_multiple_slots_customer_picks OK")


# ---------- RULE 4: date lock — owner cuma bilang "iya available" tanpa kandidat sama sekali ----------
def test_rule4_date_lock_generic_confirm_no_candidate():
    global sent_log
    reset_all()
    sent_log = []
    number = "628800100006"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa]"
    send_customer_message(number, "Selasa online ya", ai_reply)
    tuesday_str = appmod.meeting_requests[number]["resolved_date"]

    resp = send_owner_message_deterministic("iya available")
    assert resp.status_code == 200

    # Tanggal TETAP Selasa yang sama, statusnya tetap PENDING (nunggu jam), TIDAK di-drop/diganti hari lain.
    req = appmod.meeting_requests[number]
    assert req["resolved_date"] == tuesday_str
    assert req["status"] == appmod.MEETING_STATE_PENDING_OWNER_CONFIRMATION
    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("jam berapa" in t.lower() for t in owner_texts), owner_texts
    print("test_rule4_date_lock_generic_confirm_no_candidate OK")


# ---------- RULE 5 & 6: "teruskan" pas slot udah ditawarin -> RESEND beneran, bukan draft, gak nanya ulang ----------
def test_rule5_teruskan_resends_actual_message_not_draft():
    global sent_log
    reset_all()
    number = "628800100007"
    appmod.customer_names[number] = "Yutha"
    appmod.meeting_requests[number] = {
        "status": appmod.MEETING_STATE_SLOTS_OFFERED,
        "mode": "online", "day_text": "selasa", "day_display": "Selasa, 1 September 2026",
        "resolved_date": "2026-09-01", "requested_time": None,
        "name": "Yutha", "business_name": None, "need_summary": None,
        "offered_slots": ["09:00", "11:00"], "created_at": None,
    }
    sent_log = []

    resp = send_owner_message_deterministic("available, teruskan ke Yutha")
    assert resp.status_code == 200

    customer_texts = [t for n, t in sent_log if n == number]
    assert any("09.00" in t and "11.00" in t for t in customer_texts), customer_texts
    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("terkirim" in t.lower() for t in owner_texts), owner_texts
    assert not any("pesan_untuk_customer" in t.lower() for t in owner_texts), owner_texts
    print("test_rule5_teruskan_resends_actual_message_not_draft OK")


# ---------- RULE 6: setelah availability owner diterima (langsung confirmed), gak nyangkut di pending list lagi ----------
def test_rule6_no_repeat_question_after_confirmed():
    reset_all()
    number = "628800100008"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa|time=09:00]"
    send_customer_message(number, "Selasa jam 9 bisa?", ai_reply)
    assert "Yutha" in appmod.build_pending_meeting_requests_context()

    send_owner_message_deterministic("available")

    # Udah CONFIRMED & di-pop dari meeting_requests -> gak lagi muncul di context yang dikasih ke
    # owner AI, jadi gak akan ditanyain ulang "ada jam yang available?" buat Yutha lagi.
    assert number not in appmod.meeting_requests
    assert "Yutha" not in appmod.build_pending_meeting_requests_context()
    print("test_rule6_no_repeat_question_after_confirmed OK")


# ---------- Owner nyebut ANGKA JAM eksplisit -> TETAP lewat jalur AI existing (gak ke-intercept) ----------
def test_owner_explicit_digit_still_goes_through_ai_tag_path():
    reset_all()
    number = "628800100009"
    appmod.customer_names[number] = "Yutha"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa]"
    send_customer_message(number, "Selasa aja", ai_reply)

    owner_reply = "Sip.[OWNER_MEETING_SLOTS: customer=Yutha|times=13:00,15:00]"
    # Sengaja TIDAK pakai send_owner_message_deterministic (yang bakal meledak kalau AI ke-panggil) —
    # di sini AI JUSTRU HARUS dipanggil karena ada angka jam eksplisit di teks owner.
    resp = send_owner_message_with_ai("jam 1 atau 3 bisa", owner_reply)
    assert resp.status_code == 200
    req = appmod.meeting_requests[number]
    assert req["status"] == appmod.MEETING_STATE_SLOTS_OFFERED
    assert req["offered_slots"] == ["13:00", "15:00"]
    print("test_owner_explicit_digit_still_goes_through_ai_tag_path OK")


# ---------- Race condition guard: requested_time ternyata udah kepakai duluan, JANGAN asal confirm ----------
def test_requested_time_already_booked_does_not_force_confirm():
    global sent_log
    reset_all()
    sent_log = []
    number = "628800100010"
    other_number = "628800100011"
    appmod.customer_names[number] = "Yutha"
    appmod.customer_names[other_number] = "Wilson"

    ai_reply = "Oke aku cek dulu ya.[MEETING_PREFERENCE: mode=online|day=selasa|time=09:00]"
    send_customer_message(number, "Selasa jam 9 bisa?", ai_reply)
    date_str = appmod.meeting_requests[number]["resolved_date"]

    # Wilson keduluan kepesan di jam & tanggal yang sama.
    appmod.create_appointment(other_number, "Wilson", None, date_str, "09:00", "duluan")

    resp = send_owner_message_deterministic("available")
    assert resp.status_code == 200

    owner_texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("kepakai" in t.lower() for t in owner_texts), owner_texts
    # Customer Yutha TIDAK dapet appointment palsu.
    appt = appmod.get_latest_scheduled_appointment_for(number)
    assert appt is None
    print("test_requested_time_already_booked_does_not_force_confirm OK")


if __name__ == "__main__":
    test_bug_repro_yutha_selasa_online_generic_confirm()
    test_rule1_customer_exact_time_owner_generic_confirm()
    test_rule1_owner_restates_same_exact_time_via_tag()
    test_rule2_owner_gives_single_new_time_offers_not_confirms()
    test_rule3_owner_gives_multiple_slots_customer_picks()
    test_rule4_date_lock_generic_confirm_no_candidate()
    test_rule5_teruskan_resends_actual_message_not_draft()
    test_rule6_no_repeat_question_after_confirmed()
    test_owner_explicit_digit_still_goes_through_ai_tag_path()
    test_requested_time_already_booked_does_not_force_confirm()
    print("ALL APPOINTMENT FLOW FIX TESTS PASSED")
