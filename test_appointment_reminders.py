import os, json
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod

def reset():
    appmod.appointments.clear()
    appmod.followup_state.clear()
    appmod.customer_names.clear()

def fake_send(to, text):
    fake_send.calls.append((to, text))
    return True, None
fake_send.calls = []

# Test 1: H-1 reminder, customer MASIH dalam window 24 jam -> dikirim ke customer + owner
reset()
number = "628999911111"
appmod.customer_names[number] = "Wilson"
tomorrow = (appmod.now_wib().date() + timedelta(days=1)).strftime("%Y-%m-%d")
aid = appmod.create_appointment(number, "Wilson", "Toko Wilson", tomorrow, "10:00", "diskusi paket")
appmod.followup_state[number] = {"last_customer_msg_at": appmod._utcnow(), "last_followup_at": None, "followup_count": 0, "converted": False}

fake_send.calls = []
with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
    results = appmod.send_appointment_reminders()

assert results == [{"id": aid, "type": "h-1", "done": True}], results
assert len(fake_send.calls) == 2, fake_send.calls  # customer + owner
assert fake_send.calls[0][0] == number and "besok" in fake_send.calls[0][1], fake_send.calls
assert fake_send.calls[1][0] == appmod.OWNER_WHATSAPP_NUMBER, fake_send.calls
assert appmod.appointments[aid]["reminder_24h_sent"] is True
print("Test 1 (H-1 dalam window) OK")

# Test 2: idempotent -- panggil lagi, TIDAK kirim dobel
fake_send.calls = []
with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
    results2 = appmod.send_appointment_reminders()
assert results2 == [], results2
assert fake_send.calls == [], fake_send.calls
print("Test 2 (idempotent, gak dobel kirim) OK")

# Test 3: customer di LUAR window 24 jam -> customer TIDAK dikirim pesan, owner tetap dikasih tau (dengan catatan)
reset()
number2 = "628999922222"
appmod.customer_names[number2] = "Budi"
tomorrow = (appmod.now_wib().date() + timedelta(days=1)).strftime("%Y-%m-%d")
aid2 = appmod.create_appointment(number2, "Budi", "Toko Budi", tomorrow, "13:00", "diskusi")
appmod.followup_state[number2] = {"last_customer_msg_at": appmod._utcnow() - timedelta(hours=30), "last_followup_at": None, "followup_count": 0, "converted": False}

fake_send.calls = []
with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
    results3 = appmod.send_appointment_reminders()

assert results3 == [{"id": aid2, "type": "h-1", "done": True}], results3
assert len(fake_send.calls) == 1, fake_send.calls  # cuma owner
assert fake_send.calls[0][0] == appmod.OWNER_WHATSAPP_NUMBER
assert "window 24 jam" in fake_send.calls[0][1], fake_send.calls
print("Test 3 (di luar window, cuma owner dikasih tau) OK")

# Test 4: appointment status 'cancelled' -> TIDAK dapat reminder sama sekali
reset()
number3 = "628999933333"
tomorrow = (appmod.now_wib().date() + timedelta(days=1)).strftime("%Y-%m-%d")
aid3 = appmod.create_appointment(number3, "Caca", "Toko Caca", tomorrow, "15:00", "-")
appmod.update_appointment_status(aid3, "cancelled")
appmod.followup_state[number3] = {"last_customer_msg_at": appmod._utcnow(), "last_followup_at": None, "followup_count": 0, "converted": False}

fake_send.calls = []
with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
    results4 = appmod.send_appointment_reminders()
assert results4 == [], results4
assert fake_send.calls == [], fake_send.calls
print("Test 4 (appointment cancelled, gak dapet reminder) OK")

# Test 5: reschedule mereset flag reminder (gak keanggep 'udah dikirim' dari jadwal lama)
reset()
number4 = "628999944444"
tomorrow = (appmod.now_wib().date() + timedelta(days=1)).strftime("%Y-%m-%d")
aid4 = appmod.create_appointment(number4, "Dewi", "Toko Dewi", tomorrow, "10:00", "-")
appmod.appointments[aid4]["reminder_24h_sent"] = True  # simulasi udah pernah reminder H-1 sebelumnya
lusa = (appmod.now_wib().date() + timedelta(days=2)).strftime("%Y-%m-%d")
appmod.update_appointment_reschedule(aid4, lusa, "13:00")
assert appmod.appointments[aid4]["reminder_24h_sent"] is False, appmod.appointments[aid4]
print("Test 5 (reschedule reset flag reminder) OK")

print("ALL APPOINTMENT REMINDER TESTS PASSED")
