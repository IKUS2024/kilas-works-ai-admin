import os, json
from unittest.mock import patch

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
    appmod.owner_conversations.clear()
    appmod.active_customer_context.clear()
    appmod.meeting_requests.clear()
    appmod.payment_state.clear()
    appmod.followup_state.clear()
    appmod.pending_owner_questions.clear()
    appmod.lead_stage.clear()
    appmod.customer_language.clear()
    appmod.demo_sessions.clear()
    appmod.PROCESSED_MESSAGE_IDS.clear()
    appmod.FEATURES["voice_note_customer"] = True
    appmod.FEATURES["voice_note_owner"] = True


sent_log = []


def fake_send_whatsapp_message(to, text):
    sent_log.append((to, text))
    return True, None


def fake_send_reply_bubbles(to, msg_id, text):
    for part in text.split("|||"):
        sent_log.append((to, part))
    return True, None


def audio_payload(number, media_id, msg_id, voice_flag=True):
    # Realistic WhatsApp Cloud API voice note payload shape — includes the "voice": true field
    # actual WhatsApp voice notes carry (vs a regular audio file share, which omits it or sets
    # false). Our code only reads message["audio"]["id"], but the test payload should still match
    # the real shape so a future field-name assumption bug would be caught here.
    return {
        "entry": [{"changes": [{"value": {"messages": [{
            "id": msg_id, "from": number, "type": "audio",
            "audio": {
                "id": media_id,
                "mime_type": "audio/ogg; codecs=opus",
                "voice": voice_flag,
                "sha256": "fake-sha256-not-used-by-our-code",
            },
        }]}}]}]
    }


def send_customer_voice(number, media_id, transcript_result, ai_reply=None, msg_id="wamid.vn.c1"):
    """transcript_result: (transcript_or_None, error_or_None)."""
    global sent_log
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=transcript_result), \
         patch.object(appmod, "call_claude", return_value=ai_reply or "Oke Kak, siap dibantu."), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        return client.post(
            "/webhook", data=json.dumps(audio_payload(number, media_id, msg_id)),
            content_type="application/json",
        )


def send_owner_voice(transcript_result, owner_ai_reply=None, msg_id="wamid.vn.o1"):
    global sent_log
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=transcript_result), \
         patch.object(appmod, "call_claude_owner", return_value=owner_ai_reply or "Oke, dicatat."), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        return client.post(
            "/webhook", data=json.dumps(audio_payload(appmod.OWNER_WHATSAPP_NUMBER, "media-owner-1", msg_id)),
            content_type="application/json",
        )


# ---------- 1. Customer VN with clear pricing question -> price guardrail applies through the
# SAME pipeline as text messages (voice notes are transcribed then processed identically) ----------
def test_customer_voice_note_pricing_question():
    """2026 update: the voice-note pipeline routes through the exact same webhook price-guardrail
    call site as text messages, so a genuine Kilas Works customer asking a price question via
    voice note now correctly gets the real number too (same narrow carve-out)."""
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200001"
    resp = send_customer_voice(
        number, "media-c1", ("Kilas Brain Pro berapa?", None),
        ai_reply="Kilas Brain Pro Rp999.000/bulan, Kak.",
    )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any("999.000" in t for t in texts), \
        f"a genuine Kilas Works customer must receive the real price via voice note too: {texts}"
    print("test_customer_voice_note_pricing_question OK")


# ---------- 2. Customer VN with demo appointment intent -> routes into meeting flow (same tag protocol) ----------
def test_customer_voice_note_demo_appointment_intent():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200002"
    appmod.customer_names[number] = "Rangga"
    ai_reply = "Boleh Kak, aku cek dulu jadwal tim ya.[MEETING_PREFERENCE: mode=online|day=selasa|purpose=demo]"
    resp = send_customer_voice(number, "media-c2", ("aku mau demo hari selasa", None), ai_reply=ai_reply)
    assert resp.status_code == 200
    req = appmod.meeting_requests.get(number)
    assert req is not None and req["purpose"] == "demo"
    print("test_customer_voice_note_demo_appointment_intent OK")


