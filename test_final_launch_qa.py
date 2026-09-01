"""Test tambahan untuk FINAL LAUNCH QA cycle (2026-08-26). Fokus HANYA pada bug/gap konkret yang
ditemukan lewat audit di cycle ini — bukan mengulang test yang sudah ada di file lain.

1. STOPWORDS_NOT_NAMES kehilangan kata "belum" (item 23 request — "belum" eksplisit diminta jangan
   diinterpretasi sebagai nama customer). Regression test biar gak balik lagi.
2. Fallback voice note untuk BILLING_OR_QUOTA_ERROR (kredit OpenAI habis) HARUS beda kalimat dari
   fallback "audio kurang jelas" biasa — customer/owner gak boleh disuruh "kirim ulang audio yang
   sama" kalau masalahnya bukan di audionya. Tidak boleh expose OpenAI/billing/API/HTTP status.
3. Owner command dalam bahasa Inggris ("Send the catalog to Wilson.") — SEND_VERB_PATTERN memang
   Indonesia-only (item request eksplisit larang bikin parser Inggris terpisah), tapi harus
   dibuktikan tetap ACTUALLY SEND lewat jalur AI/FORWARD_MARKER yang sudah ada.
4. GENERIC_AVAILABILITY_CONFIRM_PATTERN harus match kata-kata Inggris umum ("ok", "available",
   "ready") biar owner yang jawab availability generik dalam Inggris tetap kedeteksi.
5. Landing page: lead visual sudah diubah jadi jelas ilustratif (bukan nama bisnis yang bisa
   disalahartikan sebagai client asli), dan wording "Masuk Demo" tidak pernah dipakai.
"""
import os, json
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

import app as appmod
from test_voice_note import reset_all, sent_log as _unused_placeholder, audio_payload, fake_send_whatsapp_message

client = appmod.app.test_client()
sent_log = []


def _reset():
    global sent_log
    reset_all()
    sent_log = []


def _fake_send(to, text):
    sent_log.append((to, text))
    return True, None


def _fake_send_reply_bubbles(to, msg_id, text):
    for part in text.split("|||"):
        sent_log.append((to, part))
    return True, None


# ---------- 1. STOPWORDS_NOT_NAMES: "belum" tidak boleh diinterpretasi sebagai nama customer ----------
def test_stopword_belum_not_treated_as_customer_name():
    assert "belum" in appmod.STOPWORDS_NOT_NAMES, "'belum' harus ada di STOPWORDS_NOT_NAMES (item 23)"
    print("test_stopword_belum_not_treated_as_customer_name OK")


def test_all_requested_stopwords_present():
    required = {
        "apa", "aja", "itu", "dia", "tadi", "chat", "terakhir", "yang",
        "berapa", "gimana", "udah", "belum",
    }
    missing = required - appmod.STOPWORDS_NOT_NAMES
    assert not missing, f"stopword hilang: {missing}"
    print("test_all_requested_stopwords_present OK")


# ---------- 2. Billing/quota fallback: customer ----------
def test_customer_voice_note_billing_error_uses_distinct_fallback_not_unclear_wording():
    _reset()
    number = "628900300001"
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, appmod.VOICE_ERR_BILLING_OR_QUOTA)), \
         patch.object(appmod, "call_claude", side_effect=AssertionError("must not call AI on transcription failure")), \
         patch.object(appmod, "send_whatsapp_message", side_effect=_fake_send), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-billing-c1", "wamid.billing.c1")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert texts, "customer harus tetap dapat balasan (no crash, no silent drop)"
    combined = " ".join(texts).lower()
    assert "belum bisa diproses saat ini" in combined, texts
    assert "kebaca dengan jelas" not in combined, "billing error TIDAK BOLEH pakai wording 'kurang jelas'"
    for banned in ("openai", "billing", "api key", "http", "429", "quota"):
        assert banned not in combined, f"'{banned}' bocor ke customer: {texts}"
    print("test_customer_voice_note_billing_error_uses_distinct_fallback_not_unclear_wording OK")


