"""Business Hub V2 — PRODUCTION INTEGRATION test suite (Patches 1-6, applied to app.py).

Covers the WhatsApp Patches 1-6 now actually wired into the live bot's webhook handler
(receive_webhook in app.py), per client-hub/BOT_INTEGRATION_GUIDE.md:
  Patch 1 — tenant resolution from the webhook's own phone_number_id
  Patch 2 — tenant catalog context injected into the customer system prompt for one request
  Patch 3 — tenant feature gate (voice_note) ANDed with the existing global FEATURES flag
  Patch 4 — human takeover check before any AI auto-reply
  Patch 5 — tenant-owner message bridge (classify / parse offers / send to the active customer,
            or answer an open-projects query)
  Patch 6 — customer price/payment questions answered from the tenant's own catalog, never from
            Kilas Works' own PRICING_CONFIG and never an invented number

Every test in this file that exercises "ENABLE_MULTI_TENANT=on" behavior explicitly patches
appmod.ENABLE_MULTI_TENANT to True for the duration of that test (the flag is read once from the
environment at import time, same as every other flag in this codebase) — so this file can cover
both the off and on paths in the same process. ENABLE_MULTI_TENANT is NOT set in the environment
this file runs in, so importing app.py here reproduces exactly what production sees today: off by
default.

Run with:
    python3 test_business_hub_v2_whatsapp_integration.py
"""
import os
import sys
import json
import tempfile
from unittest.mock import patch, MagicMock

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "token")
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
import wa_takeover_service  # noqa: E402

_WA_ID_COUNTER = [0]


def _next_wamid():
    _WA_ID_COUNTER[0] += 1
    return f"wamid.v2it.{_WA_ID_COUNTER[0]}"


def reset_bot_state():
    appmod.customer_names.clear()
    appmod.conversations.clear()
    appmod.active_customer_context.clear()
    appmod._tenant_active_customer_context.clear()
    appmod.pending_owner_questions.clear()
    appmod.PROCESSED_MESSAGE_IDS.clear()
    appmod.PROCESSED_MESSAGE_IDS_ORDER.clear()


def reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    chdb._local.conn = None
    chdb.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_active_tenant(phone_number_id, trusted_owner_phone, package="AI_ADMIN_PRO",
                         business_name=None, services=None, faqs=None, description=None,
                         configure_channel=True):
    """Builds an ACTIVE Client Hub tenant with WhatsApp connected. Goes straight to the end state
    via direct SQL rather than replaying the full admin approve/provision/connect/activate workflow
    (that workflow — and its preconditions/idempotency — is already covered by
    test_production_foundation.py and test_business_hub_v2_phase_a.py; this file's job is the bot
    integration on top of an already-ACTIVE tenant). tenant_features is seeded automatically by
    repo.create_business() based on `package`, exactly like the real flow.

    When `services`/`faqs`/`description` are given, this ALSO runs the tenant through real
    onboarding data + provisioning.provision_tenant() (bug fix: the tenant context a resolved
    business gets must come from ITS OWN provisioned config — see
    app._build_tenant_context_block_safe — never from Kilas Works' own catalog_service, so a test
    that actually needs to inspect tenant knowledge content needs a REAL provisioned tenant, not
    just an ACTIVE status flag)."""
    name = business_name or f"Biz {phone_number_id}"
    user_id = chrepo.create_user(f"owner_{phone_number_id}@test.com", chsecurity.hash_password("password123"))
    business_id = chrepo.create_business(user_id, name, package=package)

    if services is not None or faqs is not None or description is not None:
        import provisioning as ch_provisioning
        admin_id = chrepo.create_user(
            f"admin_{phone_number_id}@kilasworks.id", chsecurity.hash_password("adminpass123"), role="KILAS_ADMIN"
        )
        admin_actor = {"id": admin_id, "role": "KILAS_ADMIN"}
        chrepo.upsert_business_profile(business_id, {
            "business_name": name, "category": "Test", "owner_name": "Owner",
            "primary_language": "id", "customer_salutation": "Kak",
        })
        chrepo.replace_business_services(business_id, [s[0] for s in (services or [])])
        for row, (svc_name, lo, hi) in zip(chrepo.get_business_services(business_id), services or []):
            chrepo.update_normalized_service(row["id"], svc_name, None, lo, hi, "IDR", False)
        chrepo.replace_business_faqs(business_id, [q for q, _a in (faqs or [])])
        for row, (q, a) in zip(chrepo.get_business_faqs(business_id), faqs or []):
            chrepo.update_normalized_faq(row["id"], q, a, None, False)
        chrepo.save_ai_normalized_config(business_id, f"{name} summary", {"description": description or ""}, [])
        chdb.execute("UPDATE businesses SET status = 'APPROVED' WHERE id = ?", (business_id,))
        ch_provisioning.provision_tenant(business_id, admin_actor)

    chdb.execute(
        "UPDATE businesses SET status = 'ACTIVE', whatsapp_connected = ?, "
        "whatsapp_phone_number_id = ?, trusted_owner_phone = ? WHERE id = ?",
        (True, phone_number_id, trusted_owner_phone, business_id),
    )

    # Multi-tenant runtime safety cycle (Task 1/2) — the production "Connect WhatsApp" admin flow
    # ALWAYS also writes tenant_whatsapp_config (repo.upsert_whatsapp_config), which is what
    # app.py's _get_tenant_whatsapp_channel_safe actually reads to pick THIS tenant's own outgoing
    # channel. configure_channel=True (the default) reproduces that so every test in this file that
    # doesn't specifically exercise "channel not configured yet" keeps sending normally; pass
    # configure_channel=False to test that Task 2 behavior on its own.
    if configure_channel:
        credentials_reference = f"TEST_WHATSAPP_TOKEN__TENANT_{business_id}"
        chrepo.upsert_whatsapp_config(business_id, phone_number_id, None, credentials_reference,
                                       connection_status="CONNECTED")
        os.environ[credentials_reference] = f"test-access-token-{business_id}"
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
# Patch 1 — tenant resolution
# ---------------------------------------------------------------------------