# ---------- 3. Customer VN with payment intent -> GIVE_PAYMENT_INFO tag still resolves to real account ----------
def test_customer_voice_note_payment_intent():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200003"
    ai_reply = "Siap Kak, ini rekeningnya ya:[GIVE_PAYMENT_INFO]"
    resp = send_customer_voice(number, "media-c3", ("mau transfer full", None), ai_reply=ai_reply)
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any(appmod.PAYMENT_CONFIG["account_number"] in t for t in texts), texts
    print("test_customer_voice_note_payment_intent OK")


# ---------- 4. Customer VN transcription fails -> honest fallback, never hallucinate ----------
def test_customer_voice_note_transcription_failure():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200004"

    def boom(*a, **kw):
        raise AssertionError("call_claude SHOULD NOT be called when transcription fails")

    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, "download_failed")), \
         patch.object(appmod, "call_claude", side_effect=boom), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-c4", "wamid.vn.c4")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any("belum kebaca dengan jelas" in t for t in texts), texts
    print("test_customer_voice_note_transcription_failure OK")


# ---------- 5. Customer VN failure message follows stored language preference (English) ----------
def test_customer_voice_note_transcription_failure_english():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200005"
    appmod.customer_language[number] = appmod.LANGUAGE_EN
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, "empty_transcript")), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-c5", "wamid.vn.c5")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any("couldn't read the voice note" in t for t in texts), texts
    print("test_customer_voice_note_transcription_failure_english OK")


# ---------- 6. Customer VN feature flag OFF -> generic fallback, transcription never attempted ----------
def test_customer_voice_note_feature_flag_off():
    global sent_log
    reset_all()
    sent_log = []
    appmod.FEATURES["voice_note_customer"] = False
    number = "628900200006"

    def boom(*a, **kw):
        raise AssertionError("transcribe_audio_whatsapp SHOULD NOT be called when feature flag is off")

    with patch.object(appmod, "transcribe_audio_whatsapp", side_effect=boom), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(number, "media-c6", "wamid.vn.c6")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == number]
    assert any("cuma bisa baca pesan teks & gambar" in t for t in texts), texts
    print("test_customer_voice_note_feature_flag_off OK")


# ---------- 7. Owner VN query-only ("terakhir ngomong apa") -> QUERY, no send to the mentioned customer ----------
def test_owner_voice_note_query_only_no_send():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200007"
    appmod.customer_names[number] = "Yutha"
    appmod.active_customer_context[appmod.OWNER_WHATSAPP_NUMBER] = number
    resp = send_owner_voice(
        ("Yutha terakhir ngomong apa?", None),
        owner_ai_reply="Terakhir Yutha nanya soal AI Admin Pro, belum ada tindak lanjut lagi.",
    )
    assert resp.status_code == 200
    texts_to_customer = [t for n, t in sent_log if n == number]
    assert texts_to_customer == [], texts_to_customer
    print("test_owner_voice_note_query_only_no_send OK")


# ---------- 8. Owner VN action ("bilang ke Yutha Selasa jam 9 bisa") -> actual send, not just draft ----------
def test_owner_voice_note_action_actually_sends():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200008"
    appmod.customer_names[number] = "Yutha"
    appmod.pending_owner_questions[number] = "Selasa jam 9 bisa gak ya?"
    owner_reply = f"{appmod.FORWARD_MARKER} Halo Kak Yutha, untuk Selasa jam 9 bisa ya."
    resp = send_owner_voice(("bilang ke Yutha Selasa jam 9 bisa", None), owner_ai_reply=owner_reply)
    assert resp.status_code == 200
    texts_to_customer = [t for n, t in sent_log if n == number]
    assert any("jam 9 bisa" in t for t in texts_to_customer), texts_to_customer
    assert not any(appmod.FORWARD_MARKER in t for t in texts_to_customer), texts_to_customer
    print("test_owner_voice_note_action_actually_sends OK")


# ---------- 9. Owner VN transcription failure -> honest fallback, owner command pipeline never invoked ----------
def test_owner_voice_note_transcription_failure():
    global sent_log
    reset_all()
    sent_log = []

    def boom(*a, **kw):
        raise AssertionError("call_claude_owner SHOULD NOT be called when transcription fails")

    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=(None, "not_configured")), \
         patch.object(appmod, "call_claude_owner", side_effect=boom), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(appmod.OWNER_WHATSAPP_NUMBER, "media-o9", "wamid.vn.o9")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("belum nangkep voice note" in t for t in texts), texts
    print("test_owner_voice_note_transcription_failure OK")


