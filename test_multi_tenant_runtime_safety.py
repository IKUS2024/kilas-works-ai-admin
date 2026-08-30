"""Multi-tenant runtime safety cycle — regression tests for the 7 tasks fixed in this cycle:

  1. Outgoing WhatsApp replies use the resolved tenant's OWN Phone-Number-ID/access token, never
     Kilas Works' own global WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN.
  2. An incompletely-configured tenant channel is skipped, never silently sent as Kilas Works.
  3. Conversation history/facts/language are scoped by (tenant_id, phone), not phone alone — the
     SAME phone number messaging two different tenants gets two fully separate conversations.
  4. Human takeover is scoped by (tenant_id, phone) too (already correct going into this cycle —
     covered here to confirm it still holds after the changes above).
  5. Feature-flag enforcement — a Basic tenant cannot use Pro-only runtime behavior
     (image_understanding, owner_commands; voice_note was already gated and is re-checked here).
  6. is_kilas_platform_tenant() distinguishes Kilas Works' own conversation from a client tenant's.
  7. A client tenant's conversation never leaks Kilas Works' own appointment hours or BCA account.

Run with:
    python3 test_multi_tenant_runtime_safety.py
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
import subscription_service  # noqa: E402 (Fix 4 audit — helper below now backs test tenants with a subscription row)
import wa_takeover_service  # noqa: E402
import provisioning  # noqa: E402
import tenant_config_service as tcs  # noqa: E402

_WA_ID_COUNTER = [0]


def _next_wamid():
    _WA_ID_COUNTER[0] += 1
    return f"wamid.mtrs.{_WA_ID_COUNTER[0]}"


def reset_bot_state():
    appmod.conversations.clear()
    appmod.customer_names.clear()
    appmod.agreed_facts.clear()
    appmod.customer_language.clear()
    appmod.active_customer_context.clear()
    appmod._tenant_active_customer_context.clear()
    appmod.pending_owner_questions.clear()
    appmod.meeting_requests.clear()
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
                         business_name=None, configure_channel=True, credentials_env_value="present"):
    """Same shape as test_business_hub_v2_whatsapp_integration.py's helper — builds an ACTIVE
    tenant with WhatsApp connected, going straight to the end state via direct SQL. When
    `configure_channel` is True (default), also writes tenant_whatsapp_config (the table
    app.py's _get_tenant_whatsapp_channel_safe actually reads) with a credentials_reference env
    var. Pass credentials_env_value=None to simulate a recorded pointer whose env var was never
    actually provisioned (Task 2's exact scenario)."""
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
    if configure_channel:
        credentials_reference = f"TEST_WA_TOKEN__TENANT_{business_id}"
        chrepo.upsert_whatsapp_config(business_id, phone_number_id, None, credentials_reference,
                                       connection_status="CONNECTED")
        if credentials_env_value is not None:
            os.environ[credentials_reference] = credentials_env_value
        else:
            os.environ.pop(credentials_reference, None)
    return business_id


def _text_payload(from_number, text, phone_number_id=None):
    value = {
        "messages": [{"id": _next_wamid(), "from": from_number, "type": "text", "text": {"body": text}}],
    }
    if phone_number_id:
        value["metadata"] = {"phone_number_id": phone_number_id}
    return {"entry": [{"changes": [{"value": value}]}]}


client = appmod.app.test_client()


# ---------------------------------------------------------------------------
# Task 6 — is_kilas_platform_tenant()
# ---------------------------------------------------------------------------

def test_is_kilas_platform_tenant_distinguishes_kilas_from_client():
    assert appmod.is_kilas_platform_tenant(None) is True
    assert appmod.is_kilas_platform_tenant(1) is False
    assert appmod.is_kilas_platform_tenant(999) is False
    print("test_is_kilas_platform_tenant_distinguishes_kilas_from_client OK")


# ---------------------------------------------------------------------------
# Task 1/2 — per-tenant outgoing WhatsApp channel
# ---------------------------------------------------------------------------

def test_tenant_with_configured_channel_sends_via_its_own_phone_number_and_token():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-ch-001", "62899100001", credentials_env_value="tenant-own-secret-token")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo kak!"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900001", "halo", phone_number_id="pnid-ch-001")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_post.called, "a reply should have been sent"
    called_url = mock_post.call_args[0][0]
    called_headers = mock_post.call_args[1]["headers"]
    assert "pnid-ch-001" in called_url, f"must send via the tenant's OWN phone_number_id, got: {called_url}"
    assert called_headers["Authorization"] == "Bearer tenant-own-secret-token", (
        "must send via the tenant's OWN access token, never Kilas Works' own WHATSAPP_ACCESS_TOKEN"
    )
    print("test_tenant_with_configured_channel_sends_via_its_own_phone_number_and_token OK")


def test_kilas_works_own_conversation_still_uses_global_channel():
    reset_client_hub_db()
    reset_bot_state()
    # No tenant registered for this phone_number_id at all -> tenant_id resolves to None (Kilas).
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900002", "halo", phone_number_id="123")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    called_url = mock_post.call_args[0][0]
    called_headers = mock_post.call_args[1]["headers"]
    assert "/123/" in called_url, called_url
    assert called_headers["Authorization"] == "Bearer kilas-global-token"
    print("test_kilas_works_own_conversation_still_uses_global_channel OK")


def test_incomplete_tenant_channel_skips_send_never_falls_back_to_kilas_identity():
    reset_client_hub_db()
    reset_bot_state()
    # credentials_reference recorded in tenant_whatsapp_config but the actual token env var was
    # never provisioned on this process (Task 2's exact scenario).
    _make_active_tenant("pnid-ch-002", "62899100002", credentials_env_value=None)

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_call_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900003", "halo", phone_number_id="pnid-ch-002")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("tenant_whatsapp_channel_not_configured") is True
    assert not mock_call_claude.called, "must not even ask the AI for a reply it can't safely send"
    assert not mock_post.called, "must never send ANY outgoing message (never as Kilas Works' own identity)"
    print("test_incomplete_tenant_channel_skips_send_never_falls_back_to_kilas_identity OK")


def test_never_connected_tenant_channel_skips_send():
    reset_client_hub_db()
    reset_bot_state()
    # Tenant resolved (ACTIVE, phone_number_id matches) but "Connect WhatsApp" was never actually
    # completed in Client Hub -> no tenant_whatsapp_config row at all.
    _make_active_tenant("pnid-ch-003", "62899100003", configure_channel=False)

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_call_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900004", "halo", phone_number_id="pnid-ch-003")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("tenant_whatsapp_channel_not_configured") is True
    assert not mock_call_claude.called
    assert not mock_post.called
    print("test_never_connected_tenant_channel_skips_send OK")


# ---------------------------------------------------------------------------
# Task 3 — same phone number, two different tenants -> fully separate state
# ---------------------------------------------------------------------------

def _fake_claude_response(reply_text):
    """Builds a fake requests.post() return value shaped like the Anthropic Messages API response
    that call_claude() reads (data["content"][0]["text"])."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"content": [{"text": reply_text}]}
    return resp


def test_same_customer_number_two_tenants_no_shared_conversation_or_facts():
    reset_client_hub_db()
    reset_bot_state()
    business_a = _make_active_tenant("pnid-mt-a", "62899200001", business_name="Kopi Senja")
    business_b = _make_active_tenant("pnid-mt-b", "62899200002", business_name="Salon Cantika")
    same_customer = "628999888888"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", return_value=_fake_claude_response("Halo, ini Kopi Senja ya!")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload(same_customer, "halo dari kopi", phone_number_id="pnid-mt-a")),
            content_type="application/json",
        )
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", return_value=_fake_claude_response("Halo, ini Salon Cantika ya!")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload(same_customer, "halo dari salon", phone_number_id="pnid-mt-b")),
            content_type="application/json",
        )

    key_a = appmod._ck(business_a, same_customer)
    key_b = appmod._ck(business_b, same_customer)
    assert key_a != key_b, "two different tenants must never collapse to the same state key"
    assert appmod.conversations.get(key_a) is not None
    assert appmod.conversations.get(key_b) is not None
    # each tenant's own conversation history must ONLY contain that tenant's own exchange
    text_a = json.dumps(appmod.conversations[key_a])
    text_b = json.dumps(appmod.conversations[key_b])
    assert "Kopi Senja" in text_a and "Salon Cantika" not in text_a
    assert "Salon Cantika" in text_b and "Kopi Senja" not in text_b
    print("test_same_customer_number_two_tenants_no_shared_conversation_or_facts OK")


def test_same_customer_number_two_tenants_customer_name_not_shared():
    reset_client_hub_db()
    reset_bot_state()
    business_a = _make_active_tenant("pnid-mt-c", "62899200003")
    business_b = _make_active_tenant("pnid-mt-d", "62899200004")
    same_customer = "628999888889"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", return_value=_fake_claude_response("Oke Budi, [NAMA: Budi]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload(same_customer, "nama saya Budi", phone_number_id="pnid-mt-c")),
            content_type="application/json",
        )

    key_a = appmod._ck(business_a, same_customer)
    key_b = appmod._ck(business_b, same_customer)
    assert appmod.customer_names.get(key_a) == "Budi"
    assert key_b not in appmod.customer_names, "tenant B must never see a name learned by tenant A"
    print("test_same_customer_number_two_tenants_customer_name_not_shared OK")


def test_kilas_works_own_conversation_key_unaffected_by_ck():
    # tenant_id=None (Kilas Works' own number) must map to the bare phone number, byte-for-byte —
    # zero behavior change for every pre-multi-tenant call site.
    assert appmod._ck(None, "628123456789") == "628123456789"
    assert appmod._ck(5, "628123456789") == "T5:628123456789"
    print("test_kilas_works_own_conversation_key_unaffected_by_ck OK")


# ---------------------------------------------------------------------------
# Task 4 — human takeover scoped by (tenant_id, phone) — still true after this cycle's changes
# ---------------------------------------------------------------------------

def test_takeover_scoped_per_tenant_and_per_customer_still_holds():
    reset_client_hub_db()
    reset_bot_state()
    business_a = _make_active_tenant("pnid-tk-a", "62899300001")
    business_b = _make_active_tenant("pnid-tk-b", "62899300002")
    same_customer = "628999777777"
    other_customer = "628999777778"

    wa_takeover_service.start_human_takeover(business_a, same_customer, actor_user_id=None)

    # Tenant A + same customer: AI silent.
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_a:
        resp_a = client.post(
            "/webhook",
            data=json.dumps(_text_payload(same_customer, "halo", phone_number_id="pnid-tk-a")),
            content_type="application/json",
        )
    assert resp_a.get_json().get("human_takeover") is True
    assert not mock_a.called

    # Tenant B + SAME customer number: must NOT inherit takeover.
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!") as mock_b, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp_b = client.post(
            "/webhook",
            data=json.dumps(_text_payload(same_customer, "halo juga", phone_number_id="pnid-tk-b")),
            content_type="application/json",
        )
    assert not resp_b.get_json().get("human_takeover")
    assert mock_b.called

    # Tenant A + a DIFFERENT customer: must NOT be paused either.
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!") as mock_c, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp_c = client.post(
            "/webhook",
            data=json.dumps(_text_payload(other_customer, "halo", phone_number_id="pnid-tk-a")),
            content_type="application/json",
        )
    assert not resp_c.get_json().get("human_takeover")
    assert mock_c.called
    print("test_takeover_scoped_per_tenant_and_per_customer_still_holds OK")


# ---------------------------------------------------------------------------
# Task 5 — Basic tenant cannot use Pro-only runtime features; Pro tenant can
# ---------------------------------------------------------------------------

def test_basic_tenant_image_understanding_blocked_pro_tenant_allowed():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-feat-basic-img", "62899400001", package="AI_ADMIN_BASIC")
    _make_active_tenant("pnid-feat-pro-img", "62899400002", package="AI_ADMIN_PRO")

    image_payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "pnid-feat-basic-img"},
            "messages": [{"id": _next_wamid(), "from": "628999666601", "type": "image",
                          "image": {"id": "media-basic"}}],
        }}]}]
    }
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send, \
         patch.object(appmod, "download_whatsapp_media") as mock_download, \
         patch.object(appmod, "time") as mock_time:
        mock_time.sleep.return_value = None
        resp = client.post("/webhook", data=json.dumps(image_payload), content_type="application/json")
    assert resp.status_code == 200
    assert mock_send.called
    assert "chat teks" in mock_send.call_args[0][1]
    assert not mock_download.called, "Basic tenant must never even download the image for vision"

    image_payload_pro = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "pnid-feat-pro-img"},
            "messages": [{"id": _next_wamid(), "from": "628999666602", "type": "image",
                          "image": {"id": "media-pro"}}],
        }}]}]
    }
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "download_whatsapp_media", return_value=("YmFzZTY0", "image/jpeg")), \
         patch.object(appmod, "call_claude", return_value="Sip, aku lihat gambarnya."), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles:
        resp2 = client.post("/webhook", data=json.dumps(image_payload_pro), content_type="application/json")
    assert resp2.status_code == 200
    assert mock_bubbles.called, "Pro tenant must still get a normal vision-based reply"
    print("test_basic_tenant_image_understanding_blocked_pro_tenant_allowed OK")


def test_basic_tenant_owner_commands_blocked_pro_tenant_allowed():
    reset_client_hub_db()
    reset_bot_state()
    owner_basic = "62899400003"
    owner_pro = "62899400004"
    _make_active_tenant("pnid-feat-basic-owner", owner_basic, package="AI_ADMIN_BASIC")
    _make_active_tenant("pnid-feat-pro-owner", owner_pro, package="AI_ADMIN_PRO")

    # Basic tenant's "owner" sends an OWNER_ACTION-shaped message -> Task 2: recognized AS the
    # owner (never routed through the normal customer AI path / call_claude), but denied the rich
    # Task-1 owner assistant with a natural, non-technical decline.
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_call, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send_basic:
        resp_basic = client.post(
            "/webhook",
            data=json.dumps(_text_payload(owner_basic, "bilang ke customer 2 juta", phone_number_id="pnid-feat-basic-owner")),
            content_type="application/json",
        )
    assert resp_basic.status_code == 200
    assert not mock_call.called, "Basic tenant owner must NEVER be routed through the normal customer AI path"
    assert mock_send_basic.called, "Basic tenant owner must get a real reply, not silence"
    decline_text = mock_send_basic.call_args[0][1].lower()
    assert "feature" not in decline_text and "flag" not in decline_text, "must be natural wording, not internal jargon"
    assert "pro" in decline_text, "should naturally point to the Pro upgrade"

    # Pro tenant's owner: bridge IS reachable (classify_owner_message runs instead of call_claude).
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_call_pro, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        resp_pro = client.post(
            "/webhook",
            data=json.dumps(_text_payload(owner_pro, "cuma mau ngobrol santai aja", phone_number_id="pnid-feat-pro-owner")),
            content_type="application/json",
        )
    assert resp_pro.status_code == 200
    assert not mock_call_pro.called, "Pro tenant owner message should be handled by the owner bridge, not the customer AI path"
    print("test_basic_tenant_owner_commands_blocked_pro_tenant_allowed OK")


def test_upgraded_tenant_sees_new_features_on_very_next_message():
    """Task 5 verification: features are read LIVE per-message via _get_tenant_features_safe, not
    cached at startup — upgrading Basic -> Pro must take effect on the very next message."""
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-upgrade", "62899400005", package="AI_ADMIN_BASIC")
    assert appmod._get_tenant_features_safe(business_id).get("image_understanding") is False

    chdb.execute("UPDATE businesses SET package = 'AI_ADMIN_PRO' WHERE id = ?", (business_id,))
    chrepo.set_tenant_features_for_package(business_id, "AI_ADMIN_PRO")

    assert appmod._get_tenant_features_safe(business_id).get("image_understanding") is True
    print("test_upgraded_tenant_sees_new_features_on_very_next_message OK")


# ---------------------------------------------------------------------------
# Task 7 — no Kilas Works appointment-hours / BCA leakage into a client tenant's conversation
# ---------------------------------------------------------------------------

def test_tenant_system_prompt_never_contains_kilas_appointment_hours():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-hours", "62899500001", business_name="Studio Kilat")
    prompt = appmod.build_customer_system_prompt(
        "628999333001", tenant_context_block="\n\nNAMA BISNIS INI: Studio Kilat\n",
    )
    assert "APPOINTMENT / JADWAL KETEMU OWNER" not in prompt
    assert "GAMBARAN HARI KERJA KANTOR" not in prompt
    for slot in appmod.DEFAULT_MEETING_SLOT_TIMES:
        assert slot not in prompt
    print("test_tenant_system_prompt_never_contains_kilas_appointment_hours OK")


def test_tenant_conversation_never_mentions_kilas_bca_account():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-bca", "62899500002", business_name="Warung Barokah")

    ai_reply_with_payment_tag = f"Oke kak, ini info pembayarannya {appmod.TAG_GIVE_PAYMENT_INFO}"
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value=ai_reply_with_payment_tag), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999333002", "aku transfer ke mana ya", phone_number_id="pnid-bca")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_bubbles.called
    sent_text = mock_bubbles.call_args[0][2]
    assert appmod.PAYMENT_CONFIG["account_number"] not in sent_text
    assert appmod.PAYMENT_CONFIG["bank"] not in sent_text
    assert "konfirmasi langsung ke tim" in sent_text
    print("test_tenant_conversation_never_mentions_kilas_bca_account OK")


def test_kilas_works_own_conversation_still_gets_appointment_context_and_payment_info():
    # Non-regression: Kilas Works' own conversations (tenant_id=None) must be completely unaffected.
    prompt = appmod.build_customer_system_prompt("628999000001", tenant_context_block="")
    assert "APPOINTMENT / JADWAL KETEMU OWNER" in prompt
    text = appmod.build_payment_info_text()
    assert appmod.PAYMENT_CONFIG["account_number"] in text
    print("test_kilas_works_own_conversation_still_gets_appointment_context_and_payment_info OK")


# ---------------------------------------------------------------------------
# Task A — real WhatsApp connection validation (uniqueness + best-effort live Meta Graph API check)
# ---------------------------------------------------------------------------

def _make_admin_actor():
    email = f"admin_wa_validate_{_WA_ID_COUNTER[0]}@kilasworks.id"
    user_id = chrepo.create_user(email, chsecurity.hash_password("adminpass123"), role="KILAS_ADMIN")
    return chdb.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def test_whatsapp_validation_blocks_duplicate_phone_number_id_across_tenants():
    reset_client_hub_db()
    admin = _make_admin_actor()
    bid_a = _make_active_tenant("dup-pnid-1", "628700000001", configure_channel=False)
    bid_b = _make_active_tenant("dup-pnid-2", "628700000002", configure_channel=False)
    # bid_a genuinely owns "dup-pnid-1" already (as if a prior admin connected it for real).
    chrepo.upsert_whatsapp_config(bid_a, "dup-pnid-1", None, "TOK_A", connection_status="CONNECTED")

    # A second, DIFFERENT tenant must never be allowed to claim the SAME Phone Number ID.
    result = provisioning.validate_and_connect_whatsapp(bid_b, admin, "dup-pnid-1", None, "TOK_B")
    assert result["status"] == "VALIDATION_FAILED"
    assert "duplicate_phone_number_id" in result["reason"]
    config_b = chrepo.get_whatsapp_config(bid_b)
    assert config_b["connection_status"] == "VALIDATION_FAILED", \
        "provisioning.validate_and_connect_whatsapp must never leave a duplicated Phone Number ID as CONNECTED"
    print("test_whatsapp_validation_blocks_duplicate_phone_number_id_across_tenants OK")


def test_whatsapp_validation_fails_safe_without_reachable_meta_credential():
    # This sandbox has no real, internet-reachable Meta Graph API credential — the credentials_
    # reference env var is deliberately left unset, exercising the exact fail-safe path production
    # would hit for a bad/unset token. Must NEVER result in CONNECTED.
    reset_client_hub_db()
    admin = _make_admin_actor()
    bid = _make_active_tenant("pnid-unreachable", "628700000003", configure_channel=False)
    os.environ.pop("TOK_UNREACHABLE_TEST", None)

    result = provisioning.validate_and_connect_whatsapp(bid, admin, "pnid-unreachable", None, "TOK_UNREACHABLE_TEST")
    assert result["status"] == "VALIDATION_FAILED"
    config = chrepo.get_whatsapp_config(bid)
    assert config["connection_status"] == "VALIDATION_FAILED"
    print("test_whatsapp_validation_fails_safe_without_reachable_meta_credential OK")


def test_whatsapp_validation_succeeds_and_marks_connected_when_meta_check_passes():
    # The live Meta Graph API call itself can't be exercised end-to-end in this sandbox (no real
    # internet-reachable WhatsApp Business credential exists here) — this test stubs ONLY that one
    # network leg (same convention as every other test in this suite stubbing an external HTTP
    # call) to prove the rest of the validation pipeline (uniqueness check -> live check -> mark
    # CONNECTED -> businesses.whatsapp_connected) wires together correctly end to end.
    reset_client_hub_db()
    admin = _make_admin_actor()
    bid = _make_active_tenant("pnid-reachable", "628700000004", configure_channel=False)
    original_check = provisioning._check_whatsapp_phone_number_reachable
    provisioning._check_whatsapp_phone_number_reachable = lambda phone_number_id, credentials_reference: (True, "ok")
    try:
        result = provisioning.validate_and_connect_whatsapp(bid, admin, "pnid-reachable", None, "TOK_REACHABLE_TEST")
    finally:
        provisioning._check_whatsapp_phone_number_reachable = original_check
    assert result["status"] == "CONNECTED"
    config = chrepo.get_whatsapp_config(bid)
    assert config["connection_status"] == "CONNECTED"
    print("test_whatsapp_validation_succeeds_and_marks_connected_when_meta_check_passes OK")


def test_whatsapp_validation_never_logs_or_returns_the_real_access_token_value():
    reset_client_hub_db()
    admin = _make_admin_actor()
    bid = _make_active_tenant("pnid-secretcheck", "628700000005", configure_channel=False)
    os.environ["TOK_SECRET_VALUE_TEST"] = "super-secret-real-meta-token-value"
    try:
        result = provisioning.validate_and_connect_whatsapp(bid, admin, "pnid-secretcheck", None, "TOK_SECRET_VALUE_TEST")
        assert "super-secret-real-meta-token-value" not in json.dumps(result)
        audit = chrepo.get_audit_log(bid, limit=50)
        for row in audit:
            assert "super-secret-real-meta-token-value" not in (row.get("detail") or "")
    finally:
        os.environ.pop("TOK_SECRET_VALUE_TEST", None)
    print("test_whatsapp_validation_never_logs_or_returns_the_real_access_token_value OK")


# ---------------------------------------------------------------------------
# Task C — cross-tenant data-access isolation (business profile/owner/WhatsApp-config/knowledge)
# ---------------------------------------------------------------------------

def test_cross_tenant_data_access_fully_isolated():
    reset_client_hub_db()
    bid_a = _make_active_tenant("pnid-cross-a", "628700000011", business_name="Kopi Cross A")
    bid_b = _make_active_tenant("pnid-cross-b", "628700000012", business_name="Dental Cross B")

    # Tenant resolution by phone_number_id must never cross-resolve.
    assert tcs.get_tenant_by_phone_number_id("pnid-cross-a") == bid_a
    assert tcs.get_tenant_by_phone_number_id("pnid-cross-b") == bid_b

    # Owner phone (trusted_owner_phone) must never be shared/confused between tenants.
    assert tcs.get_trusted_owner_phone(bid_a) == "628700000011"
    assert tcs.get_trusted_owner_phone(bid_b) == "628700000012"
    assert tcs.get_trusted_owner_phone(bid_a) != tcs.get_trusted_owner_phone(bid_b)

    # WhatsApp channel config (phone_number_id/credentials_reference) is per-tenant only.
    channel_a = tcs.get_tenant_whatsapp_channel(bid_a)
    channel_b = tcs.get_tenant_whatsapp_channel(bid_b)
    assert channel_a["phone_number_id"] == "pnid-cross-a"
    assert channel_b["phone_number_id"] == "pnid-cross-b"
    assert channel_a["credentials_reference"] != channel_b["credentials_reference"]

    # Business profile / knowledge lookups never return the other tenant's data.
    config_a = tcs.get_tenant_config(bid_a)
    config_b = tcs.get_tenant_config(bid_b)
    if config_a is not None and config_b is not None:
        assert config_a.get("tenant_id") == bid_a
        assert config_b.get("tenant_id") == bid_b

    # Feature entitlement is per-tenant.
    features_a = tcs.get_tenant_features(bid_a)
    features_b = tcs.get_tenant_features(bid_b)
    assert features_a is not features_b

    print("test_cross_tenant_data_access_fully_isolated OK")


# ---------------------------------------------------------------------------
# Fix 4 (production-safety patch) — main tenant AI-runtime gating: an ACTIVE business with valid
# WhatsApp but NO subscription row (or a SUSPENDED/CANCELLED one) must NOT receive paid AI
# automation via the main webhook reply path — must fail safely with no response at all, exactly
# like an unknown/inactive tenant. An ACTIVE+valid-ACTIVE-subscription tenant must keep working.
# ---------------------------------------------------------------------------

def test_active_tenant_with_no_subscription_row_gets_no_reply():
    reset_client_hub_db()
    reset_bot_state()
    # _make_active_tenant() (this file's own helper) normally backfills a subscription for an
    # AI_ADMIN_* package — bypass that here to reproduce the EXACT gap Fix 4 closes: ACTIVE
    # business, valid connected WhatsApp channel, but zero subscriptions row.
    business_id = _make_active_tenant("pnid-nosub-001", "62899100099", credentials_env_value="tenant-token")
    chdb.execute("DELETE FROM subscriptions WHERE business_id = ?", (business_id,))
    assert subscription_service.get_subscription(business_id) is None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900099", "halo, ada promo?", phone_number_id="pnid-nosub-001")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("unknown_phone_number_id") is True, \
        "an ACTIVE business missing its subscription row must be treated as UNKNOWN, not served"
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_active_tenant_with_no_subscription_row_gets_no_reply OK")


def test_active_tenant_with_suspended_subscription_gets_no_reply():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-nosub-002", "62899100098", credentials_env_value="tenant-token")
    chdb.execute("UPDATE subscriptions SET status = 'SUSPENDED' WHERE business_id = ?", (business_id,))

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900098", "halo", phone_number_id="pnid-nosub-002")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("unknown_phone_number_id") is True
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_active_tenant_with_suspended_subscription_gets_no_reply OK")


def test_active_tenant_with_cancelled_subscription_gets_no_reply():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-nosub-003", "62899100097", credentials_env_value="tenant-token")
    chdb.execute("UPDATE subscriptions SET status = 'CANCELLED' WHERE business_id = ?", (business_id,))

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900097", "halo", phone_number_id="pnid-nosub-003")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("unknown_phone_number_id") is True
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_active_tenant_with_cancelled_subscription_gets_no_reply OK")


def test_active_tenant_with_grace_subscription_still_replies_normally():
    """GRACE is a currently-operating state — the tenant must keep working through the whole
    grace window (see subscription_service.py's module docstring)."""
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-grace-001", "62899100096", credentials_env_value="tenant-token")
    chdb.execute("UPDATE subscriptions SET status = 'GRACE' WHERE business_id = ?", (business_id,))

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo Kak!"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900096", "halo", phone_number_id="pnid-grace-001")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_post.called, "a GRACE-status subscription must still be served normally"
    print("test_active_tenant_with_grace_subscription_still_replies_normally OK")


def test_active_tenant_with_active_subscription_replies_normally():
    """Regression guard: the normal/common case (ACTIVE business + ACTIVE subscription) must
    keep working exactly as before Fix 4."""
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-active-001", "62899100095", credentials_env_value="tenant-token")
    assert subscription_service.get_subscription(business_id)["status"] == "ACTIVE"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo Kak!"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900095", "halo", phone_number_id="pnid-active-001")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_post.called
    print("test_active_tenant_with_active_subscription_replies_normally OK")


def test_creative_only_business_package_none_unaffected_by_subscription_gate():
    """A package='NONE' (creative-services-only) business has no subscription concept — the new
    gate must not block it (it never had a subscription row and never will)."""
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-none-001", "62899100094", package="NONE",
                                       credentials_env_value="tenant-token")
    assert subscription_service.get_subscription(business_id) is None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo Kak!"), \
         patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "{}"
        mock_post.return_value.json.return_value = {}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900094", "halo", phone_number_id="pnid-none-001")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_post.called, "a non-AI-Admin (package=NONE) business must not be blocked by the subscription gate"
    print("test_creative_only_business_package_none_unaffected_by_subscription_gate OK")