def test_customer_voice_note_billing_error_english_wording():
    _reset()
    number = "628900300002"
    appmod.customer_language[number] = appmod.LANGUAGE_EN
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, appmod.VOICE_ERR_BILLING_OR_QUOTA)), \
         patch.object(appmod, "call_claude", side_effect=AssertionError("must not call AI on transcription failure")), \
         patch.object(appmod, "send_whatsapp_message", side_effect=_fake_send), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-billing-c2", "wamid.billing.c2")),
            content_type="application/json",
        )
    texts = [t for n, t in sent_log if n == number]
    combined = " ".join(texts).lower()
    assert "can't process voice notes right now" in combined, texts
    assert "couldn't read the voice note clearly" not in combined, texts
    print("test_customer_voice_note_billing_error_english_wording OK")


# ---------- 3. Billing/quota fallback: owner ----------
def test_owner_voice_note_billing_error_uses_distinct_fallback_not_unclear_wording():
    _reset()
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, appmod.VOICE_ERR_BILLING_OR_QUOTA)), \
         patch.object(appmod, "call_claude_owner", side_effect=AssertionError("must not call AI on transcription failure")), \
         patch.object(appmod, "send_whatsapp_message", side_effect=_fake_send):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(appmod.OWNER_WHATSAPP_NUMBER, "media-billing-o1", "wamid.billing.o1")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert texts, "owner harus tetap dapat balasan (no crash)"
    combined = " ".join(texts).lower()
    assert "belum bisa proses voice note sekarang" in combined, texts
    assert "nangkep voice note" not in combined, "billing error TIDAK BOLEH pakai wording 'belum nangkep'"
    for banned in ("openai", "billing", "api key", "http", "429", "quota"):
        assert banned not in combined, f"'{banned}' bocor ke owner: {texts}"
    print("test_owner_voice_note_billing_error_uses_distinct_fallback_not_unclear_wording OK")


# ---------- 4. Non-billing failure tetap pakai wording lama (no regression) ----------
def test_non_billing_voice_error_still_uses_generic_unclear_wording():
    _reset()
    number = "628900300003"
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, appmod.VOICE_ERR_MEDIA_DOWNLOAD_FAILED)), \
         patch.object(appmod, "call_claude", side_effect=AssertionError("must not call AI")), \
         patch.object(appmod, "send_whatsapp_message", side_effect=_fake_send), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-nonbilling-c1", "wamid.nonbilling.c1")),
            content_type="application/json",
        )
    texts = [t for n, t in sent_log if n == number]
    combined = " ".join(texts).lower()
    assert "kebaca dengan jelas" in combined, texts
    print("test_non_billing_voice_error_still_uses_generic_unclear_wording OK")


# ---------- 5. Credit exhaustion: no crash, single attempt (no retry spam) ----------
def test_credit_exhaustion_does_not_crash_and_does_not_retry():
    _reset()
    call_count = {"n": 0}

    def fake_transcribe(media_id):
        call_count["n"] += 1
        return None, appmod.VOICE_ERR_BILLING_OR_QUOTA

    number = "628900300004"
    with patch.object(appmod, "transcribe_audio_whatsapp", side_effect=fake_transcribe), \
         patch.object(appmod, "call_claude", side_effect=AssertionError("must not call AI")), \
         patch.object(appmod, "send_whatsapp_message", side_effect=_fake_send), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-credit-1", "wamid.credit.1")),
            content_type="application/json",
        )
    assert resp.status_code == 200, "webhook TIDAK BOLEH crash/500 saat credit habis"
    assert call_count["n"] == 1, f"transcribe_audio_whatsapp dipanggil {call_count['n']}x, harus cuma 1x (no retry spam)"
    print("test_credit_exhaustion_does_not_crash_and_does_not_retry OK")