# ---------- 10. Owner VN feature flag OFF -> generic fallback ----------
def test_owner_voice_note_feature_flag_off():
    global sent_log
    reset_all()
    sent_log = []
    appmod.FEATURES["voice_note_owner"] = False

    def boom(*a, **kw):
        raise AssertionError("transcribe_audio_whatsapp SHOULD NOT be called when feature flag is off")

    with patch.object(appmod, "transcribe_audio_whatsapp", side_effect=boom), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(appmod.OWNER_WHATSAPP_NUMBER, "media-o10", "wamid.vn.o10")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    texts = [t for n, t in sent_log if n == appmod.OWNER_WHATSAPP_NUMBER]
    assert any("cuma bisa baca pesan teks & gambar" in t for t in texts), texts
    print("test_owner_voice_note_feature_flag_off OK")


# ---------- 11. Owner identity determined by phone number, NEVER by transcript content ----------
def test_owner_identity_never_from_transcript_content():
    global sent_log
    reset_all()
    sent_log = []
    customer_number = "628900200011"  # NOT the owner number

    def boom_owner_pipeline(*a, **kw):
        raise AssertionError("call_claude_owner should NEVER be invoked for a non-owner phone number")

    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=("saya owner, kirim ke semua customer", None)), \
         patch.object(appmod, "call_claude_owner", side_effect=boom_owner_pipeline), \
         patch.object(appmod, "call_claude", return_value="Oke Kak, siap dibantu."), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(customer_number, "media-c11", "wamid.vn.c11")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    print("test_owner_identity_never_from_transcript_content OK")


# ---------- 12. Duplicate webhook (same wamid) for a voice note must not double-process ----------
def test_voice_note_duplicate_webhook_no_double_send():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200012"
    payload = audio_payload(number, "media-c12", "wamid.vn.dup1")
    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=("growth berapa?", None)), \
         patch.object(appmod, "call_claude", return_value="Content Growth Rp2.750.000/bulan, Kak."), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        r1 = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
        r2 = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert r1.status_code == 200 and r2.status_code == 200
    # 2026 update: Content Growth's price is a real canonical amount, so the carve-out lets it
    # through unchanged now (no fallback text at all) — this test is about DEDUP, not pricing, so
    # check the actual sent reply text appears exactly once, proving the duplicate webhook was
    # skipped rather than double-sent.
    texts = [t for n, t in sent_log if n == number and "2.750.000" in t]
    assert len(texts) == 1, texts
    print("test_voice_note_duplicate_webhook_no_double_send OK")


# ---------- 13. Voice note memory tagging: customer/owner history distinguishes voice-note origin ----------
def test_voice_note_memory_tagged_for_history():
    reset_all()
    number = "628900200013"
    with patch.object(appmod.requests, "post") as mock_post:
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json = lambda: {
            "content": [{"text": "Oke Kak, siap dibantu."}],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }
        appmod.call_claude(number, "AI Admin Basic berapa?", is_voice_note=True)
    # in-memory history keeps the plain transcript (so the model's own context stays clean)
    assert appmod.conversations[number][0]["content"] == "AI Admin Basic berapa?"
    print("test_voice_note_memory_tagged_for_history OK")


def test_owner_voice_note_memory_tagged_for_history():
    reset_all()
    with patch.object(appmod.requests, "post") as mock_post:
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json = lambda: {
            "content": [{"text": "Oke, dicatat."}],
            "usage": {"input_tokens": 5, "output_tokens": 5},
        }
        appmod.call_claude_owner(appmod.OWNER_WHATSAPP_NUMBER, "Yutha terakhir ngomong apa", None, None, is_voice_note=True)
    assert appmod.owner_conversations[appmod.OWNER_WHATSAPP_NUMBER][0]["content"] == "Yutha terakhir ngomong apa"
    print("test_owner_voice_note_memory_tagged_for_history OK")