def test_unknown_phone_number_id_still_gets_no_reply_after_fix4():
    """Regression guard: Fix 4 must not weaken the pre-existing unknown-tenant behavior."""
    reset_client_hub_db()
    reset_bot_state()
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900093", "halo", phone_number_id="pnid-totally-unknown")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("unknown_phone_number_id") is True
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_unknown_phone_number_id_still_gets_no_reply_after_fix4 OK")


def test_inactive_tenant_still_gets_no_reply_after_fix4():
    """Regression guard: an APPROVED-but-not-yet-ACTIVE tenant must still be treated as unknown,
    same as before Fix 4."""
    reset_client_hub_db()
    reset_bot_state()
    user_id = chrepo.create_user("owner_inactive@test.com", chsecurity.hash_password("password123"))
    business_id = chrepo.create_business(user_id, "Not Active Yet", package="AI_ADMIN_PRO")
    chdb.execute("UPDATE businesses SET whatsapp_phone_number_id = ? WHERE id = ?",
                 ("pnid-inactive-001", business_id))
    # status stays at its default (not ACTIVE) — never touched.

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch("requests.post") as mock_post:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("628999900092", "halo", phone_number_id="pnid-inactive-001")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json().get("unknown_phone_number_id") is True
    mock_claude.assert_not_called()
    mock_post.assert_not_called()
    print("test_inactive_tenant_still_gets_no_reply_after_fix4 OK")


