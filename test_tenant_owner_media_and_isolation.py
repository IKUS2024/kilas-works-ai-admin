"""Pro tenant owner assistant deepening cycle — regression tests for:

  1. Pro tenant owner voice-note parity: a Pro tenant's own configured owner can send a voice
     note, get it transcribed via the SAME transcribe_audio_whatsapp() pipeline Kilas Works' own
     owner uses, and have the transcript fed into the SAME tenant-scoped owner assistant
     (call_tenant_owner_ai) used for text — scoped strictly to that tenant, no internal
     tags/markers leaked. A Basic tenant owner's voice note gets a natural, non-technical decline
     (not silence).
  3. Pro tenant owner image parity: a Pro tenant owner's image (screenshot, payment-proof photo)
     is understood via the SAME vision-capable owner-assistant call, scoped to that tenant — never
     falls through to the normal CUSTOMER image path (which would misinterpret the owner's own
     image as an end-customer inquiry). A Basic tenant owner's image gets a natural decline.
  4. The owner-instruction classifier (classify_owner_message / _resolve_tenant_owner_relay_target)
     recognizes a wide variety of natural Indonesian "relay to a customer" phrasings, not just one
     magic verb — and asks a clarifying question instead of guessing when the intended customer is
     genuinely ambiguous.
  5. CRITICAL — pending_owner_questions is scoped by tenant_id+phone (via _ck), not phone alone:
     the same customer phone number can have a fully independent pending question in Tenant A and
     Tenant B without either leaking into the other's (or Kilas Works' own) owner data.

Run with:
    python3 test_tenant_owner_media_and_isolation.py
"""
import os
import sys
import json
from unittest.mock import patch, MagicMock

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.pop("DATABASE_URL", None)

import _test_bootstrap  # noqa: E402,F401 — must run before `import app`, see _test_bootstrap.py

_TMP_DB = _test_bootstrap.get_temp_db_path()  # SAME path _test_bootstrap already set up (never a second, separate tempfile)

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as chdb  # noqa: E402
import repo as chrepo  # noqa: E402
import security as chsecurity  # noqa: E402
import catalog_service  # noqa: E402
import subscription_service  # noqa: E402 (Fix 4 audit — helper below now backs test tenants with a subscription row)
import provisioning  # noqa: E402
import wa_project_bridge  # noqa: E402

_WA_ID_COUNTER = [0]


def _next_wamid():
    _WA_ID_COUNTER[0] += 1
    return f"wamid.tomi.{_WA_ID_COUNTER[0]}"


def reset_bot_state():
    appmod.conversations.clear()
    appmod.customer_names.clear()
    appmod.agreed_facts.clear()
    appmod.customer_language.clear()
    appmod.active_customer_context.clear()
    appmod._tenant_active_customer_context.clear()
    appmod.pending_owner_questions.clear()
    appmod.meeting_requests.clear()
    appmod.tenant_meeting_requests.clear()
    appmod.tenant_owner_conversations.clear()
    appmod.owner_conversations.clear()
    appmod.payment_state.clear()
    appmod.lead_stage.clear()
    appmod.followup_state.clear()
    appmod.PROCESSED_MESSAGE_IDS.clear()
    appmod.PROCESSED_MESSAGE_IDS_ORDER.clear()
    appmod._clear_active_whatsapp_channel()
    appmod.FEATURES["voice_note_customer"] = True
    appmod.FEATURES["voice_note_owner"] = True


def reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    chdb._local.conn = None
    chdb.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_active_tenant(phone_number_id, trusted_owner_phone, package="AI_ADMIN_PRO",
                         business_name=None, configure_channel=True, credentials_env_value="present"):
    name = business_name or f"Biz {phone_number_id}"
    user_id = chrepo.create_user(f"owner_{phone_number_id}@test.com", chsecurity.hash_password("password123"))
    business_id = chrepo.create_business(user_id, name, package=package)
    if package in ("AI_ADMIN_BASIC", "AI_ADMIN_PRO"):
        # Fix 4 audit — the live bot now requires a currently-operating subscription row to
        # resolve an AI Admin tenant (see app.py's _tenant_subscription_permits_ai_runtime_safe()).
        # Backfill one here so this test helper keeps producing a tenant that resolves exactly
        # like it did before that fix, for every test that doesn't care about subscription state.
        _sub_admin_id = chrepo.create_user(
            f"subadmin_{business_id}@kilasworks.id", chsecurity.hash_password("adminpass123"), role="KILAS_ADMIN"
        )
        subscription_service.create_subscription(
            business_id, "ai_admin_basic" if package == "AI_ADMIN_BASIC" else "ai_admin_pro",
            actor_user_id=_sub_admin_id,
        )
    chdb.execute(
        "UPDATE businesses SET status = 'ACTIVE', whatsapp_connected = ?, "
        "whatsapp_phone_number_id = ?, trusted_owner_phone = ? WHERE id = ?",
        (True, phone_number_id, trusted_owner_phone, business_id),
    )
    profile_fields = {
        "operating_hours": "Senin-Sabtu 09.00-18.00", "closed_days": "Minggu",
        "appointment_enabled": True, "appointment_rules_raw": "Booking H-1 minimal",
        "owner_name": trusted_owner_phone, "category": "Test", "primary_language": "id",
        "customer_salutation": "Kak",
    }
    chrepo.upsert_business_profile(business_id, profile_fields)
    chrepo.replace_business_services(business_id, ["Layanan utama"])
    chrepo.set_ai_status(business_id, "DONE")
    if configure_channel:
        credentials_reference = f"TEST_WA_TOKEN__TENANT_{business_id}"
        chrepo.upsert_whatsapp_config(business_id, phone_number_id, None, credentials_reference,
                                       connection_status="CONNECTED")
        if credentials_env_value is not None:
            os.environ[credentials_reference] = credentials_env_value
        else:
            os.environ.pop(credentials_reference, None)
    admin_id = chrepo.create_user(f"admin_{phone_number_id}@test.com", chsecurity.hash_password("password123"), role="KILAS_ADMIN")
    provisioning.provision_tenant(business_id, {"id": admin_id, "role": "KILAS_ADMIN"})
    return business_id


def _tenant_id_for(phone_number_id):
    row = chdb.query_one("SELECT id FROM businesses WHERE whatsapp_phone_number_id = ?", (phone_number_id,))
    return row["id"]


def _text_payload(from_number, text, phone_number_id=None):
    value = {
        "messages": [{"id": _next_wamid(), "from": from_number, "type": "text", "text": {"body": text}}],
    }
    if phone_number_id:
        value["metadata"] = {"phone_number_id": phone_number_id}
    return {"entry": [{"changes": [{"value": value}]}]}


def _audio_payload(from_number, media_id, phone_number_id=None):
    value = {
        "messages": [{
            "id": _next_wamid(), "from": from_number, "type": "audio",
            "audio": {"id": media_id, "mime_type": "audio/ogg; codecs=opus", "voice": True},
        }],
    }
    if phone_number_id:
        value["metadata"] = {"phone_number_id": phone_number_id}
    return {"entry": [{"changes": [{"value": value}]}]}


def _image_payload(from_number, media_id, caption=None, phone_number_id=None):
    image = {"id": media_id}
    if caption:
        image["caption"] = caption
    value = {
        "messages": [{"id": _next_wamid(), "from": from_number, "type": "image", "image": image}],
    }
    if phone_number_id:
        value["metadata"] = {"phone_number_id": phone_number_id}
    return {"entry": [{"changes": [{"value": value}]}]}


client = appmod.app.test_client()


# ---------------------------------------------------------------------------
# Task 1 — Pro tenant owner voice-note parity
# ---------------------------------------------------------------------------