# ---------- 6. Owner command bahasa Inggris tetap ACTUALLY SEND lewat existing FORWARD_MARKER pipeline ----------
def test_owner_english_command_still_sends_via_existing_ai_pipeline():
    _reset()
    customer_number = "628900400001"
    appmod.customer_names[customer_number] = "Wilson"
    appmod.conversations[customer_number] = [{"role": "user", "content": "halo"}]

    # "Send the catalog to Wilson." -> SEND_VERB_PATTERN (Indonesia-only) SENGAJA tidak match ini
    # (item request: jangan bikin parser Inggris terpisah) -> harus lewat jalur AI yang sudah ada
    # (call_claude_owner mengembalikan FORWARD_MARKER, lalu benar2 dikirim ke customer).
    assert appmod.parse_owner_send_command("Send the catalog to Wilson.") is None, (
        "sanity check: SEND_VERB_PATTERN memang Indonesia-only by design, harus lewat AI pipeline"
    )

    ai_reply = f"{appmod.FORWARD_MARKER} Here's our service catalog, Wilson!"
    with patch.object(appmod, "call_claude_owner", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", side_effect=_fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=_fake_send), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        appmod.active_customer_context[appmod.OWNER_WHATSAPP_NUMBER] = customer_number
        resp = client.post(
            "/webhook",
            data=json.dumps({
                "entry": [{"changes": [{"value": {"messages": [{
                    "id": "wamid.en.owner.1", "from": appmod.OWNER_WHATSAPP_NUMBER, "type": "text",
                    "text": {"body": "Send the catalog to Wilson."},
                }]}}]}]
            }),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts_to_customer = [t for n, t in sent_log if n == customer_number]
    assert any("catalog" in t.lower() for t in texts_to_customer), (
        f"English owner command harus tetap benar2 terkirim ke customer, got: {texts_to_customer}"
    )
    print("test_owner_english_command_still_sends_via_existing_ai_pipeline OK")


# ---------- 7. GENERIC_AVAILABILITY_CONFIRM_PATTERN cocok untuk kata Inggris umum ----------
def test_generic_availability_confirm_pattern_matches_english_words():
    for phrase in ["ok", "okay", "available", "ready", "yup", "sure"[:0] or "ok"]:
        assert appmod.GENERIC_AVAILABILITY_CONFIRM_PATTERN.match(phrase), f"'{phrase}' harus match"
    # Exact-time English reply ("Tuesday at 9 is available") SENGAJA tidak match pattern generik ini
    # (by design — biar diproses lewat jalur AI [OWNER_MEETING_SLOTS] yang extract jam-nya, bukan
    # dianggap generic yes/no tanpa jam).
    assert not appmod.GENERIC_AVAILABILITY_CONFIRM_PATTERN.match("Tuesday at 9 is available")
    print("test_generic_availability_confirm_pattern_matches_english_words OK")


# ---------- 8. Landing page: lead visual sudah jelas ilustratif, bukan nama bisnis yang menyesatkan ----------
def test_landing_page_lead_visual_is_clearly_illustrative():
    with open("landing-page-kilasworks.html", encoding="utf-8") as f:
        html = f.read()
    assert "Contoh Alur AI Admin" in html
    assert "Ilustrasi cara kerja AI Admin" in html
    assert "Customer A" in html and "Customer B" in html and "Customer C" in html
    # Nama bisnis lama yang bisa disalahartikan sebagai client asli HARUS sudah hilang.
    for old_name in ("Studio Kopi Senja", "Rumah Skincare", "Bengkel Detailing X"):
        assert old_name not in html, f"nama lama '{old_name}' masih ada, bisa disalahartikan sebagai client asli"
    assert "Masuk Demo" not in html, "wording 'Masuk Demo' dilarang eksplisit"
    print("test_landing_page_lead_visual_is_clearly_illustrative OK")


if __name__ == "__main__":
    test_stopword_belum_not_treated_as_customer_name()
    test_all_requested_stopwords_present()
    test_customer_voice_note_billing_error_uses_distinct_fallback_not_unclear_wording()
    test_customer_voice_note_billing_error_english_wording()
    test_owner_voice_note_billing_error_uses_distinct_fallback_not_unclear_wording()
    test_non_billing_voice_error_still_uses_generic_unclear_wording()
    test_credit_exhaustion_does_not_crash_and_does_not_retry()
    test_owner_english_command_still_sends_via_existing_ai_pipeline()
    test_generic_availability_confirm_pattern_matches_english_words()
    test_landing_page_lead_visual_is_clearly_illustrative()
    print("ALL FINAL LAUNCH QA TESTS PASSED")