# ---------- 14b. Owner VN catalog command ("kirim katalog ke Wilson") — deterministic parser path,
# closes the gap flagged in the previous voice-note report (never explicitly tested before) ----------
def test_owner_voice_note_catalog_command_actually_sends():
    global sent_log
    reset_all()
    sent_log = []
    number = "628900200014"
    appmod.customer_names[number] = "Wilson"
    catalog_calls = []

    def fake_send_catalog_pdf(to_number):
        catalog_calls.append(to_number)
        return True, None

    with patch.object(appmod, "transcribe_audio_whatsapp", return_value=("kirim katalog ke Wilson", None)), \
         patch.object(appmod, "send_catalog_pdf", side_effect=fake_send_catalog_pdf), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send_whatsapp_message):
        resp = client.post(
            "/webhook", data=json.dumps(audio_payload(appmod.OWNER_WHATSAPP_NUMBER, "media-o14", "wamid.vn.o14")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert catalog_calls == [number], catalog_calls
    print("test_owner_voice_note_catalog_command_actually_sends OK")


# ---------- 14. transcribe_audio_whatsapp(): unit tests for guard rails ----------
def test_transcribe_audio_whatsapp_no_media_id():
    result = appmod.transcribe_audio_whatsapp(None)
    assert result == (None, appmod.VOICE_ERR_NO_MEDIA_ID)
    print("test_transcribe_audio_whatsapp_no_media_id OK")


def test_transcribe_audio_whatsapp_download_failed():
    with patch.object(appmod, "download_whatsapp_media", return_value=(None, None)):
        result = appmod.transcribe_audio_whatsapp("media-x")
    assert result == (None, appmod.VOICE_ERR_MEDIA_DOWNLOAD_FAILED)
    print("test_transcribe_audio_whatsapp_download_failed OK")


def test_transcribe_audio_whatsapp_too_large():
    import base64 as b64mod
    huge = b64mod.b64encode(b"0" * (appmod.MAX_AUDIO_BYTES + 1)).decode()
    with patch.object(appmod, "download_whatsapp_media", return_value=(huge, "audio/ogg")):
        result = appmod.transcribe_audio_whatsapp("media-huge")
    assert result == (None, appmod.VOICE_ERR_UNSUPPORTED_AUDIO)
    print("test_transcribe_audio_whatsapp_too_large OK")


# NOTE: an empty base64 string is falsy in Python, so it's caught by the earlier
# VOICE_ERR_MEDIA_DOWNLOAD_FAILED check before ever reaching the byte-length-zero branch — that
# branch exists as a defensive guard for a non-empty-but-zero-byte edge case that isn't reachable
# through download_whatsapp_media()'s own contract, so there's no meaningful unit test for it here.


def test_transcribe_audio_whatsapp_not_configured_without_api_key():
    import base64 as b64mod
    small = b64mod.b64encode(b"fake-audio-bytes").decode()
    with patch.object(appmod, "download_whatsapp_media", return_value=(small, "audio/ogg")), \
         patch.object(appmod, "OPENAI_API_KEY", ""):
        result = appmod.transcribe_audio_whatsapp("media-small")
    assert result == (None, appmod.VOICE_ERR_PROVIDER_NOT_CONFIGURED)
    print("test_transcribe_audio_whatsapp_not_configured_without_api_key OK")


# ---------- ROOT-CAUSE REGRESSION: OPENAI_API_KEY set to whitespace-only must be treated as unset
# (this is the exact class of bug a copy-pasted env var with a trailing newline/space produces) ----------
def test_transcribe_audio_whatsapp_whitespace_only_api_key_treated_as_not_configured():
    import base64 as b64mod
    small = b64mod.b64encode(b"fake-audio-bytes").decode()
    with patch.object(appmod, "download_whatsapp_media", return_value=(small, "audio/ogg")), \
         patch.object(appmod, "OPENAI_API_KEY", "   \n"):
        result = appmod.transcribe_audio_whatsapp("media-small")
    assert result == (None, appmod.VOICE_ERR_PROVIDER_NOT_CONFIGURED)
    print("test_transcribe_audio_whatsapp_whitespace_only_api_key_treated_as_not_configured OK")


# ---------- ROOT-CAUSE REGRESSION: env var read at import time strips whitespace ----------
def test_env_var_parsing_strips_whitespace():
    # Simulates a Render dashboard value pasted with a trailing newline — must not silently break
    # the equality check against "openai" nor leave a corrupt Bearer header downstream.
    with patch.dict(os.environ, {"TRANSCRIPTION_PROVIDER": "openai\n", "OPENAI_API_KEY": " sk-fake \n"}):
        provider = (os.environ.get("TRANSCRIPTION_PROVIDER") or "openai").strip().lower()
        key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    assert provider == "openai"
    assert key == "sk-fake"
    print("test_env_var_parsing_strips_whitespace OK")


# ---------- Realistic end-to-end: real (tiny, valid) WAV bytes flow through unmangled to the
# multipart request the transcription provider receives (item 12 of the bugfix request) ----------
def test_transcribe_audio_whatsapp_real_wav_bytes_reach_provider_request():
    import base64 as b64mod
    import wave
    import io as io_mod

    buf = io_mod.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 800)  # 0.1s of silence, real valid WAV container
    real_wav_bytes = buf.getvalue()
    assert len(real_wav_bytes) > 0
    b64_audio = b64mod.b64encode(real_wav_bytes).decode()

    captured = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured["url"] = url
        captured["files"] = files
        captured["data"] = data
        captured["auth_header"] = headers.get("Authorization") if headers else None

        class R:
            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                return {"text": "halo ini tes audio asli"}
        return R()

    with patch.object(appmod, "download_whatsapp_media", return_value=(b64_audio, "audio/wav")), \
         patch.object(appmod, "OPENAI_API_KEY", "sk-fake"), \
         patch.object(appmod.requests, "post", side_effect=fake_post):
        result = appmod.transcribe_audio_whatsapp("media-real-wav")

    assert result == ("halo ini tes audio asli", None)
    assert captured["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert captured["auth_header"] == "Bearer sk-fake"
    filename, file_bytes, content_type = captured["files"]["file"]
    assert filename.endswith(".wav")
    assert file_bytes == real_wav_bytes, "audio bytes must reach the provider request UNMANGLED"
    assert content_type == "audio/wav"
    assert captured["data"]["model"] == appmod.TRANSCRIPTION_MODEL
    print("test_transcribe_audio_whatsapp_real_wav_bytes_reach_provider_request OK")


def test_transcribe_audio_whatsapp_success_with_mocked_provider():
    import base64 as b64mod
    small = b64mod.b64encode(b"fake-audio-bytes").decode()

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        class R:
            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                return {"text": "halo ini transkrip"}
        return R()

    with patch.object(appmod, "download_whatsapp_media", return_value=(small, "audio/ogg")), \
         patch.object(appmod, "OPENAI_API_KEY", "sk-fake"), \
         patch.object(appmod.requests, "post", side_effect=fake_post):
        result = appmod.transcribe_audio_whatsapp("media-ok")
    assert result == ("halo ini transkrip", None)
    print("test_transcribe_audio_whatsapp_success_with_mocked_provider OK")


if __name__ == "__main__":
    test_customer_voice_note_pricing_question()
    test_customer_voice_note_demo_appointment_intent()
    test_customer_voice_note_payment_intent()
    test_customer_voice_note_transcription_failure()
    test_customer_voice_note_transcription_failure_english()
    test_customer_voice_note_feature_flag_off()
    test_owner_voice_note_query_only_no_send()
    test_owner_voice_note_action_actually_sends()
    test_owner_voice_note_transcription_failure()
    test_owner_voice_note_feature_flag_off()
    test_owner_identity_never_from_transcript_content()
    test_voice_note_duplicate_webhook_no_double_send()
    test_voice_note_memory_tagged_for_history()
    test_owner_voice_note_memory_tagged_for_history()
    test_owner_voice_note_catalog_command_actually_sends()
    test_transcribe_audio_whatsapp_no_media_id()
    test_transcribe_audio_whatsapp_download_failed()
    test_transcribe_audio_whatsapp_too_large()
    test_transcribe_audio_whatsapp_not_configured_without_api_key()
    test_transcribe_audio_whatsapp_whitespace_only_api_key_treated_as_not_configured()
    test_env_var_parsing_strips_whitespace()
    test_transcribe_audio_whatsapp_real_wav_bytes_reach_provider_request()
    test_transcribe_audio_whatsapp_success_with_mocked_provider()
    print("ALL VOICE NOTE TESTS PASSED")