def test_pro_tenant_owner_voice_note_gets_real_tenant_scoped_reply():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-vn-pro", "62894000001", business_name="Kopi Rina")

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "transcribe_audio_whatsapp", return_value=("capek banget hari ini", None)), \
         patch("requests.post") as mock_post, \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp_obj = MagicMock()
        resp_obj.raise_for_status.return_value = None
        resp_obj.json.return_value = {"content": [{"text": "Siap, semangat terus ya!"}]}
        mock_post.return_value = resp_obj
        resp = client.post(
            "/webhook",
            data=json.dumps(_audio_payload("62894000001", "media-vn-1", phone_number_id="pnid-vn-pro")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert sent, "a Pro tenant owner's voice note must get a real reply, not silence"
    assert sent[-1] == ("62894000001", "Siap, semangat terus ya!")
    for (_to, text) in sent:
        for marker in ("[OWNER VOICE NOTE]", "[ACTION", "[STATE", "OWNER_ACTION"):
            assert marker not in text, f"internal marker leaked to owner: {text!r}"

    tenant_id = _tenant_id_for("pnid-vn-pro")
    scoped_key = appmod._ck(tenant_id, "62894000001")
    assert scoped_key in appmod.tenant_owner_conversations, "must use the tenant-scoped owner history, not Kilas Works' own"
    assert "62894000001" not in appmod.owner_conversations
    print("test_pro_tenant_owner_voice_note_gets_real_tenant_scoped_reply OK")


def test_basic_tenant_owner_voice_note_gets_natural_decline():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-vn-basic", "62894000002", package="AI_ADMIN_BASIC")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "transcribe_audio_whatsapp") as mock_transcribe, \
         patch("requests.post") as mock_post, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/webhook",
            data=json.dumps(_audio_payload("62894000002", "media-vn-2", phone_number_id="pnid-vn-basic")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_transcribe.called, "Basic tenant owner must never even reach transcription"
    assert not mock_post.called
    assert mock_send.called, "Basic tenant owner must get a natural decline, never silence"
    reply = mock_send.call_args[0][1].lower()
    assert "feature" not in reply and "flag" not in reply and "false" not in reply
    print("test_basic_tenant_owner_voice_note_gets_natural_decline OK")


# ---------------------------------------------------------------------------
# Task 3 — Pro tenant owner image parity
# ---------------------------------------------------------------------------

def test_pro_tenant_owner_image_handled_via_owner_path_scoped_to_tenant():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-img-pro", "62894000003", business_name="Salon Dewi")

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "download_whatsapp_media", return_value=("YmFzZTY0aW1n", "image/jpeg")), \
         patch.object(appmod, "call_claude") as mock_customer_ai, \
         patch("requests.post") as mock_post, \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp_obj = MagicMock()
        resp_obj.raise_for_status.return_value = None
        resp_obj.json.return_value = {"content": [{"text": "Oke, itu bukti transfernya sudah aku lihat."}]}
        mock_post.return_value = resp_obj
        resp = client.post(
            "/webhook",
            data=json.dumps(_image_payload("62894000003", "media-img-1", caption="ini bukti transfer dari Budi",
                                            phone_number_id="pnid-img-pro")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_customer_ai.called, "an owner's own image must NEVER be routed through the normal customer image path"
    assert sent and sent[-1][1] == "Oke, itu bukti transfernya sudah aku lihat."

    # Vision must use the vision-capable model (Sonnet), reusing the SAME image-understanding call
    # shape call_claude_owner() uses for Kilas Works' own owner (never Haiku for vision).
    called_model = mock_post.call_args.kwargs["json"]["model"]
    assert called_model == appmod.MODEL_PRIMARY

    tenant_id = _tenant_id_for("pnid-img-pro")
    scoped_key = appmod._ck(tenant_id, "62894000003")
    assert scoped_key in appmod.tenant_owner_conversations
    assert "62894000003" not in appmod.owner_conversations
    print("test_pro_tenant_owner_image_handled_via_owner_path_scoped_to_tenant OK")


def test_basic_tenant_owner_image_gets_natural_decline():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-img-basic", "62894000004", package="AI_ADMIN_BASIC")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "download_whatsapp_media") as mock_download, \
         patch.object(appmod, "call_claude") as mock_customer_ai, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/webhook",
            data=json.dumps(_image_payload("62894000004", "media-img-2", phone_number_id="pnid-img-basic")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_download.called, "Basic tenant owner must never even download the image"
    assert not mock_customer_ai.called
    assert mock_send.called
    reply = mock_send.call_args[0][1].lower()
    assert "feature" not in reply and "flag" not in reply and "false" not in reply
    print("test_basic_tenant_owner_image_gets_natural_decline OK")


# ---------------------------------------------------------------------------
# Task 4 — natural-language variety in the owner-command classifier
# ---------------------------------------------------------------------------

def test_classifier_recognizes_verb_variants_as_owner_action():
    variants = [
        "Bales Budi bilang stoknya ada.",
        "Follow up yang kemarin.",
        "Tanyain jadi booking atau enggak.",
        "Terusin ke customer tadi.",
        "Ingetin dia besok jam 3.",
    ]
    for text in variants:
        kind = wa_project_bridge.classify_owner_message(text)
        assert kind == "OWNER_ACTION", f"{text!r} should classify as OWNER_ACTION, got {kind}"
    # A real question must still classify as a query, not get swept into ACTION by a loose match.
    assert wa_project_bridge.classify_owner_message("project Rina gimana progressnya?") == "OWNER_QUERY"
    print("test_classifier_recognizes_verb_variants_as_owner_action OK")


def test_pro_tenant_owner_relay_via_new_verb_variants_end_to_end():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-verb-a", "62894000005", business_name="Toko Sari")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899777001", "halo", phone_number_id="pnid-verb-a")), content_type="application/json")
    tenant_id = _tenant_id_for("pnid-verb-a")
    appmod.customer_names[appmod._ck(tenant_id, "62899777001")] = "Budi"

    for owner_text in ["Bales Budi bilang stoknya ada", "Ingetin Budi besok jam 3"]:
        sent = []

        def fake_send(to, text):
            sent.append((to, text))
            return True, None

        with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
             patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
            resp = client.post(
                "/webhook",
                data=json.dumps(_text_payload("62894000005", owner_text, phone_number_id="pnid-verb-a")),
                content_type="application/json",
            )
        assert resp.status_code == 200
        forwarded = [t for (to, t) in sent if to == "62899777001"]
        assert forwarded, f"{owner_text!r} should have triggered a relay to Budi"
    print("test_pro_tenant_owner_relay_via_new_verb_variants_end_to_end OK")


def test_ambiguous_relay_target_asks_clarifying_question_instead_of_guessing():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-ambig-a", "62894000006", business_name="Studio Foto")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899777002", "halo dari budi", phone_number_id="pnid-ambig-a")), content_type="application/json")
        client.post("/webhook", data=json.dumps(_text_payload("62899777003", "halo dari sari", phone_number_id="pnid-ambig-a")), content_type="application/json")
    tenant_id = _tenant_id_for("pnid-ambig-a")
    appmod.customer_names[appmod._ck(tenant_id, "62899777002")] = "Budi"
    appmod.customer_names[appmod._ck(tenant_id, "62899777003")] = "Sari"

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62894000006", "bales Budi dan Sari bilang udah beres", phone_number_id="pnid-ambig-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not any(to in ("62899777002", "62899777003") for (to, _t) in sent), "must NOT guess and forward when ambiguous"
    assert sent and sent[-1][0] == "62894000006"
    assert "?" in sent[-1][1]
    print("test_ambiguous_relay_target_asks_clarifying_question_instead_of_guessing OK")


