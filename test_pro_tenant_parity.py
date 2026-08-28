"""Pro tenant parity cycle — regression tests for the 11 tasks fixed in this cycle:

  1. A Pro tenant's own recognized owner gets the same category of rich, natural owner-assistant
     conversation Kilas Works' own owner gets (query/action/internal-note), scoped strictly to
     that tenant's own data, never leaking raw internal tags to the owner or a customer.
  2. A Basic tenant's owner is recognized AS the owner (never treated like a plain customer) but
     denied the Pro-only owner assistant, with a natural (non-technical) decline.
  3. Pro tenant appointment booking (request/reschedule/cancel) is wired to that tenant's OWN
     business hours/appointment-enabled toggle/rules, scoped by tenant_id+phone; a Basic tenant (or
     appointment-disabled Pro tenant) never gets it.
  4. Pro tenant payment conversation answers with THAT tenant's OWN bank details (never Kilas
     Works' BCA account); a Basic tenant (or unconfigured Pro tenant) gets a natural fallback.
  5. Client Hub tenant config schema/service actually has appointment + payment settings fields.
  6. The thread-local active-WhatsApp-channel override is always cleared (finally block; never
     leaks between a tenant webhook, another tenant's webhook, the internal owner-notify endpoint,
     or an exception mid-request).
  7. An unrecognized WhatsApp Phone Number ID is never treated as Kilas Works by default, and a
     tenant-lookup failure degrades the same way (no reply, no Kilas fallback), not a crash.
  9. Appointment state and payment-conversation state stay fully isolated between two tenants for
     the identical customer phone number (extends test_multi_tenant_runtime_safety.py's coverage).
  10. An owner-phone collision between Kilas Works' own owner and a tenant's owner is decided by
      channel+phone, never phone alone (see also test_business_hub_v2_whatsapp_integration.py).
  11. Runtime Basic vs Pro feature matrix parity, including the Task-1 owner assistant / appointment
      / payment / voice / image / human takeover.

Run with:
    python3 test_pro_tenant_parity.py
"""
import os
import sys
import json
import tempfile
from unittest.mock import patch, MagicMock

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.pop("DATABASE_URL", None)

import app as appmod  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub"))
import db as chdb  # noqa: E402
import repo as chrepo  # noqa: E402
import security as chsecurity  # noqa: E402
import catalog_service  # noqa: E402
import provisioning  # noqa: E402
import tenant_config_service as tcs  # noqa: E402

_WA_ID_COUNTER = [0]


def _next_wamid():
    _WA_ID_COUNTER[0] += 1
    return f"wamid.ptp.{_WA_ID_COUNTER[0]}"


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
    appmod.payment_state.clear()
    appmod.lead_stage.clear()
    appmod.followup_state.clear()
    appmod.PROCESSED_MESSAGE_IDS.clear()
    appmod.PROCESSED_MESSAGE_IDS_ORDER.clear()
    appmod._clear_active_whatsapp_channel()


def reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    chdb._local.conn = None
    chdb.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_active_tenant(phone_number_id, trusted_owner_phone, package="AI_ADMIN_PRO",
                         business_name=None, configure_channel=True, credentials_env_value="present",
                         appointment_enabled=True, business_hours="Senin-Sabtu 09.00-18.00",
                         payment=None):
    """Same shape as test_multi_tenant_runtime_safety.py's helper, extended with the new
    appointment/payment profile fields this cycle adds."""
    name = business_name or f"Biz {phone_number_id}"
    user_id = chrepo.create_user(f"owner_{phone_number_id}@test.com", chsecurity.hash_password("password123"))
    business_id = chrepo.create_business(user_id, name, package=package)
    chdb.execute(
        "UPDATE businesses SET status = 'ACTIVE', whatsapp_connected = ?, "
        "whatsapp_phone_number_id = ?, trusted_owner_phone = ? WHERE id = ?",
        (True, phone_number_id, trusted_owner_phone, business_id),
    )
    profile_fields = {
        "operating_hours": business_hours, "closed_days": "Minggu",
        "appointment_enabled": appointment_enabled, "appointment_rules_raw": "Booking H-1 minimal",
        "owner_name": trusted_owner_phone, "category": "Test", "primary_language": "id",
        "customer_salutation": "Kak",
    }
    if payment:
        profile_fields.update(payment)
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
    # Materialize the tenant config snapshot (business_name/knowledge/etc — appointment/payment
    # settings themselves are read LIVE from business_profiles, see tenant_config_service.py, so
    # this step isn't required for THOSE, but IS required for business_name/catalog/FAQ to appear
    # in the owner assistant's context), same as what an admin's "approve" step does in production.
    admin_id = chrepo.create_user(f"admin_{phone_number_id}@test.com", chsecurity.hash_password("password123"), role="KILAS_ADMIN")
    provisioning.provision_tenant(business_id, {"id": admin_id, "role": "KILAS_ADMIN"})
    return business_id


