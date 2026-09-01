"""Test tambahan khusus VOICE NOTE PRODUCTION BUG cycle 3 (landing page + voice note masih gagal
di production walau OPENAI_API_KEY sudah ditambahkan). File TERPISAH dari test_voice_note.py (yang
sudah lengkap dari cycle sebelumnya) supaya diff/scope perubahan gampang direview.

Fokus test di sini:
1. Audio format REPRESENTATIF (OGG/Opus asli, bukan cuma string transcript yang di-mock) benar2
   sampai ke request provider tanpa rusak/kepotong.
2. MIME "audio/ogg; codecs=opus" (format asli WhatsApp voice note) TETAP diproses, tidak ditolak.
3. Error billing/quota OpenAI (API key BENAR tapi akun belum ada credit) dikategorikan SPESIFIK
   sebagai BILLING_OR_QUOTA_ERROR, bukan disamarkan jadi TRANSCRIPTION_API_ERROR generik.
4. Error API key salah/invalid dikategorikan sebagai TRANSCRIPTION_API_ERROR (BUKAN billing).
5. stage=webhook_received dan stage=route_after_transcript benar2 ke-emit (lewat capsys) — ini
   yang dipakai buat verifikasi production logs beneran menunjukkan tahap yang gagal.
"""
import os, json, io, struct
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


def _minimal_real_ogg_bytes():
    """Bangun satu OGG page header YANG VALID secara struktur (capture pattern 'OggS', version,
    header_type, granule_position, serial_number, page_sequence, checksum, segment_table) plus
    payload dummy — INI BUKAN string mock, ini byte container OGG asli yang bisa di-parse sebagai
    OGG oleh tool manapun (walau isi Opus datanya dummy, bukan audio yang bisa didengar). Tujuannya
    membuktikan pipeline base64 encode/decode + kirim ke provider TIDAK merusak/memotong bytes,
    yang tidak bisa dibuktikan cuma dengan mock string transcript.
    """
    payload = b"\x01\x13OpusHead" + b"\x00" * 10  # dummy opus identification-ish payload
    header = (
        b"OggS"                       # capture pattern
        + bytes([0])                  # version
        + bytes([0x02])               # header_type (beginning of stream)
        + struct.pack("<q", 0)        # granule position
        + struct.pack("<I", 12345)    # serial number
        + struct.pack("<I", 0)        # page sequence number
        + struct.pack("<I", 0)        # checksum (dummy, not recalculated — fine for this test)
        + bytes([1])                  # number of page segments
        + bytes([len(payload)])       # segment table
    )
    return header + payload


def _fake_openai_success(transcript_text):
    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        class R:
            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                return {"text": transcript_text}
        return R()
    return fake_post


def _fake_openai_http_error(status_code, error_type, error_code=None, message="error"):
    import requests

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        class FakeResp:
            def __init__(self):
                self.status_code = status_code

            def raise_for_status(self_inner):
                err = requests.HTTPError(f"{status_code} error")
                err.response = self_inner
                raise err

            def json(self_inner):
                return {"error": {"type": error_type, "code": error_code, "message": message}}
        return FakeResp()
    return fake_post


# ---------- 1. Real OGG/Opus-shaped bytes reach the provider request completely unmangled ----------
def test_transcribe_real_ogg_opus_bytes_reach_provider_request():
    real_ogg_bytes = _minimal_real_ogg_bytes()
    assert real_ogg_bytes[:4] == b"OggS"
    import base64 as b64mod
    b64_audio = b64mod.b64encode(real_ogg_bytes).decode()

    captured = {}

    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        captured["files"] = files
        captured["data"] = data

        class R:
            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                return {"text": "halo ini tes voice note asli"}
        return R()

    # MIME persis seperti yang WhatsApp Cloud API kirim untuk voice note asli.
    with patch.object(appmod, "download_whatsapp_media", return_value=(b64_audio, "audio/ogg; codecs=opus")), \
         patch.object(appmod, "OPENAI_API_KEY", "sk-fake"), \
         patch.object(appmod.requests, "post", side_effect=fake_post):
        result = appmod.transcribe_audio_whatsapp("media-real-ogg")

    assert result == ("halo ini tes voice note asli", None)
    filename, file_bytes, content_type = captured["files"]["file"]
    assert filename.endswith(".ogg"), filename
    assert file_bytes == real_ogg_bytes, "bytes audio berubah/kepotong di tengah pipeline"
    # content_type yang dikirim ke provider harus base MIME yang sudah dinormalisasi (tanpa
    # "; codecs=opus"), bukan string mentahnya — itu sebabnya normalisasi base_mime penting.
    assert content_type == "audio/ogg", content_type
    print("test_transcribe_real_ogg_opus_bytes_reach_provider_request OK")