def test_unknown_phone_number_id_resolves_to_none():
    reset_client_hub_db()
    assert appmod._resolve_tenant_id(None) is None
    assert appmod._resolve_tenant_id("some-unregistered-id") is None
    print("test_unknown_phone_number_id_resolves_to_none OK")


def test_known_active_tenant_phone_number_id_resolves_correctly():
    reset_client_hub_db()
    business_id = _make_active_tenant("pnid-1001", "62899000001")
    assert appmod._resolve_tenant_id("pnid-1001") == business_id
    print("test_known_active_tenant_phone_number_id_resolves_correctly OK")


def test_client_hub_db_failure_never_crashes_webhook():
    # simulate a broken/unavailable client-hub read — must degrade to tenant_id=None, not raise.
    with patch.object(appmod._tcs, "get_tenant_by_phone_number_id", side_effect=RuntimeError("db down")):
        assert appmod._resolve_tenant_id("pnid-1001") is None
    print("test_client_hub_db_failure_never_crashes_webhook OK")


# ---------------------------------------------------------------------------
# ENABLE_MULTI_TENANT = off — old production behavior must remain valid
# ---------------------------------------------------------------------------

def test_multi_tenant_off_kilas_works_customer_flow_unchanged():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-2001", "62899000002")  # a real tenant exists, but flag stays off

    captured = {}

    def fake_call_claude(user_number, user_message, **kwargs):
        captured["tenant_context_block"] = kwargs.get("tenant_context_block")
        return "Halo kak, ada yang bisa dibantu?"

    payload = _text_payload("628999111111", "halo", phone_number_id="pnid-2001")
    with patch.object(appmod, "call_claude", side_effect=fake_call_claude), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    # flag is off -> tenant_context_block must be empty even though a real tenant matched
    assert captured.get("tenant_context_block") == "", captured
    print("test_multi_tenant_off_kilas_works_customer_flow_unchanged OK")


def test_multi_tenant_off_human_takeover_state_still_checked_and_inert_by_default():
    # Patch 4 is independent of the flag, but with no tenant activated for THIS number the default
    # mode is always AI_ACTIVE, so the bot still replies normally either way.
    reset_client_hub_db()
    reset_bot_state()
    payload = _text_payload("628999111112", "halo lagi", phone_number_id=None)
    with patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_send:
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    assert mock_send.called, "AI reply must still be sent when no tenant is in human takeover"
    print("test_multi_tenant_off_human_takeover_state_still_checked_and_inert_by_default OK")


# ---------------------------------------------------------------------------
# ENABLE_MULTI_TENANT = on — tenant-aware behavior
# ---------------------------------------------------------------------------