def _text_payload(from_number, text, phone_number_id=None):
    value = {
        "messages": [{"id": _next_wamid(), "from": from_number, "type": "text", "text": {"body": text}}],
    }
    if phone_number_id:
        value["metadata"] = {"phone_number_id": phone_number_id}
    return {"entry": [{"changes": [{"value": value}]}]}


def _fake_claude_post(reply_text):
    def _fake(url, headers=None, json=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"content": [{"text": reply_text}]}
        return resp
    return _fake


client = appmod.app.test_client()


# ---------------------------------------------------------------------------
# Task 1 — rich, natural, tenant-scoped owner assistant
# ---------------------------------------------------------------------------

def test_pro_tenant_owner_internal_note_gets_a_real_reply_not_silence():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t1-a", "62891000001")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Siap, dicatat ya.")), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62891000001", "capek banget hari ini banyak orderan", phone_number_id="pnid-t1-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_send.called, "an internal note/thinking-out-loud must still get a real reply, never silence"
    assert mock_send.call_args[0][1] == "Siap, dicatat ya."
    print("test_pro_tenant_owner_internal_note_gets_a_real_reply_not_silence OK")


def test_pro_tenant_owner_query_scoped_to_own_customers_only():
    reset_client_hub_db()
    reset_bot_state()
    tenant_a = _make_active_tenant("pnid-t1-b", "62891000002", business_name="Kopi Rina")
    tenant_b = _make_active_tenant("pnid-t1-c", "62891000003", business_name="Salon Dewi")

    # Two different tenants' customers chat first, so each tenant has its own customer on record.
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo, ada yang bisa dibantu?"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899555001", "halo dari kopi", phone_number_id="pnid-t1-b")), content_type="application/json")
        client.post("/webhook", data=json.dumps(_text_payload("62899555002", "halo dari salon", phone_number_id="pnid-t1-c")), content_type="application/json")

    captured = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append(json["system"])
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"content": [{"text": "Ada 1 customer aktif."}]}
        return resp

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=fake_post), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62891000002", "ada customer yang serius hari ini?", phone_number_id="pnid-t1-b")),
            content_type="application/json",
        )
    assert captured, "owner query must call the AI"
    system_prompt = captured[0]
    assert "62899555001" in system_prompt, "this tenant's own customer must be in scope"
    assert "62899555002" not in system_prompt, "the OTHER tenant's customer must never leak into this system prompt"
    assert "Kopi Rina" in system_prompt and "Salon Dewi" not in system_prompt
    print("test_pro_tenant_owner_query_scoped_to_own_customers_only OK")


def test_pro_tenant_owner_relay_forwards_plain_instruction_to_named_customer():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t1-d", "62891000004", business_name="Toko Budi")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo, ada yang bisa dibantu?"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899555003", "halo", phone_number_id="pnid-t1-d")), content_type="application/json")
    appmod.customer_names[appmod._ck(_tenant_id_for("pnid-t1-d"), "62899555003")] = "Budi"

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62891000004", "bales si Budi bilang stoknya ada", phone_number_id="pnid-t1-d")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    forwarded = [t for (to, t) in sent if to == "62899555003"]
    assert forwarded, "the named customer must receive the relayed message"
    assert "stoknya ada" in forwarded[0]
    # Never leak internal tags/markers into what the customer or owner sees.
    for (_to, text) in sent:
        for marker in ("[ACTION", "[STATE", "PESAN_UNTUK_CUSTOMER", "OWNER_ACTION"):
            assert marker not in text
    print("test_pro_tenant_owner_relay_forwards_plain_instruction_to_named_customer OK")


