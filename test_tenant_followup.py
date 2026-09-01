"""Gap-fix Area F — tenant-scoped automatic follow-up test suite.

Covers: correct tenant channel used, cross-tenant isolation (same customer phone, two tenants),
unknown/suspended/unvalidated tenants send nothing, human takeover respected, customer response
stops follow-up, cooldown/max-attempt enforcement, NEVER falls back to Kilas Works' global
channel, and Kilas Works' own existing /cron/followups behavior is completely unchanged.

Run with:
    python3 test_tenant_followup.py
"""
import os
import sys
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "kilas-global-123")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "kilas-global-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "key")
os.environ.setdefault("VERIFY_TOKEN", "verify")
os.environ.setdefault("OWNER_WHATSAPP_NUMBER", "628111111111")
os.environ.setdefault("CRON_SECRET", "test-cron-secret")

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
import provisioning  # noqa: E402
import tenant_followup_service  # noqa: E402
import subscription_service  # noqa: E402

client = appmod.app.test_client()


def reset_bot_state():
    appmod.conversations.clear()
    appmod.customer_names.clear()
    appmod.agreed_facts.clear()
    appmod.active_customer_context.clear()
    appmod._tenant_active_customer_context.clear()
    appmod.followup_state.clear()
    appmod._clear_active_whatsapp_channel()


def reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    chdb._local.conn = None
    chdb.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_active_tenant(phone_number_id, trusted_owner_phone, package="AI_ADMIN_PRO",
                         business_name=None, connection_status="CONNECTED"):
    name = business_name or f"Biz {phone_number_id}"
    user_id = chrepo.create_user(f"owner_{phone_number_id}@test.com", chsecurity.hash_password("password123"))
    business_id = chrepo.create_business(user_id, name, package=package)
    chdb.execute(
        "UPDATE businesses SET status = 'ACTIVE', whatsapp_connected = ?, "
        "whatsapp_phone_number_id = ?, trusted_owner_phone = ? WHERE id = ?",
        (True, phone_number_id, trusted_owner_phone, business_id),
    )
    chrepo.upsert_business_profile(business_id, {
        "operating_hours": "Senin-Sabtu 09.00-18.00", "closed_days": "Minggu",
        "owner_name": trusted_owner_phone, "category": "Test", "primary_language": "id",
        "customer_salutation": "Kak",
    })
    chrepo.replace_business_services(business_id, ["Layanan utama"])
    chrepo.set_ai_status(business_id, "DONE")
    credentials_reference = f"TEST_WA_TOKEN__TENANT_{business_id}"
    chrepo.upsert_whatsapp_config(business_id, phone_number_id, None, credentials_reference,
                                   connection_status=connection_status)
    os.environ[credentials_reference] = f"secret-token-for-{business_id}"
    admin_id = chrepo.create_user(f"admin_{phone_number_id}@test.com", chsecurity.hash_password("password123"),
                                   role="KILAS_ADMIN")
    provisioning.provision_tenant(business_id, {"id": admin_id, "role": "KILAS_ADMIN"})
    subscription_service.create_subscription(
        business_id, "ai_admin_basic" if package == "AI_ADMIN_BASIC" else "ai_admin_pro", actor_user_id=admin_id,
    )
    return business_id


def _seed_due_followup(business_id, customer_phone, hours_silent=13, followup_count=0, resolved=False):
    now = appmod._utcnow()
    tenant_followup_service._upsert_state(
        business_id, customer_phone,
        last_customer_msg_at=(now - timedelta(hours=hours_silent)).isoformat(),
        followup_count=followup_count, resolved=resolved,
    )


class _enable_multi_tenant:
    """Context manager — temporarily sets appmod.ENABLE_MULTI_TENANT = True for exactly the scope
    of a `with` block, restoring the ORIGINAL value afterward in __exit__ (which always runs, even
    if the block raises — a Python context manager's __exit__ is guaranteed to run on exception
    unwind). Production's real, intentional gate on /cron/tenant-followups
    (`if not ENABLE_MULTI_TENANT: return ... 409 disabled`, see app.py) is NEVER touched or
    weakened by this — this only flips a Python-side test double for the duration of one sweep
    call, in this test process, then puts it back. Never sets the flag globally/permanently for
    the whole test process — see test_tenant_followup_disabled_when_enable_multi_tenant_false()
    below, which explicitly verifies the flag is False again by the time it runs."""
    def __enter__(self):
        self._original = appmod.ENABLE_MULTI_TENANT
        appmod.ENABLE_MULTI_TENANT = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        appmod.ENABLE_MULTI_TENANT = self._original
        return False  # never suppress an exception raised inside the `with` block