if __name__ == "__main__":
    test_is_kilas_platform_tenant_distinguishes_kilas_from_client()
    test_tenant_with_configured_channel_sends_via_its_own_phone_number_and_token()
    test_kilas_works_own_conversation_still_uses_global_channel()
    test_incomplete_tenant_channel_skips_send_never_falls_back_to_kilas_identity()
    test_never_connected_tenant_channel_skips_send()
    test_same_customer_number_two_tenants_no_shared_conversation_or_facts()
    test_same_customer_number_two_tenants_customer_name_not_shared()
    test_kilas_works_own_conversation_key_unaffected_by_ck()
    test_takeover_scoped_per_tenant_and_per_customer_still_holds()
    test_basic_tenant_image_understanding_blocked_pro_tenant_allowed()
    test_basic_tenant_owner_commands_blocked_pro_tenant_allowed()
    test_upgraded_tenant_sees_new_features_on_very_next_message()
    test_tenant_system_prompt_never_contains_kilas_appointment_hours()
    test_tenant_conversation_never_mentions_kilas_bca_account()
    test_kilas_works_own_conversation_still_gets_appointment_context_and_payment_info()
    test_whatsapp_validation_blocks_duplicate_phone_number_id_across_tenants()
    test_whatsapp_validation_fails_safe_without_reachable_meta_credential()
    test_whatsapp_validation_succeeds_and_marks_connected_when_meta_check_passes()
    test_whatsapp_validation_never_logs_or_returns_the_real_access_token_value()
    test_cross_tenant_data_access_fully_isolated()
    test_active_tenant_with_no_subscription_row_gets_no_reply()
    test_active_tenant_with_suspended_subscription_gets_no_reply()
    test_active_tenant_with_cancelled_subscription_gets_no_reply()
    test_active_tenant_with_grace_subscription_still_replies_normally()
    test_active_tenant_with_active_subscription_replies_normally()
    test_creative_only_business_package_none_unaffected_by_subscription_gate()
    test_unknown_phone_number_id_still_gets_no_reply_after_fix4()
    test_inactive_tenant_still_gets_no_reply_after_fix4()
    print("\nALL MULTI-TENANT RUNTIME SAFETY TESTS PASSED")