def _tenant_id_for(phone_number_id):
    row = chdb.query_one("SELECT id FROM businesses WHERE whatsapp_phone_number_id = ?", (phone_number_id,))
    return row["id"]


# ---------------------------------------------------------------------------
# Task 2 — Basic tenant owner recognized but denied, naturally
# ---------------------------------------------------------------------------

def test_basic_tenant_owner_recognized_not_treated_as_customer():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t2-a", "62892000001", package="AI_ADMIN_BASIC")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_customer_ai, \
         patch("requests.post") as mock_ai_post, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62892000001", "ada customer yang serius hari ini?", phone_number_id="pnid-t2-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_customer_ai.called, "must never be routed through the normal customer AI path"
    assert not mock_ai_post.called, "Basic tenant owner must not reach the Pro owner-AI call at all"
    assert mock_send.called
    reply = mock_send.call_args[0][1].lower()
    assert "feature" not in reply and "flag" not in reply and "false" not in reply
    print("test_basic_tenant_owner_recognized_not_treated_as_customer OK")


# ---------------------------------------------------------------------------
# Task 3 — Pro tenant appointment flow uses THAT tenant's own settings
# ---------------------------------------------------------------------------

def test_pro_tenant_appointment_request_uses_own_business_hours_and_notifies_own_owner():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t3-a", "62893000001", business_hours="Senin-Jumat 10.00-20.00")

    captured_prompts = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_prompts.append(json["system"])
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "content": [{"text": "Oke aku catat dulu ya.[MEETING_PREFERENCE: day=besok|time=14:00]"}]
        }
        return resp

    notified = []

    def fake_send(to, text):
        notified.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=fake_post), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555010", "mau booking besok jam 2 siang", phone_number_id="pnid-t3-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert "10.00-20.00" in captured_prompts[0], "the customer prompt must carry THIS tenant's own business hours"
    tenant_id = _tenant_id_for("pnid-t3-a")
    scoped_key = appmod._ck(tenant_id, "62899555010")
    assert scoped_key in appmod.tenant_meeting_requests, "appointment request must be recorded, scoped by tenant+phone"
    assert appmod.tenant_meeting_requests[scoped_key]["status"] == "REQUESTED"
    owner_notified = [t for (to, t) in notified if to == "62893000001"]
    assert owner_notified, "this tenant's OWN owner must be notified of the booking request"
    print("test_pro_tenant_appointment_request_uses_own_business_hours_and_notifies_own_owner OK")


def test_basic_tenant_appointment_stays_unavailable():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t3-b", "62893000002", package="AI_ADMIN_BASIC")
    import feature_flags
    assert feature_flags.FEATURE_MATRIX["AI_ADMIN_BASIC"]["appointment"] is False

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post(
             "Oke aku catat.[MEETING_PREFERENCE: day=besok|time=14:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555011", "mau booking besok", phone_number_id="pnid-t3-b")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    tenant_id = _tenant_id_for("pnid-t3-b")
    scoped_key = appmod._ck(tenant_id, "62899555011")
    assert scoped_key not in appmod.tenant_meeting_requests, "Basic tenant must never actually book an appointment"
    reply_text = mock_bubbles.call_args[0][2]
    assert "hubungi langsung" in reply_text
    print("test_basic_tenant_appointment_stays_unavailable OK")


def test_appointment_disabled_pro_tenant_still_blocked_despite_pro_package():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t3-c", "62893000003", package="AI_ADMIN_PRO", appointment_enabled=False)

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post(
             "Oke aku catat.[MEETING_PREFERENCE: day=besok|time=14:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555012", "mau booking besok", phone_number_id="pnid-t3-c")),
            content_type="application/json",
        )
    tenant_id = _tenant_id_for("pnid-t3-c")
    scoped_key = appmod._ck(tenant_id, "62899555012")
    assert scoped_key not in appmod.tenant_meeting_requests, "a Pro tenant that opted OUT of appointments must not book one"
    print("test_appointment_disabled_pro_tenant_still_blocked_despite_pro_package OK")


# ---------------------------------------------------------------------------
# Task 4 — Pro tenant payment conversation uses THAT tenant's own bank details
# ---------------------------------------------------------------------------