def _run_sweep():
    """Every dedicated tenant-follow-up test in this file wants to exercise the REAL
    eligibility/send logic behind /cron/tenant-followups, not the production ENABLE_MULTI_TENANT
    gate in front of it (that gate is tested explicitly and separately, see
    test_tenant_followup_disabled_when_enable_multi_tenant_false()) — so the flag is scoped True
    for exactly this one HTTP call via _enable_multi_tenant(), then restored immediately."""
    with _enable_multi_tenant():
        return client.get(f"/cron/tenant-followups?key={appmod.CRON_SECRET}")


# ---------------------------------------------------------------------------
# 1. Correct tenant channel is used for the send
# ---------------------------------------------------------------------------
def test_correct_tenant_channel_used():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-A-phone", "62894000001", business_name="Kopi A")
    _seed_due_followup(bid, "62899990001")

    captured_channel = {}

    def fake_send_reply_bubbles(to, msg_id, text):
        captured_channel["phone_number_id"] = appmod._active_whatsapp_phone_number_id()
        captured_channel["access_token"] = appmod._active_whatsapp_access_token()
        return True, None

    with patch.object(appmod, "call_claude", return_value="Halo Kak, masih ada yang bisa dibantu?"), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles):
        resp = _run_sweep()

    assert resp.status_code == 200, resp.get_json()
    assert captured_channel["phone_number_id"] == "tenant-A-phone", captured_channel
    assert captured_channel["access_token"] == f"secret-token-for-{bid}"
    print("test_correct_tenant_channel_used OK")


# ---------------------------------------------------------------------------
# 2. Two tenants with the SAME customer phone stay completely isolated
# ---------------------------------------------------------------------------
def test_two_tenants_same_customer_phone_stay_isolated():
    reset_client_hub_db()
    reset_bot_state()
    bid_a = _make_active_tenant("tenant-A", "62894000001", business_name="Kopi A")
    bid_b = _make_active_tenant("tenant-B", "62894000002", business_name="Kopi B")
    shared_phone = "62899990099"
    _seed_due_followup(bid_a, shared_phone)
    _seed_due_followup(bid_b, shared_phone)

    sent_channels = []

    def fake_send_reply_bubbles(to, msg_id, text):
        sent_channels.append((appmod._active_whatsapp_phone_number_id(), to))
        return True, None

    with patch.object(appmod, "call_claude", return_value="Halo Kak, masih ada yang bisa dibantu?"), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles):
        resp = _run_sweep()

    assert resp.status_code == 200
    assert ("tenant-A", shared_phone) in sent_channels
    assert ("tenant-B", shared_phone) in sent_channels
    assert len(sent_channels) == 2, sent_channels

    # Each tenant's own state row must be independently tracked (not shared/merged).
    state_a = tenant_followup_service._get_state(bid_a, shared_phone)
    state_b = tenant_followup_service._get_state(bid_b, shared_phone)
    assert state_a["followup_count"] == 1
    assert state_b["followup_count"] == 1
    assert state_a["id"] != state_b["id"]
    print("test_two_tenants_same_customer_phone_stay_isolated OK")


# ---------------------------------------------------------------------------
# 3. Unknown tenant (never created) sends nothing — trivially true since the sweep only
#    iterates real ACTIVE businesses, but verify tenants_checked reflects reality.
# ---------------------------------------------------------------------------
def test_no_tenants_means_nothing_sent():
    reset_client_hub_db()
    reset_bot_state()
    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tenants_checked"] == 0
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_no_tenants_means_nothing_sent OK")


# ---------------------------------------------------------------------------
# 4. Invalid/unvalidated WhatsApp channel -> tenant skipped, nothing sent
# ---------------------------------------------------------------------------
def test_unvalidated_whatsapp_sends_nothing():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-unval", "62894000003", connection_status="PENDING_VALIDATION")
    _seed_due_followup(bid, "62899990002")

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()

    assert resp.status_code == 200
    body = resp.get_json()
    assert any(r.get("status") == "skipped" and "whatsapp_not_validated" in r.get("reason", "")
               for r in body["results"]), body
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_unvalidated_whatsapp_sends_nothing OK")


