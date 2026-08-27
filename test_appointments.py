import os
import re
import json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import app as appmod

def reset_state():
    appmod.appointments.clear()
    appmod._appointment_id_counter = 0
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.active_customer_context.clear()

sent_log = []

def fake_send_whatsapp_message(to, text):
    sent_log.append((to, text))
    return True, None

def fake_send_reply_bubbles(to, msg_id, text):
    for part in text.split("|||"):
        sent_log.append((to, part))
    return True, None

# ---------- Test 1: parse_meeting_status_command ----------
def test_parse_meeting_status():
    cases = [
        ("meeting Caca selesai", "Caca", "completed"),
        ("meeting Kimfong gak jadi", "Kimfong", "cancelled"),
        ("meeting Andi no show", "Andi", "no_show"),
        ("meeting Andi no show tuh kayaknya", "Andi", "no_show"),
    ]
    for text, expect_target, expect_status in cases:
        r = appmod.parse_meeting_status_command(text)
        assert r is not None, f"failed to parse: {text}"
        assert r["status"] == expect_status, f"{text} -> {r}"
        assert expect_target.lower() in r["target_raw"].lower(), f"{text} -> {r}"
    print("test_parse_meeting_status OK")


# ---------- Test 2: booking flow (success + double-book prevention) ----------
def test_booking_flow():
    reset_state()
    number = "628222222222"
    appmod.customer_names[number] = "Caca"

    today = appmod.now_wib().date()
    # pick a valid non-day-off date within a week
    target_date = None
    for i in range(1, 8):
        d = today + appmod.timedelta(days=i)
        if d.weekday() not in appmod.MEETING_DAYS_OFF:
            target_date = d
            break
    date_str = target_date.strftime("%Y-%m-%d")
    time_str = appmod.DEFAULT_MEETING_SLOT_TIMES[0]

    ok, text, owner_notify = appmod.try_book_meeting(number, "Caca", "Toko Caca", date_str, time_str, "mau AI admin")
    assert ok, text
    assert "dijadwalkan" in text
    assert owner_notify is not None and "Meeting baru" in owner_notify
    assert len(appmod.appointments) == 1

    # double-book same slot should fail
    ok2, text2, owner_notify2 = appmod.try_book_meeting("628333333333", "Budi", "Toko Budi", date_str, time_str, "mau tanya")
    assert not ok2, text2
    assert "keisi" in text2 or "penuh" in text2
    print("test_booking_flow OK")
    return number, date_str, time_str


# ---------- Test 3: reschedule updates same record ----------
def test_reschedule_flow():
    number, date_str, time_str = test_booking_flow()
    appt_id_before = appmod.get_latest_scheduled_appointment_for(number)["id"]

    today = appmod.now_wib().date()
    new_date = None
    for i in range(2, 9):
        d = today + appmod.timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() not in appmod.MEETING_DAYS_OFF and ds != date_str:
            new_date = ds
            break
    new_time = appmod.DEFAULT_MEETING_SLOT_TIMES[1]

    ok, text, owner_notify = appmod.try_reschedule_meeting(number, new_date, new_time)
    assert ok, text
    appt_after = appmod.get_latest_scheduled_appointment_for(number)
    assert appt_after["id"] == appt_id_before, "reschedule should update same record, not create new"
    assert appt_after["meeting_date"] == new_date
    assert appt_after["meeting_time"] == new_time
    assert len(appmod.appointments) == 1  # only Caca's appointment (Budi's booking failed, never created)
    print("test_reschedule_flow OK")
    return number


# ---------- Test 4: cancel sets status, keeps history ----------
def test_cancel_flow():
    number = test_reschedule_flow()
    appt = appmod.get_latest_scheduled_appointment_for(number)
    assert appt is not None
    ok, text, owner_notify = appmod.try_cancel_meeting(number)
    assert ok, text
    assert appmod.appointments[appt["id"]]["status"] == "cancelled"
    assert appmod.get_latest_scheduled_appointment_for(number) is None
    # history preserved
    assert appt["id"] in appmod.appointments
    print("test_cancel_flow OK")


# ---------- Test 5: owner meeting-status command via webhook ----------
def test_owner_meeting_status_webhook():
    reset_state()
    number = "628444444444"
    appmod.customer_names[number] = "Caca"
    today = appmod.now_wib().date()
    target_date = None
    for i in range(1, 8):
        d = today + appmod.timedelta(days=i)
        if d.weekday() not in appmod.MEETING_DAYS_OFF:
            target_date = d
            break
    date_str = target_date.strftime("%Y-%m-%d")
    appmod.create_appointment(number, "Caca", "Toko Caca", date_str, appmod.DEFAULT_MEETING_SLOT_TIMES[0], "mau coba AI admin")

    global sent_log
    sent_log = []
    client = appmod.app.test_client()

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.status1",
                        "from": appmod.OWNER_WHATSAPP_NUMBER,
                        "type": "text",
                        "text": {"body": "meeting Caca selesai"},
                    }]
                }
            }]
        }]
    }

    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    appt = None
    for a in appmod.appointments.values():
        if a["number"] == number:
            appt = a
    assert appt is not None
    assert appt["status"] == "completed", appt
    assert any("diupdate jadi selesai" in t for _, t in sent_log), sent_log
    print("test_owner_meeting_status_webhook OK")


# ---------- Test 6: ambiguous name for meeting status command ----------
def test_owner_meeting_status_ambiguous():
    reset_state()
    appmod.customer_names["628555555551"] = "Kimfong Wijaya"
    appmod.customer_names["628555555552"] = "Kimfong Tan"

    global sent_log
    sent_log = []
    client = appmod.app.test_client()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.status2",
                        "from": appmod.OWNER_WHATSAPP_NUMBER,
                        "type": "text",
                        "text": {"body": "meeting Kimfong gak jadi"},
                    }]
                }
            }]
        }]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    assert any("mirip" in t for _, t in sent_log), sent_log
    print("test_owner_meeting_status_ambiguous OK")


if __name__ == "__main__":
    test_parse_meeting_status()
    test_cancel_flow()
    test_owner_meeting_status_webhook()
    test_owner_meeting_status_ambiguous()
    print("ALL TESTS PASSED")