def test_pro_tenant_payment_conversation_uses_own_bank_details_never_kilas_bca():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant(
        "pnid-t4-a", "62894000001",
        payment={"payment_bank_name": "Mandiri", "payment_account_number": "1234567890",
                  "payment_account_name": "Toko Budi Jaya", "payment_instructions": "Kirim bukti transfer ya."},
    )

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Boleh, ini rekeningnya ya.[GIVE_PAYMENT_INFO]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555020", "transfernya ke mana ya", phone_number_id="pnid-t4-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    reply_text = mock_bubbles.call_args[0][2]
    assert "Mandiri" in reply_text and "1234567890" in reply_text and "Toko Budi Jaya" in reply_text
    assert appmod.PAYMENT_CONFIG["account_number"] not in reply_text, "must NEVER contain Kilas Works' own BCA account"
    print("test_pro_tenant_payment_conversation_uses_own_bank_details_never_kilas_bca OK")


def test_basic_tenant_payment_conversation_blocked_with_natural_fallback():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant(
        "pnid-t4-b", "62894000002", package="AI_ADMIN_BASIC",
        payment={"payment_bank_name": "BRI", "payment_account_number": "999", "payment_account_name": "Toko X"},
    )

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Boleh.[GIVE_PAYMENT_INFO]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles:
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555021", "transfer ke mana ya", phone_number_id="pnid-t4-b")),
            content_type="application/json",
        )
    reply_text = mock_bubbles.call_args[0][2]
    assert "BRI" not in reply_text and "999" not in reply_text, "Basic tenant must never reveal its bank details via chat"
    assert appmod.PAYMENT_CONFIG["account_number"] not in reply_text
    assert "konfirmasi langsung" in reply_text or "hubungi" in reply_text
    print("test_basic_tenant_payment_conversation_blocked_with_natural_fallback OK")


def test_pro_tenant_without_configured_payment_gets_natural_fallback_not_crash():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t4-c", "62894000003")  # Pro, but no payment_bank_name/account set

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Boleh.[GIVE_PAYMENT_INFO]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555022", "transfer ke mana ya", phone_number_id="pnid-t4-c")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    reply_text = mock_bubbles.call_args[0][2]
    assert appmod.PAYMENT_CONFIG["account_number"] not in reply_text
    print("test_pro_tenant_without_configured_payment_gets_natural_fallback_not_crash OK")


# ---------------------------------------------------------------------------
# Task 5 — Client Hub schema/service actually carries these settings
# ---------------------------------------------------------------------------

def test_client_hub_schema_has_appointment_and_payment_fields():
    reset_client_hub_db()
    business_id = _make_active_tenant(
        "pnid-t5-a", "62895000001",
        payment={"payment_bank_name": "BCA", "payment_account_number": "111", "payment_account_name": "Kedai A"},
    )
    profile = chrepo.get_business_profile(business_id)
    assert profile["appointment_enabled"] in (1, True)
    assert profile["payment_bank_name"] == "BCA"
    settings = tcs.get_tenant_appointment_settings(business_id)
    assert settings["meeting_enabled"] is True
    payment_cfg = tcs.get_tenant_payment_config(business_id)
    assert payment_cfg["bank_name"] == "BCA" and payment_cfg["account_number"] == "111"
    print("test_client_hub_schema_has_appointment_and_payment_fields OK")


# ---------------------------------------------------------------------------
# Task 6 — active-channel thread-local is always cleared
# ---------------------------------------------------------------------------

def test_channel_cleared_after_exception_mid_webhook():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t6-a", "62896000001")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", side_effect=RuntimeError("boom")):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555030", "halo", phone_number_id="pnid-t6-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200, "webhook must still return a clean 200 even on internal exception"
    assert appmod._active_whatsapp_phone_number_id() == appmod.WHATSAPP_PHONE_NUMBER_ID, (
        "the tenant channel must be cleared even though the request raised mid-processing"
    )
    print("test_channel_cleared_after_exception_mid_webhook OK")


