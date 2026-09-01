import os, json
from unittest.mock import patch, MagicMock

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod

client = appmod.app.test_client()

# Test 1: halaman /demo render, greeting ke-inject dengan benar, ada label Demo Simulation
r = client.get("/demo")
html = r.get_data(as_text=True)
assert "Demo Simulation" in html, "label Demo Simulation harus ada"
assert "demo AI WhatsApp Admin Kilas Works" in html, "greeting harus ke-inject ke halaman"
assert "__DEMO_GREETING_JS__" not in html, "placeholder greeting harusnya udah diganti"
assert "__OWNER_WA_LINK__" not in html, "placeholder link WA harusnya udah diganti"
print("Test 1 (halaman /demo render benar) OK")

# Test 2: onboarding max 3 pertanyaan -- system prompt eksplisit nyebut ini
assert "MAKSIMAL 3 PERTANYAAN" in appmod.DEMO_SYSTEM_PROMPT
assert "STOP ONBOARDING" in appmod.DEMO_SYSTEM_PROMPT
assert "JANGAN nawarin meeting" in appmod.DEMO_SYSTEM_PROMPT or "JANGAN nawarin meeting di PESAN PERTAMA" in appmod.DEMO_SYSTEM_PROMPT
print("Test 2 (system prompt sesuai spek 3 pertanyaan + gak buru2 nawarin meeting) OK")

# Test 3: reset demo ("coba bisnis lain") -- deterministic, gak manggil AI sama sekali
appmod.demo_sessions.clear()
sid = "sess-reset-1"
appmod.demo_sessions[sid] = {"history": [{"role": "user", "content": "halo"}], "count": 5, "created_at": appmod._utcnow(), "notified": False}

def boom(*a, **kw):
    raise AssertionError("AI TIDAK BOLEH dipanggil buat perintah reset!")

with patch.object(appmod.requests, "post", side_effect=boom):
    r = client.post("/demo/api", data=json.dumps({"session_id": sid, "message": "reset demo dong"}), content_type="application/json")
    data = r.get_json()
    assert data["reset"] is True
    assert data["reply"] == appmod.DEMO_GREETING
    assert appmod.demo_sessions[sid]["count"] == 0
    assert appmod.demo_sessions[sid]["history"] == []
print("Test 3 (reset demo, gak panggil AI, state ke-reset) OK")

# Test 3b: variasi reset lain
appmod.demo_sessions.clear()
for phrase in ["coba bisnis lain dong", "mulai ulang ya", "aku mau coba dari awal lagi- mulai ulang"]:
    sid2 = f"sess-{phrase[:5]}"
    appmod.demo_sessions[sid2] = {"history": [{"role": "user", "content": "x"}], "count": 3, "created_at": appmod._utcnow(), "notified": False}
    with patch.object(appmod.requests, "post", side_effect=boom):
        r = client.post("/demo/api", data=json.dumps({"session_id": sid2, "message": phrase}), content_type="application/json")
        assert r.get_json()["reset"] is True, phrase
print("Test 3b (variasi frasa reset semua terdeteksi) OK")

# Test 4: chat biasa TIDAK ke-detect sebagai reset (jangan overtrigger)
appmod.demo_sessions.clear()
sid3 = "sess-normal"
appmod.demo_sessions[sid3] = {"history": [], "count": 0, "created_at": appmod._utcnow(), "notified": False}

def fake_post_ok(url, headers=None, json=None, timeout=None):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"content": [{"text": "Oke, bisnisnya di bidang apa nih Kak?"}], "usage": {"input_tokens": 10, "output_tokens": 5}}
    return resp

with patch.object(appmod.requests, "post", side_effect=fake_post_ok):
    r = client.post("/demo/api", data=json.dumps({"session_id": sid3, "message": "Cafe Askar"}), content_type="application/json")
    data = r.get_json()
    assert data.get("reset") is not True
    assert "bidang apa" in data["reply"]
print("Test 4 (chat normal gak ke-trigger reset) OK")

# Test 5: demo SAMA SEKALI TIDAK nyentuh DB production (appointments/customer_names/messages)
appmod.appointments.clear()
appmod.customer_names.clear()
before_appt = dict(appmod.appointments)
before_cust = dict(appmod.customer_names)
with patch.object(appmod.requests, "post", side_effect=fake_post_ok):
    client.post("/demo/api", data=json.dumps({"session_id": "sess-isolate", "message": "mau booking jam 2 besok buat 8 orang"}), content_type="application/json")
assert appmod.appointments == before_appt, "demo TIDAK BOLEH nulis appointment production"
assert appmod.customer_names == before_cust, "demo TIDAK BOLEH nulis customer_names production"
print("Test 5 (demo gak polusi DB production) OK")

print("ALL DEMO UX TESTS PASSED")