# ---------------------------------------------------------------------------
# Task 5 — CRITICAL: pending_owner_questions scoped by tenant, not phone alone
# ---------------------------------------------------------------------------

def test_pending_owner_question_isolated_between_tenants_same_customer_phone():
    reset_client_hub_db()
    reset_bot_state()
    tenant_a = _make_active_tenant("pnid-pend-a", "62894000007", business_name="Kopi Rina")
    tenant_b = _make_active_tenant("pnid-pend-b", "62894000008", business_name="Salon Dewi")
    shared_customer_phone = "62899888000"

    # Same customer phone number asks something that needs owner escalation in BOTH tenants.
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="[TANYA_OWNER]Belum yakin nih."), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload(shared_customer_phone, "pertanyaan susah A", phone_number_id="pnid-pend-a")), content_type="application/json")
        client.post("/webhook", data=json.dumps(_text_payload(shared_customer_phone, "pertanyaan susah B", phone_number_id="pnid-pend-b")), content_type="application/json")

    key_a = appmod._ck(tenant_a, shared_customer_phone)
    key_b = appmod._ck(tenant_b, shared_customer_phone)
    assert key_a in appmod.pending_owner_questions
    assert key_b in appmod.pending_owner_questions
    assert appmod.pending_owner_questions[key_a] != appmod.pending_owner_questions[key_b] or (
        "pertanyaan susah A" in appmod.pending_owner_questions[key_a]
        and "pertanyaan susah B" in appmod.pending_owner_questions[key_b]
    )
    assert shared_customer_phone not in appmod.pending_owner_questions, "the plain unscoped phone number must never be used as a key"

    # Tenant B's slice must never contain Tenant A's pending question, and vice versa.
    only_b = appmod._pending_owner_questions_for_tenant(tenant_b)
    only_a = appmod._pending_owner_questions_for_tenant(tenant_a)
    assert shared_customer_phone in only_a and only_a[shared_customer_phone] == "pertanyaan susah A"
    assert shared_customer_phone in only_b and only_b[shared_customer_phone] == "pertanyaan susah B"

    # Kilas Works' own owner (tenant_id=None) must see NEITHER tenant's pending question.
    kilas_only = appmod._pending_owner_questions_for_tenant(None)
    assert shared_customer_phone not in kilas_only
    print("test_pending_owner_question_isolated_between_tenants_same_customer_phone OK")