def test_validation_failed_whatsapp_sends_nothing():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-valfail", "62894000004", connection_status="VALIDATION_FAILED")
    _seed_due_followup(bid, "62899990003")

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()

    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_validation_failed_whatsapp_sends_nothing OK")


# ---------------------------------------------------------------------------
# 5. Subscription SUSPENDED -> tenant skipped, nothing sent (even if business row itself is
#    still marked ACTIVE at the DB level, e.g. a race/partial state)
# ---------------------------------------------------------------------------
def test_suspended_subscription_sends_nothing():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-susp", "62894000005")
    _seed_due_followup(bid, "62899990004")
    chdb.execute("UPDATE subscriptions SET status = 'SUSPENDED' WHERE business_id = ?", (bid,))

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()

    assert resp.status_code == 200
    body = resp.get_json()
    assert any(r.get("status") == "skipped" and "SUSPENDED" in r.get("reason", "")
               for r in body["results"]), body
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_suspended_subscription_sends_nothing OK")


def test_business_status_suspended_sends_nothing():
    """A fully SUSPENDED business (the actual state a lapsed subscription drives it to via
    subscription_service.run_lifecycle_sweep()) is simply never returned by
    list_all_businesses(status_filter='ACTIVE') in the first place — verifies that too."""
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-susp2", "62894000006")
    _seed_due_followup(bid, "62899990005")
    chdb.execute("UPDATE businesses SET status = 'SUSPENDED' WHERE id = ?", (bid,))

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()

    assert resp.status_code == 200
    assert resp.get_json()["tenants_checked"] == 0
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_business_status_suspended_sends_nothing OK")


# ---------------------------------------------------------------------------
# 6. HUMAN_TAKEOVER -> that customer is skipped, nothing sent to them
# ---------------------------------------------------------------------------
def test_human_takeover_sends_nothing():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-takeover", "62894000007")
    customer = "62899990006"
    _seed_due_followup(bid, customer)

    with patch.object(appmod, "_get_conversation_mode_safe", return_value="HUMAN_TAKEOVER"), \
         patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()

    assert resp.status_code == 200
    body = resp.get_json()
    assert any(r.get("status") == "skipped" and r.get("reason") == "human_takeover" for r in body["results"]), body
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_human_takeover_sends_nothing OK")


# ---------------------------------------------------------------------------
# 7. Customer response stops follow-up (mark_customer_activity resets the "due" clock)
# ---------------------------------------------------------------------------
def test_customer_response_stops_followup():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-resp", "62894000008")
    customer = "62899990007"
    _seed_due_followup(bid, customer, hours_silent=13)

    # Simulate the customer replying — the real webhook path calls this via _tf_mark_activity_safe.
    tenant_followup_service.mark_customer_activity(bid, customer)

    due = tenant_followup_service.get_customers_due_for_followup(bid)
    assert customer not in due, due

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_customer_response_stops_followup OK")


def test_resolution_stops_followup_permanently():
    """Booking/payment/explicit stop-request -> mark_resolved() -> never sent again, even after
    the cooldown window would otherwise re-qualify them."""
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-resolve", "62894000009")
    customer = "62899990008"
    _seed_due_followup(bid, customer, hours_silent=100)  # very silent, would normally be due
    tenant_followup_service.mark_resolved(bid, customer, reason="payment_confirmed")

    due = tenant_followup_service.get_customers_due_for_followup(bid)
    assert customer not in due

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_resolution_stops_followup_permanently OK")


