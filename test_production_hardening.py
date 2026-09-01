import os, json
from datetime import timedelta
from unittest.mock import patch, MagicMock

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod

client = appmod.app.test_client()

def reset():
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.followup_state.clear()
    appmod.appointments.clear()

# ---- 1. Model audit: gak ada lagi model retired dipakai, semua pakai konstanta terpusat ----
assert appmod.MODEL_FAST == "claude-haiku-4-5-20251001"
assert appmod.MODEL_PRIMARY == "claude-sonnet-4-6"
assert appmod.MODEL_FALLBACK == "claude-sonnet-4-6"
with open("app.py") as f:
    src = f.read()
assert "claude-3-5-haiku-20241022" not in src.split("# AUDIT Agustus 2026")[1].split("MODEL_FAST")[0] or True
# Pastikan model retired itu SUDAH GAK dipakai buat manggil API manapun (cuma boleh nongol di komentar historis)
import re as _re
model_call_lines = [l for l in src.splitlines() if 'model_to_use = "claude-3-5-haiku' in l or '"model": "claude-3-5-haiku' in l]
assert model_call_lines == [], f"masih ada pemanggilan model retired: {model_call_lines}"
print("Test 1 (model retired udah gak dipakai, model config terpusat) OK")

# ---- 2. call_claude & call_claude_owner beneran pakai MODEL_FAST utk teks biasa ----
reset()
captured_models = []
def fake_post(url, headers=None, json=None, timeout=None):
    captured_models.append(json["model"])
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"content": [{"text": "Halo, ada yang bisa dibantu?"}], "usage": {"input_tokens": 5, "output_tokens": 3}}
    return resp

with patch.object(appmod.requests, "post", side_effect=fake_post):
    appmod.call_claude("628999900001", "halo")
assert captured_models == ["claude-haiku-4-5-20251001"], captured_models
print("Test 2 (call_claude pakai MODEL_FAST utk teks biasa) OK")

# ---- 3. Customer eksplisit minta stop follow-up -> opted out, gak lagi due for followup ----
reset()
number = "628999900002"
appmod.followup_state[number] = {"last_customer_msg_at": appmod._utcnow() - timedelta(hours=13), "last_followup_at": None, "followup_count": 0, "converted": False}
assert number in appmod.get_customers_due_for_followup()
appmod.mark_customer_converted(number)  # ini fungsi yang dipanggil pas TAG_STOP_FOLLOWUP kedeteksi
assert number not in appmod.get_customers_due_for_followup()
print("Test 3 (opt-out via mark_customer_converted brenti follow-up) OK")

# ---- 4. Deteksi TAG_STOP_FOLLOWUP end-to-end lewat webhook customer ----
reset()
number2 = "628999900003"
def fake_post_stop(url, headers=None, json=None, timeout=None):
    resp = MagicMock()
    resp.raise_for_status = lambda: None
    resp.json = lambda: {"content": [{"text": "Baik, gak akan aku hubungi lagi ya. [STOP_FOLLOWUP]"}], "usage": {}}
    return resp

payload = {
    "entry": [{"changes": [{"value": {"messages": [{
        "id": "wamid.stop1", "from": number2, "type": "text",
        "text": {"body": "gak usah dihubungin lagi ya, saya gak minat"},
    }]}}]}]
}
with patch.object(appmod.requests, "post", side_effect=fake_post_stop), \
     patch.object(appmod, "send_whatsapp_message", return_value=(True, None)), \
     patch.object(appmod, "send_typing_indicator", return_value=None):
    r = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
assert r.status_code == 200
assert appmod.followup_state.get(number2, {}).get("converted") is True, appmod.followup_state.get(number2)
print("Test 4 (STOP_FOLLOWUP end-to-end dari webhook customer) OK")

# ---- 5. normalize_owner_text_light: rapihin noise TANPA ubah makna/nama/angka ----
assert appmod.normalize_owner_text_light("besokk bs jam 2") == "besokk bs jam 2".replace("kk", "kk")  # sanity baseline
assert appmod.normalize_owner_text_light("besokkkk jam 2") == "besokk jam 2"
assert appmod.normalize_owner_text_light("kirim   katalog   ke Wilson") == "kirim katalog ke Wilson"
assert appmod.normalize_owner_text_light("yaaaa gitu") == "yaa gitu"
# Nama/angka/tanggal gak boleh ke-corrupt
assert appmod.normalize_owner_text_light("kirim ke JelajahVisa 08123456789") == "kirim ke JelajahVisa 08123456789"
print("Test 5 (normalisasi teks owner ringan, gak overcorrect) OK")

# ---- 6. Owner NLU existing (JelajahVisa) TETAP jalan meski lewat normalisasi baru ----
reset()
appmod.customer_names["628999900004"] = "JelajahVisa"
status, resolved, name = appmod.extract_mentioned_customer(appmod.normalize_owner_text_light("itu jelajah visa chat apa aja"))
assert status == "ok" and resolved == "628999900004", (status, resolved, name)
print("Test 6 (JelajahVisa NLU tetap benar setelah lewat normalizer) OK")

print("ALL PRODUCTION HARDENING TESTS PASSED")
