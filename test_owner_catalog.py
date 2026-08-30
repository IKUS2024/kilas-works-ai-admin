import os
import json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import app as appmod


def reset_state():
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.active_customer_context.clear()
    appmod.pending_owner_questions.clear()


# ---------- Test 1: katalog.pdf ditemukan (langsung di root workspace) ----------
def test_find_catalog_pdf_path():
    appmod._CATALOG_PDF_PATH_CACHE.update(path=None, checked=False)
    path = appmod.find_catalog_pdf_path()
    assert path is not None, "katalog.pdf harus ketemu di repo"
    assert os.path.exists(path)
    assert path.lower().endswith("katalog.pdf")
    print("test_find_catalog_pdf_path OK")


# ---------- Test 2: owner system prompt sekarang punya knowledge harga ----------
def test_owner_prompt_has_pricing_knowledge():
    assert "AI WhatsApp Admin" in appmod.SYSTEM_PROMPT_OWNER_BASE
    assert "999rb" in appmod.SYSTEM_PROMPT_OWNER_BASE or "999.000" in appmod.SYSTEM_PROMPT_OWNER_BASE
    assert "Meta Ads" in appmod.SYSTEM_PROMPT_OWNER_BASE
    assert "aku butuh list jasa dari lo" in appmod.SYSTEM_PROMPT_OWNER_BASE  # instruksi larangan, bukan jawaban
    print("test_owner_prompt_has_pricing_knowledge OK")


# ---------- Test 3: parser membedakan QUERY vs ACTION ----------
def test_parse_owner_catalog_command_query_vs_action():
    # Query-only -> None (jangan dieksekusi kirim apapun)
    assert appmod.parse_owner_catalog_command("katalog kita isinya apa?") is None
    assert appmod.parse_owner_catalog_command("katalog kita isinya apa") is None
    assert appmod.parse_owner_catalog_command("ada apa aja di katalog kita") is None
    assert appmod.parse_owner_catalog_command("kasih tau dong katalog kita ada apa aja") is None
    assert appmod.parse_owner_catalog_command("jasa kita sekarang apa aja") is None  # gak nyebut katalog+kirim
    assert appmod.parse_owner_catalog_command("AI Admin sekarang berapa") is None

    # Action -> dict
    r1 = appmod.parse_owner_catalog_command("kirim katalog ke Wilson")
    assert r1 == {"self_target": False, "send_services_intro": False}, r1

    r2 = appmod.parse_owner_catalog_command("kirimin Wilson katalog kita")
    assert r2 == {"self_target": False, "send_services_intro": False}, r2

    r3 = appmod.parse_owner_catalog_command("kirim katalog terbaru ke Kimfong")
    assert r3 == {"self_target": False, "send_services_intro": False}, r3

    r4 = appmod.parse_owner_catalog_command("kirim katalog ke gw")
    assert r4 == {"self_target": True, "send_services_intro": False}, r4

    r5 = appmod.parse_owner_catalog_command("kasih Wilson info jasa terbaru kita terus kirim katalog juga")
    assert r5 == {"self_target": False, "send_services_intro": True}, r5

    r6 = appmod.parse_owner_catalog_command(
        "yang Wilson kirimin ke dia jasa kita yang terbaru bisa apa aja dan kirim katalognya juga"
    )
    assert r6 == {"self_target": False, "send_services_intro": True}, r6

    print("test_parse_owner_catalog_command_query_vs_action OK")


# ---------- Test 4: end-to-end webhook — kirim katalog ke customer (single send, confirmation) ----------
def test_webhook_send_catalog_to_customer():
    reset_state()
    number = "628999911111"
    appmod.customer_names[number] = "Wilson"

    sent_texts = []
    catalog_calls = []

    def fake_send_whatsapp_message(to, text):
        sent_texts.append((to, text))
        return True, None

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat1", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "kirim katalog ke Wilson"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert catalog_calls == [number], f"katalog harus dikirim SATU KALI ke Wilson, dapat: {catalog_calls}"
    assert any("Katalog terkirim ke Wilson" in t for _, t in sent_texts), sent_texts
    print("test_webhook_send_catalog_to_customer OK")