def test_internal_owner_notify_never_inherits_a_leaked_tenant_channel():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t6-b", "62896000002", credentials_env_value="tenant-secret-token")

    # Simulate a stuck thread-local from some earlier, buggy code path (what this cycle's fix
    # prevents from ever happening via receive_webhook's own finally block) and confirm the
    # internal endpoint defends against it independently too.
    appmod._set_active_whatsapp_channel("pnid-t6-b", "tenant-secret-token")
    os.environ["INTERNAL_SERVICE_SECRET"] = "test-internal-secret"
    appmod.INTERNAL_SERVICE_SECRET = "test-internal-secret"
    appmod.INTERNAL_OWNER_NOTIFY_DISABLED = False

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/internal/owner-notify",
            data=json.dumps({"notification_type": "CUSTOM_PROJECT_SUBMITTED", "message": "test"}),
            content_type="application/json",
            headers={"X-Internal-Service-Secret": "test-internal-secret"},
        )
    assert resp.status_code == 200
    assert mock_post.called
    called_url = mock_post.call_args[0][0]
    assert "pnid-t6-b" not in called_url, "must never send via a leaked tenant channel"
    assert f"/{appmod.WHATSAPP_PHONE_NUMBER_ID}/" in called_url
    print("test_internal_owner_notify_never_inherits_a_leaked_tenant_channel OK")


def test_webhook_finally_clear_alone_protects_the_internal_endpoint():
    """End-to-end version of the scenario above: a REAL tenant webhook runs to completion
    (success, no simulated exception, no manual channel reset in between) and the very next call
    on this same test client — the internal owner-notify endpoint — must still use Kilas Works'
    own channel, proving receive_webhook()'s own `finally` clear is what does the job."""
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t6-e", "62896000005", credentials_env_value="tenant-e-token")
    os.environ["INTERNAL_SERVICE_SECRET"] = "test-internal-secret"
    appmod.INTERNAL_SERVICE_SECRET = "test-internal-secret"
    appmod.INTERNAL_OWNER_NOTIFY_DISABLED = False

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555099", "halo", phone_number_id="pnid-t6-e")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert "pnid-t6-e" in mock_post.call_args[0][0], "sanity check: the webhook itself DID use the tenant's channel"

    with patch("requests.post") as mock_post2:
        mock_post2.return_value.status_code = 200
        mock_post2.return_value.text = "{}"
        mock_post2.return_value.json.return_value = {}
        resp2 = client.post(
            "/internal/owner-notify",
            data=json.dumps({"notification_type": "CUSTOM_PROJECT_SUBMITTED", "message": "test"}),
            content_type="application/json",
            headers={"X-Internal-Service-Secret": "test-internal-secret"},
        )
    assert resp2.status_code == 200
    assert mock_post2.called
    called_url = mock_post2.call_args[0][0]
    assert "pnid-t6-e" not in called_url
    assert f"/{appmod.WHATSAPP_PHONE_NUMBER_ID}/" in called_url
    print("test_webhook_finally_clear_alone_protects_the_internal_endpoint OK")


def test_two_tenants_back_to_back_each_use_their_own_channel():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t6-c", "62896000003", credentials_env_value="token-c")
    _make_active_tenant("pnid-t6-d", "62896000004", credentials_env_value="token-d")

    urls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        urls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "{}"
        resp.json.return_value = {}
        return resp

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch("requests.post", side_effect=fake_post):
        client.post("/webhook", data=json.dumps(_text_payload("62899555040", "halo", phone_number_id="pnid-t6-c")), content_type="application/json")
        client.post("/webhook", data=json.dumps(_text_payload("62899555041", "halo", phone_number_id="pnid-t6-d")), content_type="application/json")

    assert any("pnid-t6-c" in u for u in urls)
    assert any("pnid-t6-d" in u for u in urls)
    print("test_two_tenants_back_to_back_each_use_their_own_channel OK")


# ---------------------------------------------------------------------------
# Task 7 — unrecognized Phone Number ID is never treated as Kilas Works
# ---------------------------------------------------------------------------

def test_unknown_phone_number_id_gets_no_reply_and_no_kilas_fallback():
    reset_client_hub_db()
    reset_bot_state()

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_call, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555050", "halo", phone_number_id="totally-unknown-pnid")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("unknown_phone_number_id") is True
    assert not mock_call.called
    assert not mock_post.called, "no reply of any kind must be sent for a genuinely unknown phone_number_id"
    print("test_unknown_phone_number_id_gets_no_reply_and_no_kilas_fallback OK")