def test_multi_tenant_on_injects_tenant_own_catalog_context_never_kilas_works_pricing():
    """Bug fix: the tenant context block must be built from THIS tenant's OWN provisioned
    services/knowledge — never from Kilas Works' own catalog_service.list_active_catalog() (which
    used to be mislabeled here as "this business's official catalog"). A coffee-shop-style tenant
    asking about its own product must never see any Kilas Works product/price."""
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant(
        "pnid-3001", "62899000003", business_name="Kopi Senja V2",
        services=[("Kopi Susu Gula Aren", 20000, 20000)],
        faqs=[("Ada wifi?", "Ada, gratis.")],
        description="Kedai kopi santai",
    )

    captured = {}

    def fake_call_claude(user_number, user_message, **kwargs):
        captured["tenant_context_block"] = kwargs.get("tenant_context_block")
        return "Kopi susu gula aren nya segini ya kak."

    payload = _text_payload("628999222222", "menu apa aja ya", phone_number_id="pnid-3001")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", side_effect=fake_call_claude), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    block = captured.get("tenant_context_block") or ""
    assert "Kopi Senja V2" in block
    assert "Kopi Susu Gula Aren" in block
    assert "app.kilasworks.id" in block  # official payment channel note, not a Kilas Works product
    for forbidden in ("AI Admin", "Content Basic", "Content Growth", "Content Pro",
                       "Landing Page", "Rp799.000", "Meta Ads Management"):
        assert forbidden not in block, f"leaked Kilas Works content into tenant context: {forbidden!r}"
    print("test_multi_tenant_on_injects_tenant_own_catalog_context_never_kilas_works_pricing OK")


def test_multi_tenant_on_service_without_a_set_price_never_shows_invented_price():
    """A tenant service with no price_from/price_to set yet (the tenant's own equivalent of a
    'custom quote' item) must never get an invented number — the bot must be told to ask/escalate
    instead."""
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant(
        "pnid-3002", "62899000004", business_name="Studio Custom V2",
        services=[("Paket Custom Sesuai Kebutuhan", None, None)],
        faqs=[],
        description="Studio custom project",
    )

    captured = {}

    def fake_call_claude(user_number, user_message, **kwargs):
        captured["tenant_context_block"] = kwargs.get("tenant_context_block")
        return "Ok"

    payload = _text_payload("628999222223", "paket custom berapa", phone_number_id="pnid-3002")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", side_effect=fake_call_claude), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    block = captured.get("tenant_context_block") or ""
    assert "Paket Custom Sesuai Kebutuhan" in block
    assert "JANGAN karang angka" in block
    print("test_multi_tenant_on_service_without_a_set_price_never_shows_invented_price OK")


def test_human_takeover_blocks_ai_reply_and_return_to_ai_restores_it():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-4001", "62899000005")
    customer_number = "628999333333"

    wa_takeover_service.start_human_takeover(business_id, customer_number, actor_user_id=None)

    payload = _text_payload(customer_number, "halo masih di sini kak?", phone_number_id="pnid-4001")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_call_claude, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")

    assert resp.status_code == 200
    assert resp.get_json().get("human_takeover") is True
    assert not mock_call_claude.called, "AI must NOT reply while human takeover is active"

    # Return to AI — the very next message must get a normal AI reply again.
    wa_takeover_service.return_to_ai(business_id, customer_number, actor_user_id=None)
    payload2 = _text_payload(customer_number, "halo lagi", phone_number_id="pnid-4001")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo kak!") as mock_call_claude2, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_send:
        resp2 = client.post("/webhook", data=json.dumps(payload2), content_type="application/json")

    assert resp2.status_code == 200
    assert mock_call_claude2.called, "AI must reply again after return_to_ai"
    assert mock_send.called
    print("test_human_takeover_blocks_ai_reply_and_return_to_ai_restores_it OK")