# ---------- Test 5: kirim katalog ke owner sendiri ("kirim katalog ke gw") ----------
def test_webhook_send_catalog_to_self():
    reset_state()
    sent_texts = []
    catalog_calls = []

    def fake_send_whatsapp_message(to, text):
        sent_texts.append((to, text))
        return True, None

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat2", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "kirim katalog ke gw"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert catalog_calls == [appmod.OWNER_WHATSAPP_NUMBER], catalog_calls
    assert any("Katalog Kilas Works sudah aku kirim ke kamu" in t for _, t in sent_texts), sent_texts
    print("test_webhook_send_catalog_to_self OK")


# ---------- Test 6: combined action — info jasa terbaru + kirim katalog (2 actions, masing2 1x) ----------
def test_webhook_combined_intro_and_catalog():
    reset_state()
    number = "628999922222"
    appmod.customer_names[number] = "Wilson"

    sent_owner_texts = []
    sent_bubbles = []
    catalog_calls = []

    def fake_send_whatsapp_message(to, text):
        sent_owner_texts.append((to, text))
        return True, None

    def fake_send_reply_bubbles(to, msg_id, text):
        sent_bubbles.append((to, text))
        return True, None

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat3", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "yang Wilson kirimin ke dia jasa kita yang terbaru bisa apa aja dan kirim katalognya juga"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    # Pesan intro cuma dikirim SATU KALI ke Wilson
    assert len(sent_bubbles) == 1 and sent_bubbles[0][0] == number, sent_bubbles
    assert "Content Creation" in sent_bubbles[0][1] and "AI WhatsApp Admin" in sent_bubbles[0][1], sent_bubbles
    # Katalog PDF juga cuma SATU KALI
    assert catalog_calls == [number], catalog_calls
    # Owner dapat SATU konfirmasi gabungan
    assert any("Info layanan + katalog sudah terkirim ke Wilson" in t for _, t in sent_owner_texts), sent_owner_texts
    print("test_webhook_combined_intro_and_catalog OK")


# ---------- Test 7: query soal katalog TIDAK memicu pengiriman apapun ----------
def test_webhook_catalog_query_does_not_send():
    reset_state()
    catalog_calls = []
    bubble_calls = []

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    def fake_call_claude_owner(owner_number, owner_message, pending_question, pending_customer_number, **kwargs):
        return "Katalog kita isinya: AI WhatsApp Admin, Content Basic/Growth/Pro, Meta Ads, Website, Event."

    def fake_send_reply_bubbles(to, msg_id, text):
        bubble_calls.append((to, text))
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat4", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "katalog kita isinya apa?"},
        }]}}]}]
    }
    with patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf), \
         patch.object(appmod, "call_claude_owner", side_effect=fake_call_claude_owner), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert catalog_calls == [], f"query doang harusnya GAK kirim apa-apa, tapi: {catalog_calls}"
    assert len(bubble_calls) == 1
    print("test_webhook_catalog_query_does_not_send OK")


# ---------- Test 8: ambiguous name saat kirim katalog -> tanya, jangan nebak ----------
def test_webhook_catalog_ambiguous_asks():
    reset_state()
    appmod.customer_names["628999933331"] = "Kimfong Wijaya"
    appmod.customer_names["628999933332"] = "Kimfong Tan"

    sent_log = []

    def fake_send(to, text):
        sent_log.append((to, text))
        return True, None

    catalog_calls = []

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat5", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "kirim katalog ke Kimfong"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert catalog_calls == [], "jangan kirim apapun kalau nama ambigu"
    assert any("mirip" in t for _, t in sent_log), sent_log
    print("test_webhook_catalog_ambiguous_asks OK")


# ---------- Test 9: "yaudah kirim sekalian katalog" pakai active_customer_context ----------
def test_webhook_catalog_uses_active_context():
    reset_state()
    number = "628999944444"
    appmod.customer_names[number] = "Budi"
    appmod.active_customer_context[appmod.OWNER_WHATSAPP_NUMBER] = number

    sent_texts = []
    catalog_calls = []

    def fake_send_whatsapp_message(to, text):
        sent_texts.append((to, text))
        return True, None

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat6", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "yaudah kirim sekalian katalog"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert catalog_calls == [number], catalog_calls
    assert any("Katalog terkirim ke Budi" in t for _, t in sent_texts), sent_texts
    print("test_webhook_catalog_uses_active_context OK")