def test_tenant_lookup_db_failure_also_gets_no_reply_and_no_kilas_fallback():
    reset_client_hub_db()
    reset_bot_state()

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(tcs, "get_tenant_by_phone_number_id", side_effect=RuntimeError("db exploded")), \
         patch.object(appmod, "call_claude") as mock_call, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899555051", "halo", phone_number_id="pnid-that-would-have-matched")),
            content_type="application/json",
        )
    assert resp.status_code == 200, "must still return a clean 200 to Meta, never crash the handler"
    assert resp.get_json().get("unknown_phone_number_id") is True
    assert not mock_call.called
    assert not mock_post.called
    print("test_tenant_lookup_db_failure_also_gets_no_reply_and_no_kilas_fallback OK")


# ---------------------------------------------------------------------------
# Task 9 — appointment & payment state isolation between two tenants, same phone
# ---------------------------------------------------------------------------

def test_appointment_and_payment_state_isolated_between_tenants_same_phone():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t9-a", "62899000101", payment={"payment_bank_name": "BCA", "payment_account_number": "111", "payment_account_name": "A"})
    _make_active_tenant("pnid-t9-b", "62899000102", payment={"payment_bank_name": "Mandiri", "payment_account_number": "222", "payment_account_name": "B"})
    same_customer = "62899000999"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Oke.[MEETING_PREFERENCE: day=besok|time=10:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload(same_customer, "mau booking besok jam 10", phone_number_id="pnid-t9-a")), content_type="application/json")

    tenant_a = _tenant_id_for("pnid-t9-a")
    tenant_b = _tenant_id_for("pnid-t9-b")
    key_a = appmod._ck(tenant_a, same_customer)
    key_b = appmod._ck(tenant_b, same_customer)
    assert key_a in appmod.tenant_meeting_requests
    assert key_b not in appmod.tenant_meeting_requests, "the SAME phone number's appointment with tenant A must not appear under tenant B"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Boleh.[GIVE_PAYMENT_INFO]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles_a:
        client.post("/webhook", data=json.dumps(_text_payload(same_customer, "transfer ke mana", phone_number_id="pnid-t9-a")), content_type="application/json")
    reply_a = mock_bubbles_a.call_args[0][2]
    assert "111" in reply_a and "222" not in reply_a

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Boleh.[GIVE_PAYMENT_INFO]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles_b:
        client.post("/webhook", data=json.dumps(_text_payload(same_customer, "transfer ke mana", phone_number_id="pnid-t9-b")), content_type="application/json")
    reply_b = mock_bubbles_b.call_args[0][2]
    assert "222" in reply_b and "111" not in reply_b
    print("test_appointment_and_payment_state_isolated_between_tenants_same_phone OK")


def test_owner_discussion_context_isolated_between_tenants():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-t9-c", "62899000103", business_name="Kedai Satu")
    _make_active_tenant("pnid-t9-d", "62899000104", business_name="Kedai Dua")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Oke dicatat.")), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899000103", "rahasia dapur kedai satu", phone_number_id="pnid-t9-c")), content_type="application/json")

    tenant_c = _tenant_id_for("pnid-t9-c")
    tenant_d = _tenant_id_for("pnid-t9-d")
    key_c = appmod._ck(tenant_c, "62899000103")
    key_d = appmod._ck(tenant_d, "62899000104")
    assert key_c in appmod.tenant_owner_conversations
    assert key_d not in appmod.tenant_owner_conversations
    print("test_owner_discussion_context_isolated_between_tenants OK")


# ---------------------------------------------------------------------------
# Task 10 — owner-phone collision resolved by channel, not phone alone
# (see also test_business_hub_v2_whatsapp_integration.py's dedicated regression test)
# ---------------------------------------------------------------------------

def test_owner_collision_regression_kilas_owner_number_as_tenant_owner():
    reset_client_hub_db()
    reset_bot_state()
    kilas_owner = appmod.OWNER_WHATSAPP_NUMBER
    _make_active_tenant("pnid-t10-a", kilas_owner, package="AI_ADMIN_BASIC")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude_owner") as mock_kilas_owner, \
         patch.object(appmod, "call_claude") as mock_customer_ai, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload(kilas_owner, "halo", phone_number_id="pnid-t10-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_kilas_owner.called
    assert not mock_customer_ai.called, "recognized as the (Basic) tenant owner, not a plain customer either"
    print("test_owner_collision_regression_kilas_owner_number_as_tenant_owner OK")