def test_human_takeover_is_tenant_and_customer_scoped_no_cross_tenant_leakage():
    reset_client_hub_db()
    reset_bot_state()
    business_a = _make_active_tenant("pnid-5001", "62899000006")
    business_b = _make_active_tenant("pnid-5002", "62899000007")
    customer_number = "628999444444"  # SAME customer number chatting into two different tenants

    wa_takeover_service.start_human_takeover(business_a, customer_number, actor_user_id=None)

    # Tenant A: takeover active -> AI silent
    payload_a = _text_payload(customer_number, "halo", phone_number_id="pnid-5001")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude") as mock_a, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp_a = client.post("/webhook", data=json.dumps(payload_a), content_type="application/json")
    assert resp_a.get_json().get("human_takeover") is True
    assert not mock_a.called

    # Tenant B: same customer number, untouched -> AI still replies normally
    payload_b = _text_payload(customer_number, "halo juga", phone_number_id="pnid-5002")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!") as mock_b, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp_b = client.post("/webhook", data=json.dumps(payload_b), content_type="application/json")
    assert not resp_b.get_json().get("human_takeover")
    assert mock_b.called, "a different tenant's identical customer number must NOT inherit takeover"
    print("test_human_takeover_is_tenant_and_customer_scoped_no_cross_tenant_leakage OK")


def test_other_customers_of_same_tenant_continue_normally_during_takeover():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-6001", "62899000008")
    customer_1 = "628999555555"
    customer_2 = "628999555556"
    wa_takeover_service.start_human_takeover(business_id, customer_1, actor_user_id=None)

    payload_2 = _text_payload(customer_2, "halo", phone_number_id="pnid-6001")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo kak!") as mock_call, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_send:
        resp = client.post("/webhook", data=json.dumps(payload_2), content_type="application/json")
    assert not resp.get_json().get("human_takeover")
    assert mock_call.called and mock_send.called
    print("test_other_customers_of_same_tenant_continue_normally_during_takeover OK")


def test_owner_bridge_action_sends_offer_to_active_customer_only_when_flag_on():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-7001", "62899000009")
    owner_phone = "62899000009"
    customer_number = "628999666666"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo kak!"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload(customer_number, "halo mau tanya", phone_number_id="pnid-7001")),
            content_type="application/json",
        )

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    owner_payload = _text_payload(owner_phone, "bilang ke customer 2 juta bisa 2 video", phone_number_id="pnid-7001")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp = client.post("/webhook", data=json.dumps(owner_payload), content_type="application/json")

    assert resp.status_code == 200
    targets = [t for t, _ in sent]
    assert customer_number in targets, f"customer should have received the offer, got sends to: {targets}"
    customer_msg = next(m for t, m in sent if t == customer_number)
    assert "Rp2.000.000" in customer_msg
    assert "bilang ke customer" not in customer_msg.lower(), "owner's raw wording must never leak to the customer"
    print("test_owner_bridge_action_sends_offer_to_active_customer_only_when_flag_on OK")


def test_owner_bridge_disabled_when_flag_off_falls_through_to_normal_owner_path():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-7002", "62899000010")
    owner_phone = "62899000010"

    # Flag OFF: this "tenant owner" is not OWNER_WHATSAPP_NUMBER either, so with the bridge
    # disabled this number is treated as an ordinary CUSTOMER message (today's exact behavior).
    with patch.object(appmod, "call_claude", return_value="Halo kak, ada yang bisa dibantu?") as mock_call, \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_send:
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload(owner_phone, "bilang ke customer 2 juta", phone_number_id="pnid-7002")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert mock_call.called, "with the flag off, this must fall through to the normal customer AI path"
    print("test_owner_bridge_disabled_when_flag_off_falls_through_to_normal_owner_path OK")


def test_owner_bridge_query_answers_from_open_projects_summary():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-7003", "62899000011")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/client-hub")
    import projects_repo
    projects_repo.create_custom_project(business_id, "VIDEO", "Video Rina", {}, 1_000_000, 2_000_000, None)

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    # Task 1 (multi-tenant runtime safety cycle) — OWNER_QUERY for a Pro tenant owner now goes
    # through a REAL Claude call (call_tenant_owner_ai), same architecture as Kilas Works' own
    # owner assistant, instead of a canned "list open projects" response. The guarantee this test
    # verifies is that the project data actually reaches the model (in the system prompt) — the
    # mocked Claude response below stands in for what a real model would say back.
    captured_requests = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_requests.append(json)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"content": [{"text": "Yang masih jalan: Video Rina."}]}
        return resp

    owner_payload = _text_payload("62899000011", "project apa aja yang masih jalan?", phone_number_id="pnid-7003")
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send), \
         patch("requests.post", side_effect=fake_post):
        resp = client.post("/webhook", data=json.dumps(owner_payload), content_type="application/json")

    assert resp.status_code == 200
    assert captured_requests, "owner query must actually call the AI"
    assert "Video Rina" in captured_requests[0]["system"], "this tenant's own open project must reach the model's context"
    assert sent, "owner query should get a direct reply"
    assert "Video Rina" in sent[0][1]
    print("test_owner_bridge_query_answers_from_open_projects_summary OK")