# ---------- Test 10: kegagalan kirim -> owner dikasih tau GAGAL, bukan diklaim sukses ----------
def test_webhook_catalog_send_failure_reported_honestly():
    reset_state()
    number = "628999955555"
    appmod.customer_names[number] = "Wilson"

    sent_texts = []

    def fake_send_whatsapp_message(to, text):
        sent_texts.append((to, text))
        return True, None

    def fake_send_catalog_pdf(to_number):
        return False, "media upload failed"

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat7", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "kirim katalog ke Wilson"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert any("GAGAL" in t for _, t in sent_texts), sent_texts
    assert not any("terkirim" in t.lower() and "gagal" not in t.lower() for _, t in sent_texts), sent_texts
    print("test_webhook_catalog_send_failure_reported_honestly OK")


# ---------- Test 11 (gap-fix): "katalog dong"/"minta katalog" (bare request, no send verb) ----------
def test_parse_owner_catalog_command_bare_request():
    # Bare request (no explicit send verb) -> masih dianggap ACTION sekarang (gap-fix), bukan None lagi.
    r1 = appmod.parse_owner_catalog_command("katalog dong")
    assert r1 is not None, "katalog dong harus dieksekusi (kirim ke owner), bukan diabaikan"
    r2 = appmod.parse_owner_catalog_command("minta katalog")
    assert r2 is not None
    r3 = appmod.parse_owner_catalog_command("boleh minta katalog")
    assert r3 is not None
    # Query beneran tetap None (regresi guard) walau ada kata "dong".
    assert appmod.parse_owner_catalog_command("kasih tau dong katalog kita ada apa aja") is None
    print("test_parse_owner_catalog_command_bare_request OK")


# ---------- Test 12 (gap-fix): "katalog dong" tanpa target -> default kirim ke OWNER, bukan nanya ----------
def test_webhook_catalog_bare_request_defaults_to_owner():
    reset_state()
    sent_texts = []
    catalog_calls = []

    def fake_send_whatsapp_message(to, text):
        sent_texts.append((to, text))
        return True, None

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat8", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "katalog dong"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    # Katalog harus terkirim ke OWNER sendiri (bukan nanya "buat siapa"), dan TIDAK ADA pertanyaan
    # klarifikasi "mau dikirim ke siapa" yang dikirim balik.
    assert catalog_calls == [appmod.OWNER_WHATSAPP_NUMBER], catalog_calls
    assert not any("dikirim ke siapa" in t.lower() for _, t in sent_texts), sent_texts
    print("test_webhook_catalog_bare_request_defaults_to_owner OK")


# ---------- Test 13 (gap-fix): "minta katalog" juga default ke owner ----------
def test_webhook_catalog_minta_katalog_defaults_to_owner():
    reset_state()
    catalog_calls = []

    def fake_send_whatsapp_message(to, text):
        return True, None

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    client = appmod.app.test_client()
    payload = {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": "wamid.cat9", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
            "text": {"body": "minta katalog dong"},
        }]}}]}]
    }
    with patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert catalog_calls == [appmod.OWNER_WHATSAPP_NUMBER], catalog_calls
    print("test_webhook_catalog_minta_katalog_defaults_to_owner OK")


if __name__ == "__main__":
    test_find_catalog_pdf_path()
    test_owner_prompt_has_pricing_knowledge()
    test_parse_owner_catalog_command_query_vs_action()
    test_webhook_send_catalog_to_customer()
    test_webhook_send_catalog_to_self()
    test_webhook_combined_intro_and_catalog()
    test_webhook_catalog_query_does_not_send()
    test_webhook_catalog_ambiguous_asks()
    test_webhook_catalog_uses_active_context()
    test_webhook_catalog_send_failure_reported_honestly()
    test_parse_owner_catalog_command_bare_request()
    test_webhook_catalog_bare_request_defaults_to_owner()
    test_webhook_catalog_minta_katalog_defaults_to_owner()
    print("ALL CATALOG TESTS PASSED")