# ---------------------------------------------------------------------------
# Task 8 — shared-default credential architecture (no per-tenant env var required)
# ---------------------------------------------------------------------------

def test_tenant_without_credentials_reference_uses_shared_default_token():
    reset_client_hub_db()
    reset_bot_state()
    # configure_channel=False here so we control tenant_whatsapp_config directly, with NO
    # credentials_reference recorded at all (the Task 8 "shared default" case).
    business_id = _make_active_tenant("pnid-t8-a", "62898000001", configure_channel=False)
    chrepo.upsert_whatsapp_config(business_id, "pnid-t8-a", None, None, connection_status="CONNECTED")

    channel = appmod._get_tenant_whatsapp_channel_safe(business_id)
    assert channel is not None
    assert channel["phone_number_id"] == "pnid-t8-a"
    assert channel["access_token"] == appmod.WHATSAPP_ACCESS_TOKEN, (
        "no credentials_reference recorded -> must fall back to the shared default "
        "WHATSAPP_ACCESS_TOKEN, never fail closed and never require a new env var"
    )
    print("test_tenant_without_credentials_reference_uses_shared_default_token OK")


def test_tenant_with_distinct_credentials_reference_still_uses_its_own_token():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-t8-b", "62898000002", credentials_env_value="distinct-tenant-token")
    channel = appmod._get_tenant_whatsapp_channel_safe(business_id)
    assert channel is not None
    assert channel["access_token"] == "distinct-tenant-token"
    assert channel["access_token"] != appmod.WHATSAPP_ACCESS_TOKEN
    print("test_tenant_with_distinct_credentials_reference_still_uses_its_own_token OK")


# ---------------------------------------------------------------------------
# Task 11 — Basic vs Pro feature matrix, verified at runtime
# ---------------------------------------------------------------------------

def test_basic_vs_pro_runtime_matrix():
    reset_client_hub_db()
    reset_bot_state()
    basic_id = _make_active_tenant("pnid-t11-basic", "62897000001", package="AI_ADMIN_BASIC")
    pro_id = _make_active_tenant("pnid-t11-pro", "62897000002", package="AI_ADMIN_PRO")

    basic_feats = appmod._get_tenant_features_safe(basic_id)
    pro_feats = appmod._get_tenant_features_safe(pro_id)

    # Basic: customer support + FAQ/info yes; Pro-only advanced stuff no.
    assert basic_feats["faq"] is True and basic_feats["business_info"] is True
    for key in ("owner_commands", "appointment", "payment_conversation", "lead_qualification",
                "image_understanding", "voice_note", "advanced_history"):
        assert basic_feats[key] is False, f"Basic must not have {key}"

    # Pro: everything Basic has, plus every advanced capability.
    for key in basic_feats:
        if basic_feats[key]:
            assert pro_feats[key] is True
    for key in ("owner_commands", "appointment", "payment_conversation", "lead_qualification",
                "image_understanding", "voice_note", "advanced_history"):
        assert pro_feats[key] is True, f"Pro must have {key}"
    print("test_basic_vs_pro_runtime_matrix OK")


def test_human_takeover_available_regardless_of_package():
    # Human takeover is a Client Hub operational control (wa_takeover_service), not gated by
    # feature_flags at all — available for both packages, confirmed still true after this cycle.
    reset_client_hub_db()
    reset_bot_state()
    basic_id = _make_active_tenant("pnid-t11-basic2", "62897000003", package="AI_ADMIN_BASIC")
    import wa_takeover_service
    wa_takeover_service.start_human_takeover(basic_id, "62899999999", None)
    assert appmod._get_conversation_mode_safe(basic_id, "62899999999") == "HUMAN_TAKEOVER"
    print("test_human_takeover_available_regardless_of_package OK")


# ---------------------------------------------------------------------------
# Task D (v1 completion cycle) — ENABLE_MULTI_TENANT must never silently degrade a real Render
# deployment to single-tenant-only when the Client Hub bridge is genuinely available.
# ---------------------------------------------------------------------------