def test_tenant_owner_collision_with_kilas_owner_number_stays_scoped_to_the_tenant():
    # Task 10 (multi-tenant runtime safety cycle) — a coincidental collision (some CLIENT tenant's
    # own trusted_owner_phone happens to equal Kilas Works' personal OWNER_WHATSAPP_NUMBER) must
    # NOT hijack that tenant's conversation into Kilas Works' own owner-AI path. Owner identity is
    # decided by (the channel this message arrived on) + (phone number), never phone number alone
    # — this message arrives on the TENANT's own phone_number_id, so it must be handled as THAT
    # tenant's own owner (or its Basic/Pro gate), never routed to call_claude_owner().
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-7004", appmod.OWNER_WHATSAPP_NUMBER, package="AI_ADMIN_PRO")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude_owner") as mock_kilas_owner_ai, \
         patch("requests.post") as mock_post, \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send:
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {"content": [{"text": "Oke, dicatat."}]}
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload(
                appmod.OWNER_WHATSAPP_NUMBER, "gimana kabar bisnis", phone_number_id="pnid-7004",
            )),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_kilas_owner_ai.called, "must NEVER be routed to Kilas Works' own owner-AI path"
    assert mock_send.called, "the tenant's own owner must still get a real reply"
    print("test_tenant_owner_collision_with_kilas_owner_number_stays_scoped_to_the_tenant OK")


def test_tenant_feature_gate_blocks_voice_note_when_tenant_feature_disabled():
    reset_client_hub_db()
    reset_bot_state()
    business_id = _make_active_tenant("pnid-8001", "62899000012", package="AI_ADMIN_BASIC")
    # AI_ADMIN_BASIC has voice_note=False in feature_flags.FEATURE_MATRIX
    assert appmod._get_tenant_features_safe(business_id).get("voice_note") is False

    payload = {
        "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "pnid-8001"},
            "messages": [{"id": _next_wamid(), "from": "628999777777", "type": "audio",
                          "audio": {"id": "media-1"}}],
        }}]}]
    }
    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)) as mock_send, \
         patch.object(appmod, "send_typing_indicator", return_value=None), \
         patch.object(appmod, "time") as mock_time:
        mock_time.sleep.return_value = None
        resp = client.post("/webhook", data=json.dumps(payload), content_type="application/json")
    assert resp.status_code == 200
    assert mock_send.called
    reply_text = mock_send.call_args[0][1]
    assert "teks & gambar" in reply_text, "Basic-tier tenant must be told voice notes aren't available"
    print("test_tenant_feature_gate_blocks_voice_note_when_tenant_feature_disabled OK")


if __name__ == "__main__":
    test_unknown_phone_number_id_resolves_to_none()
    test_known_active_tenant_phone_number_id_resolves_correctly()
    test_client_hub_db_failure_never_crashes_webhook()
    test_multi_tenant_off_kilas_works_customer_flow_unchanged()
    test_multi_tenant_off_human_takeover_state_still_checked_and_inert_by_default()
    test_multi_tenant_on_injects_tenant_own_catalog_context_never_kilas_works_pricing()
    test_multi_tenant_on_service_without_a_set_price_never_shows_invented_price()
    test_human_takeover_blocks_ai_reply_and_return_to_ai_restores_it()
    test_human_takeover_is_tenant_and_customer_scoped_no_cross_tenant_leakage()
    test_other_customers_of_same_tenant_continue_normally_during_takeover()
    test_owner_bridge_action_sends_offer_to_active_customer_only_when_flag_on()
    test_owner_bridge_disabled_when_flag_off_falls_through_to_normal_owner_path()
    test_owner_bridge_query_answers_from_open_projects_summary()
    test_tenant_owner_collision_with_kilas_owner_number_stays_scoped_to_the_tenant()
    test_tenant_feature_gate_blocks_voice_note_when_tenant_feature_disabled()
    print("\nALL BUSINESS HUB V2 WHATSAPP PRODUCTION INTEGRATION TESTS PASSED")