# ---------- 2. MIME "audio/ogg; codecs=opus" tidak ditolak / tidak mempengaruhi hasil ----------
def test_mime_with_codecs_suffix_not_rejected():
    import base64 as b64mod
    b64_audio = b64mod.b64encode(b"dummy-audio-bytes-not-empty").decode()
    with patch.object(appmod, "download_whatsapp_media", return_value=(b64_audio, "audio/ogg; codecs=opus")), \
         patch.object(appmod, "OPENAI_API_KEY", "sk-fake"), \
         patch.object(appmod.requests, "post", side_effect=_fake_openai_success("oke")):
        result = appmod.transcribe_audio_whatsapp("media-codecs")
    assert result == ("oke", None), result
    print("test_mime_with_codecs_suffix_not_rejected OK")


# ---------- 3. Billing/quota error dikategorikan spesifik, BUKAN generic API error ----------
def test_billing_or_quota_error_categorized_specifically():
    import base64 as b64mod
    b64_audio = b64mod.b64encode(b"dummy-audio-bytes-not-empty").decode()
    with patch.object(appmod, "download_whatsapp_media", return_value=(b64_audio, "audio/ogg")), \
         patch.object(appmod, "OPENAI_API_KEY", "sk-fake-but-no-billing"), \
         patch.object(appmod.requests, "post", side_effect=_fake_openai_http_error(
             429, "insufficient_quota", error_code="insufficient_quota",
             message="You exceeded your current quota, please check your plan and billing details.",
         )):
        result = appmod.transcribe_audio_whatsapp("media-billing")
    assert result == (None, appmod.VOICE_ERR_BILLING_OR_QUOTA), result
    print("test_billing_or_quota_error_categorized_specifically OK")


# ---------- 4. Invalid API key error dikategorikan sebagai API error biasa (BUKAN billing) ----------
def test_invalid_api_key_error_categorized_as_api_error_not_billing():
    import base64 as b64mod
    b64_audio = b64mod.b64encode(b"dummy-audio-bytes-not-empty").decode()
    with patch.object(appmod, "download_whatsapp_media", return_value=(b64_audio, "audio/ogg")), \
         patch.object(appmod, "OPENAI_API_KEY", "sk-invalid"), \
         patch.object(appmod.requests, "post", side_effect=_fake_openai_http_error(
             401, "invalid_request_error", error_code="invalid_api_key", message="Incorrect API key provided.",
         )):
        result = appmod.transcribe_audio_whatsapp("media-badkey")
    assert result == (None, appmod.VOICE_ERR_API_ERROR), result
    print("test_invalid_api_key_error_categorized_as_api_error_not_billing OK")


# ---------- 5. stage=webhook_received & stage=route_after_transcript benar2 muncul di log ----------
def test_webhook_received_and_route_after_transcript_stages_logged():
    import contextlib

    reset_all()
    from test_voice_note import audio_payload  # reuse existing payload builder, no duplicate logic

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), \
         patch.object(appmod, "transcribe_audio_whatsapp", return_value=("halo test log", None)), \
         patch.object(appmod, "call_claude", return_value="Oke Kak."), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)), \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "notify_owner_new_message", return_value=None):
        client.post(
            "/webhook", data=json.dumps(audio_payload("628900999888", "media-log-test", "wamid.logtest.1")),
            content_type="application/json",
        )
    output = buf.getvalue()
    assert "VOICE_DEBUG: stage=webhook_received" in output, output
    assert "sender_role=CUSTOMER" in output, output
    assert "VOICE_DEBUG: stage=route_after_transcript" in output, output
    assert "target=customer" in output, output
    print("test_webhook_received_and_route_after_transcript_stages_logged OK")


if __name__ == "__main__":
    test_transcribe_real_ogg_opus_bytes_reach_provider_request()
    test_mime_with_codecs_suffix_not_rejected()
    test_billing_or_quota_error_categorized_specifically()
    test_invalid_api_key_error_categorized_as_api_error_not_billing()
    test_webhook_received_and_route_after_transcript_stages_logged()
    print("ALL VOICE NOTE PRODUCTION BUGFIX TESTS PASSED")