def test_render_warns_when_client_hub_available_but_multi_tenant_disabled():
    """Actually re-imports app.py in a fresh subprocess with RENDER set, Client Hub importable
    (client-hub/ is on sys.path via the real app.py startup code), and ENABLE_MULTI_TENANT left
    unset — exercises the REAL startup code path in app.py, not a re-implemented copy of it."""
    import subprocess
    env = dict(os.environ)
    env["RENDER"] = "true"
    env["ENABLE_MULTI_TENANT"] = "false"
    env.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
    env.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
    env.setdefault("ANTHROPIC_API_KEY", "key")
    env["VERIFY_TOKEN"] = "a-real-non-default-verify-token"
    env["DASHBOARD_KEY"] = "a-real-non-default-dashboard-key"
    env["CRON_SECRET"] = "a-real-non-default-cron-secret"
    env["INTERNAL_SERVICE_SECRET"] = "a-real-non-default-internal-secret"
    env.pop("DATABASE_URL", None)
    repo_root = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"import must still succeed (warning, not a hard fail): {result.stderr}"
    combined = result.stdout + result.stderr
    assert "ENABLE_MULTI_TENANT" in combined, (
        "must warn by name when Client Hub is available but ENABLE_MULTI_TENANT is off on Render"
    )
    assert "single-tenant" in combined.lower() or "SINGLE-TENANT" in combined
    print("test_render_warns_when_client_hub_available_but_multi_tenant_disabled OK")


def test_render_no_warning_when_multi_tenant_already_enabled():
    import subprocess
    env = dict(os.environ)
    env["RENDER"] = "true"
    env["ENABLE_MULTI_TENANT"] = "true"
    env.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
    env.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
    env.setdefault("ANTHROPIC_API_KEY", "key")
    env["VERIFY_TOKEN"] = "a-real-non-default-verify-token"
    env["DASHBOARD_KEY"] = "a-real-non-default-dashboard-key"
    env["CRON_SECRET"] = "a-real-non-default-cron-secret"
    env["INTERNAL_SERVICE_SECRET"] = "a-real-non-default-internal-secret"
    env["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
    repo_root = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=repo_root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "SINGLE-TENANT-ONLY" not in combined, "must not warn when multi-tenant mode is already on"
    print("test_render_no_warning_when_multi_tenant_already_enabled OK")


if __name__ == "__main__":
    test_pro_tenant_owner_internal_note_gets_a_real_reply_not_silence()
    test_pro_tenant_owner_query_scoped_to_own_customers_only()
    test_pro_tenant_owner_relay_forwards_plain_instruction_to_named_customer()
    test_basic_tenant_owner_recognized_not_treated_as_customer()
    test_pro_tenant_appointment_request_uses_own_business_hours_and_notifies_own_owner()
    test_basic_tenant_appointment_stays_unavailable()
    test_appointment_disabled_pro_tenant_still_blocked_despite_pro_package()
    test_pro_tenant_payment_conversation_uses_own_bank_details_never_kilas_bca()
    test_basic_tenant_payment_conversation_blocked_with_natural_fallback()
    test_pro_tenant_without_configured_payment_gets_natural_fallback_not_crash()
    test_client_hub_schema_has_appointment_and_payment_fields()
    test_tenant_without_credentials_reference_uses_shared_default_token()
    test_tenant_with_distinct_credentials_reference_still_uses_its_own_token()
    test_channel_cleared_after_exception_mid_webhook()
    test_internal_owner_notify_never_inherits_a_leaked_tenant_channel()
    test_webhook_finally_clear_alone_protects_the_internal_endpoint()
    test_two_tenants_back_to_back_each_use_their_own_channel()
    test_unknown_phone_number_id_gets_no_reply_and_no_kilas_fallback()
    test_tenant_lookup_db_failure_also_gets_no_reply_and_no_kilas_fallback()
    test_appointment_and_payment_state_isolated_between_tenants_same_phone()
    test_owner_discussion_context_isolated_between_tenants()
    test_owner_collision_regression_kilas_owner_number_as_tenant_owner()
    test_basic_vs_pro_runtime_matrix()
    test_human_takeover_available_regardless_of_package()
    test_render_warns_when_client_hub_available_but_multi_tenant_disabled()
    test_render_no_warning_when_multi_tenant_already_enabled()
    print("\nALL PRO TENANT PARITY TESTS PASSED")