# ---------------------------------------------------------------------------
# 8. Cooldown + max-attempt protection
# ---------------------------------------------------------------------------
def test_cooldown_prevents_immediate_resend():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-cooldown", "62894000010")
    customer = "62899990009"
    _seed_due_followup(bid, customer, hours_silent=13)

    with patch.object(appmod, "call_claude", return_value="Halo Kak"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp1 = _run_sweep()
    assert resp1.status_code == 200
    assert tenant_followup_service._get_state(bid, customer)["followup_count"] == 1

    # Immediately sweep again — cooldown (same `hours` gap since last_followup_at) must block a
    # second send right away.
    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp2 = _run_sweep()
    assert resp2.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    assert tenant_followup_service._get_state(bid, customer)["followup_count"] == 1, \
        "cooldown must prevent a second send in the same window"
    print("test_cooldown_prevents_immediate_resend OK")


def test_max_attempts_enforced():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-maxattempt", "62894000011")
    customer = "62899990010"
    _seed_due_followup(bid, customer, hours_silent=13,
                        followup_count=tenant_followup_service.DEFAULT_MAX_FOLLOWUPS)

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_max_attempts_enforced OK")


# ---------------------------------------------------------------------------
# PRODUCTION MICRO-FIX — Meta error 131047: 8h gap / 23h safety gate / max 2 attempts (tenant path)
# ---------------------------------------------------------------------------
def test_tenant_max_attempts_is_2():
    assert tenant_followup_service.DEFAULT_MAX_FOLLOWUPS == 2
    print("test_tenant_max_attempts_is_2 OK")


def test_tenant_followup_allowed_at_8h_gap():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-8h", "62894000013")
    customer = "62899990013"
    _seed_due_followup(bid, customer, hours_silent=9)

    with patch.object(appmod, "call_claude", return_value="Halo Kak"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp = _run_sweep()
    assert resp.status_code == 200
    assert tenant_followup_service._get_state(bid, customer)["followup_count"] == 1, \
        "a customer silent for 9h (>= new 8h gap) must be followed up"
    print("test_tenant_followup_allowed_at_8h_gap OK")


def test_tenant_followup_not_yet_due_before_8h():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-notyet8h", "62894000014")
    customer = "62899990014"
    _seed_due_followup(bid, customer, hours_silent=5)

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_tenant_followup_not_yet_due_before_8h OK")


def test_tenant_second_followup_allowed_while_still_under_23h_safety_gate():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-second-ok", "62894000015")
    customer = "62899990015"
    now = appmod._utcnow()
    tenant_followup_service._upsert_state(
        bid, customer,
        last_customer_msg_at=(now - timedelta(hours=20)).isoformat(),
        last_followup_at=(now - timedelta(hours=9)).isoformat(),
        followup_count=1, resolved=False,
    )

    with patch.object(appmod, "call_claude", return_value="Halo Kak"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        resp = _run_sweep()
    assert resp.status_code == 200
    assert tenant_followup_service._get_state(bid, customer)["followup_count"] == 2
    print("test_tenant_second_followup_allowed_while_still_under_23h_safety_gate OK")


def test_tenant_followup_skipped_at_23h_safety_boundary():
    """Must NEVER attempt a free-text follow-up at/beyond WhatsApp's 24h customer-service window
    (23h safety buffer) — same rule as the global Kilas Works path, no template/channel fallback."""
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-23h-skip", "62894000016")
    customer = "62899990016"
    _seed_due_followup(bid, customer, hours_silent=23)

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_tenant_followup_skipped_at_23h_safety_boundary OK")


# ---------------------------------------------------------------------------
# 9. Tenant follow-up NEVER uses Kilas Works' own global WhatsApp channel
# ---------------------------------------------------------------------------
def test_tenant_followup_never_uses_kilas_global_channel():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-notglobal", "62894000012")
    _seed_due_followup(bid, "62899990011")

    captured = {}

    def fake_send_reply_bubbles(to, msg_id, text):
        captured["phone_number_id"] = appmod._active_whatsapp_phone_number_id()
        return True, None

    with patch.object(appmod, "call_claude", return_value="Halo Kak"), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles):
        resp = _run_sweep()

    assert resp.status_code == 200
    assert captured["phone_number_id"] != appmod.WHATSAPP_PHONE_NUMBER_ID, captured
    assert captured["phone_number_id"] == "tenant-notglobal"
    # And after the sweep finishes, the thread-local channel must be cleared, not left pointing at
    # the last tenant processed (which would silently leak into the NEXT unrelated request).
    assert appmod._active_whatsapp_phone_number_id() == appmod.WHATSAPP_PHONE_NUMBER_ID, \
        "channel must be cleared back to Kilas Works' own default after the sweep"
    print("test_tenant_followup_never_uses_kilas_global_channel OK")


def test_missing_channel_never_falls_back_to_global():
    """A tenant with NO tenant_whatsapp_config row at all (should be impossible given the ACTIVE
    gate, but tested directly as defense-in-depth) must be skipped, never silently sent via the
    global channel."""
    reset_client_hub_db()
    reset_bot_state()
    user_id = chrepo.create_user("owner_nochannel@test.com", chsecurity.hash_password("password123"))
    bid = chrepo.create_business(user_id, "No Channel Biz", package="AI_ADMIN_PRO")
    chdb.execute("UPDATE businesses SET status = 'ACTIVE' WHERE id = ?", (bid,))
    admin_id = chrepo.create_user("admin_nochannel@test.com", chsecurity.hash_password("password123"), role="KILAS_ADMIN")
    subscription_service.create_subscription(bid, "ai_admin_pro", actor_user_id=admin_id)
    _seed_due_followup(bid, "62899990012")

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = _run_sweep()
    assert resp.status_code == 200
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    print("test_missing_channel_never_falls_back_to_global OK")


# ---------------------------------------------------------------------------
# 10. Kilas Works' own existing /cron/followups behavior is completely unchanged
# ---------------------------------------------------------------------------
def test_kilas_works_own_followup_unchanged():
    reset_client_hub_db()
    reset_bot_state()
    number = "628800000099"
    appmod.customer_names[number] = "Budi"
    appmod.followup_state[number] = {
        "last_customer_msg_at": appmod._utcnow() - timedelta(hours=13),
        "last_followup_at": None, "followup_count": 0, "converted": False,
    }
    sent = []

    def fake_send_reply_bubbles(to, msg_id, text):
        sent.append((to, appmod._active_whatsapp_phone_number_id()))
        return True, None

    with patch.object(appmod, "call_claude", return_value="Halo Kak Budi, masih ada yang mau ditanyain?"), \
         patch.object(appmod, "send_reply_bubbles", side_effect=fake_send_reply_bubbles):
        resp = client.get(f"/cron/followups?key={appmod.CRON_SECRET}")

    assert resp.status_code == 200
    assert sent == [(number, appmod.WHATSAPP_PHONE_NUMBER_ID)], sent
    print("test_kilas_works_own_followup_unchanged OK")


# ---------------------------------------------------------------------------
# Production gate regression — /cron/tenant-followups must return 409 disabled and send NOTHING
# when ENABLE_MULTI_TENANT is False (the real, current, intentional production default). This
# test deliberately does NOT use _run_sweep() (which scopes the flag to True) — it calls the
# endpoint directly to verify the opposite, default-off case matches production right now.
# ---------------------------------------------------------------------------
def test_tenant_followup_disabled_when_enable_multi_tenant_false():
    reset_client_hub_db()
    reset_bot_state()
    bid = _make_active_tenant("tenant-gate-test", "62894000099")
    _seed_due_followup(bid, "62899990099")
    assert appmod.ENABLE_MULTI_TENANT is False, \
        "test process default must be False here, matching production's real current setting"

    with patch.object(appmod, "call_claude") as mock_claude, \
         patch.object(appmod, "send_reply_bubbles") as mock_send:
        resp = client.get(f"/cron/tenant-followups?key={appmod.CRON_SECRET}")

    assert resp.status_code == 409, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "disabled"
    assert body["tenants_checked"] == 0
    assert body["results"] == []
    mock_claude.assert_not_called()
    mock_send.assert_not_called()
    # And the flag must still be False afterward — nothing in this test process permanently
    # changed it (this test ran BEFORE any _run_sweep()-based test in file order here, but the
    # assertion holds regardless of order since _enable_multi_tenant() always restores in __exit__).
    assert appmod.ENABLE_MULTI_TENANT is False
    print("test_tenant_followup_disabled_when_enable_multi_tenant_false OK")


if __name__ == "__main__":
    test_correct_tenant_channel_used()
    test_two_tenants_same_customer_phone_stay_isolated()
    test_no_tenants_means_nothing_sent()
    test_unvalidated_whatsapp_sends_nothing()
    test_validation_failed_whatsapp_sends_nothing()
    test_suspended_subscription_sends_nothing()
    test_business_status_suspended_sends_nothing()
    test_human_takeover_sends_nothing()
    test_customer_response_stops_followup()
    test_resolution_stops_followup_permanently()
    test_cooldown_prevents_immediate_resend()
    test_max_attempts_enforced()
    test_tenant_max_attempts_is_2()
    test_tenant_followup_allowed_at_8h_gap()
    test_tenant_followup_not_yet_due_before_8h()
    test_tenant_second_followup_allowed_while_still_under_23h_safety_gate()
    test_tenant_followup_skipped_at_23h_safety_boundary()
    test_tenant_followup_never_uses_kilas_global_channel()
    test_missing_channel_never_falls_back_to_global()
    test_kilas_works_own_followup_unchanged()
    test_tenant_followup_disabled_when_enable_multi_tenant_false()
    print("ALL TENANT FOLLOWUP TESTS PASSED")