def test_kilas_owner_fifo_fallback_never_picks_up_a_tenant_pending_question():
    reset_client_hub_db()
    reset_bot_state()
    tenant_a = _make_active_tenant("pnid-pend-c", "62894000009", business_name="Kopi Rina")

    # Only a TENANT's customer has a pending question — Kilas Works itself has none.
    appmod.pending_owner_questions[appmod._ck(tenant_a, "62899888111")] = "pertanyaan tenant"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post") as mock_post, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send:
        resp_obj = MagicMock()
        resp_obj.raise_for_status.return_value = None
        resp_obj.json.return_value = {"content": [{"text": "Oke, sudah aku catat."}]}
        mock_post.return_value = resp_obj
        # Kilas Works' own owner sends a vague pronoun-only message, no explicit name/number.
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload(appmod.OWNER_WHATSAPP_NUMBER, "gimana ya soal itu",
                                           phone_number_id=appmod.WHATSAPP_PHONE_NUMBER_ID)),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_send.called
    # The tenant's pending question must remain untouched — Kilas Works' own owner branch never
    # consumed/popped it via the FIFO fallback.
    assert appmod._ck(tenant_a, "62899888111") in appmod.pending_owner_questions
    print("test_kilas_owner_fifo_fallback_never_picks_up_a_tenant_pending_question OK")


if __name__ == "__main__":
    test_pro_tenant_owner_voice_note_gets_real_tenant_scoped_reply()
    test_basic_tenant_owner_voice_note_gets_natural_decline()
    test_pro_tenant_owner_image_handled_via_owner_path_scoped_to_tenant()
    test_basic_tenant_owner_image_gets_natural_decline()
    test_classifier_recognizes_verb_variants_as_owner_action()
    test_pro_tenant_owner_relay_via_new_verb_variants_end_to_end()
    test_ambiguous_relay_target_asks_clarifying_question_instead_of_guessing()
    test_pending_owner_question_isolated_between_tenants_same_customer_phone()
    test_kilas_owner_fifo_fallback_never_picks_up_a_tenant_pending_question()
    print("\nALL TENANT OWNER MEDIA + ISOLATION TESTS PASSED")
