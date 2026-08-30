"""Gap-fix Area E — AI Admin monthly subscription lifecycle test suite.

Covers: subscription creation on first activation, reminder/GRACE/SUSPENDED progression via
run_lifecycle_sweep(), non-destructive suspension (every other tenant table untouched), renewal
reactivation WITHOUT re-onboarding, and independence from creative-service projects.

Run with:
    cd client-hub && python3 tests/test_subscription_lifecycle.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import talent_service  # noqa: E402
import projects_repo  # noqa: E402
import payment_service  # noqa: E402
import provisioning  # noqa: E402
import subscription_service  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()
    talent_service.seed_talents_if_needed()


def _make_owner_and_business(email="owner@test.com", package="AI_ADMIN_BASIC"):
    user_id = repo.create_user(email, security.hash_password("password123"))
    business_id = repo.create_business(user_id, "Test Biz", package=package)
    return user_id, business_id


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _activate_fully(package="AI_ADMIN_BASIC"):
    """Full path to ACTIVE, reusing the exact same steps the real Phase B/C activation tests use
    (approve -> connect WhatsApp -> checkout/verify AI Admin payment -> activate)."""
    admin = _make_admin()
    uid, bid = _make_owner_and_business(email=f"owner_{os.urandom(4).hex()}@test.com", package=package)
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, f"555{bid}", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    catalog_key = "ai_admin_basic" if package == "AI_ADMIN_BASIC" else "ai_admin_pro"
    ai_item = catalog_service.get_catalog_item(catalog_key)
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    provisioning.activate_tenant(bid, admin)
    return admin, uid, bid


def _prepare_for_activation(package="AI_ADMIN_BASIC"):
    """Same steps as _activate_fully() up through verified payment, but stops BEFORE calling
    provisioning.activate_tenant() — lets Fix 3 tests inject a failure right at the activation
    call itself and inspect business/subscription state before vs. after."""
    admin = _make_admin()
    uid, bid = _make_owner_and_business(email=f"owner_{os.urandom(4).hex()}@test.com", package=package)
    repo.upsert_business_profile(bid, {"business_name": "Test Biz", "category": "Test", "owner_name": "X",
                                        "primary_language": "id", "customer_salutation": "Kak"})
    repo.replace_business_services(bid, ["Layanan A - 10rb"])
    repo.replace_business_faqs(bid, ["FAQ? Jawaban."])
    repo.save_ai_normalized_config(bid, "summary", {"description": "desc"}, [])
    provisioning.approve_and_provision(bid, admin)
    provisioning.connect_whatsapp_credentials(bid, admin, f"555{bid}", None, "WHATSAPP_TOKEN__TEST")
    db.execute("UPDATE businesses SET whatsapp_connected = ? WHERE id = ?", (True, bid))

    catalog_key = "ai_admin_basic" if package == "AI_ADMIN_BASIC" else "ai_admin_pro"
    ai_item = catalog_service.get_catalog_item(catalog_key)
    project_id = projects_repo.create_fixed_price_project(bid, ai_item, uid)
    invoice_id = payment_service.checkout(project_id, bid, uid)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 3, ?, ?)",
        (bid, project_id, b"abc", uid),
    )
    payment_service.upload_payment_proof(payment["id"], bid, file_id, uid)
    payment_service.verify_payment(payment["id"], bid, admin["id"])
    return admin, uid, bid


# ---------------------------------------------------------------------------
# Fix 3 — activation must fail closed if subscription creation fails
# ---------------------------------------------------------------------------
def test_activation_aborts_when_subscription_creation_fails():
    reset_db()
    admin, uid, bid = _prepare_for_activation()
    business_before = repo.get_business(bid)
    assert business_before["status"] == "APPROVED"

    import provisioning as prov_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated DB outage during subscription creation")

    with patch.object(subscription_service, "create_subscription", side_effect=boom):
        try:
            prov_module.activate_tenant(bid, admin)
            assert False, "activate_tenant must raise when subscription creation fails"
        except prov_module.ProvisioningError as e:
            assert "subscription_setup_failed" in str(e)

    business_after = repo.get_business(bid)
    assert business_after["status"] != "ACTIVE", "business must NOT become ACTIVE when subscription setup fails"
    assert business_after["status"] == "APPROVED", "business status must be left exactly as it was"
    assert subscription_service.get_subscription(bid) is None, \
        "no subscription row should exist after a failed creation attempt"
    print("test_activation_aborts_when_subscription_creation_fails OK")


def test_activation_failure_preserves_all_existing_tenant_data():
    reset_db()
    admin, uid, bid = _prepare_for_activation()
    profile_before = repo.get_business_profile(bid)
    services_before = repo.get_business_services(bid)
    faqs_before = repo.get_business_faqs(bid)
    ai_settings_before = repo.get_ai_settings(bid)
    wa_config_before = repo.get_whatsapp_config(bid)
    payments_before = db.query_all("SELECT * FROM payments WHERE business_id = ?", (bid,))

    import provisioning as prov_module

    with patch.object(subscription_service, "create_subscription",
                       side_effect=RuntimeError("simulated failure")):
        try:
            prov_module.activate_tenant(bid, admin)
        except prov_module.ProvisioningError:
            pass

    assert repo.get_business_profile(bid) == profile_before
    assert [s["raw_input"] for s in repo.get_business_services(bid)] == [s["raw_input"] for s in services_before]
    assert [f["raw_input"] for f in repo.get_business_faqs(bid)] == [f["raw_input"] for f in faqs_before]
    assert repo.get_ai_settings(bid)["normalized_config"] == ai_settings_before["normalized_config"]
    assert repo.get_whatsapp_config(bid) == wa_config_before
    payments_after = db.query_all("SELECT * FROM payments WHERE business_id = ?", (bid,))
    assert len(payments_after) == len(payments_before)
    print("test_activation_failure_preserves_all_existing_tenant_data OK")


def test_successful_activation_creates_subscription_before_activating():
    """Verifies ORDERING: create_subscription is called, and succeeds, strictly BEFORE
    repo.activate_business() flips the status — proven by making create_subscription itself
    assert the business is NOT YET ACTIVE at the moment it runs."""
    reset_db()
    admin, uid, bid = _prepare_for_activation()
    import provisioning as prov_module
    real_create_subscription = subscription_service.create_subscription
    call_order = []

    def spy_create_subscription(business_id, plan_key, actor_user_id=None, **kwargs):
        call_order.append("subscription_created")
        business_at_this_moment = repo.get_business(business_id)
        assert business_at_this_moment["status"] != "ACTIVE", \
            "subscription must be created BEFORE the business is activated"
        return real_create_subscription(business_id, plan_key, actor_user_id=actor_user_id, **kwargs)

    with patch.object(subscription_service, "create_subscription", side_effect=spy_create_subscription):
        result = prov_module.activate_tenant(bid, admin)

    call_order.append("activation_returned")
    assert call_order == ["subscription_created", "activation_returned"]
    assert result["status"] == "ACTIVE"
    business_after = repo.get_business(bid)
    assert business_after["status"] == "ACTIVE"
    sub = subscription_service.get_subscription(bid)
    assert sub is not None and sub["status"] == "ACTIVE"
    print("test_successful_activation_creates_subscription_before_activating OK")


def test_activation_retry_after_failure_succeeds_once_transient_error_clears():
    """A failed activation attempt must not leave the tenant permanently stuck — retrying
    activate_tenant() once the transient failure is gone must succeed normally."""
    reset_db()
    admin, uid, bid = _prepare_for_activation()
    import provisioning as prov_module

    with patch.object(subscription_service, "create_subscription",
                       side_effect=RuntimeError("transient")):
        try:
            prov_module.activate_tenant(bid, admin)
        except prov_module.ProvisioningError:
            pass
    assert repo.get_business(bid)["status"] == "APPROVED"

    # Retry without the injected failure — must succeed cleanly.
    result = prov_module.activate_tenant(bid, admin)
    assert result["status"] == "ACTIVE"
    assert repo.get_business(bid)["status"] == "ACTIVE"
    sub = subscription_service.get_subscription(bid)
    assert sub is not None and sub["status"] == "ACTIVE"
    print("test_activation_retry_after_failure_succeeds_once_transient_error_clears OK")


def test_activation_remains_idempotent_when_already_active():
    """Pre-existing idempotency guarantee (calling activate_tenant twice on an already-ACTIVE
    tenant is a safe no-op) must still hold after the Fix 3 reordering."""
    reset_db()
    admin, uid, bid = _activate_fully()
    assert repo.get_business(bid)["status"] == "ACTIVE"
    sub_before = subscription_service.get_subscription(bid)

    import provisioning as prov_module
    result = prov_module.activate_tenant(bid, admin)
    assert result == {"changed": False, "status": "ACTIVE"}
    sub_after = subscription_service.get_subscription(bid)
    assert sub_after == sub_before, "re-calling activate_tenant on an already-ACTIVE tenant must not touch the subscription"
    print("test_activation_remains_idempotent_when_already_active OK")


# ---------------------------------------------------------------------------
# 1. Subscription auto-created on first activation, correct plan_key, pricing untouched
# ---------------------------------------------------------------------------
def test_subscription_created_on_first_activation_basic():
    reset_db()
    admin, uid, bid = _activate_fully(package="AI_ADMIN_BASIC")
    sub = subscription_service.get_subscription(bid)
    assert sub is not None, "subscription harus otomatis dibuat begitu tenant pertama kali ACTIVE"
    assert sub["plan_key"] == "ai_admin_basic"
    assert sub["status"] == "ACTIVE"
    assert sub["grace_days"] == 3
    print("test_subscription_created_on_first_activation_basic OK")


def test_subscription_created_on_first_activation_pro():
    reset_db()
    admin, uid, bid = _activate_fully(package="AI_ADMIN_PRO")
    sub = subscription_service.get_subscription(bid)
    assert sub["plan_key"] == "ai_admin_pro"
    assert sub["status"] == "ACTIVE"
    print("test_subscription_created_on_first_activation_pro OK")


def test_pricing_config_unchanged():
    """Gap-fix Area E must NEVER redefine pricing — Basic Rp499.000 / Pro Rp999.000 stay exactly
    as they were in the source baseline."""
    import pricing_config
    basic = pricing_config.CATALOG_ITEMS_BY_KEY.get("ai_admin_basic") if hasattr(pricing_config, "CATALOG_ITEMS_BY_KEY") else None
    if basic is None:
        # Fall back to scanning CATALOG_ITEMS directly if no by-key index exists.
        basic = next(i for i in pricing_config.CATALOG_ITEMS if i["key"] == "ai_admin_basic")
        pro = next(i for i in pricing_config.CATALOG_ITEMS if i["key"] == "ai_admin_pro")
    else:
        pro = pricing_config.CATALOG_ITEMS_BY_KEY.get("ai_admin_pro")
    assert basic["price_amount"] == 499000, basic
    assert pro["price_amount"] == 999000, pro
    print("test_pricing_config_unchanged OK")


# ---------------------------------------------------------------------------
# 2. Lifecycle sweep: reminder -> GRACE -> SUSPENDED, non-destructive at each step
# ---------------------------------------------------------------------------
def test_sweep_sends_reminder_when_due_soon():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    near_due = (now + timedelta(days=2, hours=12)).isoformat()
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?", (near_due, bid))

    result = subscription_service.run_lifecycle_sweep()
    reminded_ids = [b for b, _stage in result["reminded"]]
    assert bid in reminded_ids, result
    sub = subscription_service.get_subscription(bid)
    assert sub["reminder_stage"] == "H3"  # 2 days remaining -> falls in the H3 (<=3 days) window
    assert sub["status"] == "ACTIVE"  # reminder alone never changes status
    print("test_sweep_sends_reminder_when_due_soon OK")


def test_reminder_stages_progress_h7_then_h3_then_h1():
    """Verifies all three reminder checkpoints (H-7, H-3, H-1) fire in order across separate
    sweeps as the due date approaches, each exactly once, never regressing."""
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)

    # 6 days out -> H7 checkpoint (<=7 days).
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(days=6)).isoformat(), bid))
    result = subscription_service.run_lifecycle_sweep()
    assert (bid, "H7") in result["reminded"], result
    assert subscription_service.get_subscription(bid)["reminder_stage"] == "H7"

    # Re-sweep same day, nothing changes (already sent H7 for this period).
    result = subscription_service.run_lifecycle_sweep()
    assert bid not in [b for b, _ in result["reminded"]], result

    # 3 days out -> H3 checkpoint.
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(days=3)).isoformat(), bid))
    result = subscription_service.run_lifecycle_sweep()
    assert (bid, "H3") in result["reminded"], result
    assert subscription_service.get_subscription(bid)["reminder_stage"] == "H3"

    # 1 day out -> H1 checkpoint.
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(days=1)).isoformat(), bid))
    result = subscription_service.run_lifecycle_sweep()
    assert (bid, "H1") in result["reminded"], result
    assert subscription_service.get_subscription(bid)["reminder_stage"] == "H1"
    print("test_reminder_stages_progress_h7_then_h3_then_h1 OK")


def test_reminder_stage_jumps_straight_to_h1_if_sweep_was_skipped():
    """A sweep that hasn't run in a while (e.g. cron skipped several days) must land on whichever
    stage is CURRENTLY due, not try to replay H7/H3 after the fact."""
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(hours=12)).isoformat(), bid))
    result = subscription_service.run_lifecycle_sweep()
    assert (bid, "H1") in result["reminded"], result
    print("test_reminder_stage_jumps_straight_to_h1_if_sweep_was_skipped OK")


def test_reminder_stage_resets_on_renewal():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(days=1)).isoformat(), bid))
    subscription_service.run_lifecycle_sweep()
    assert subscription_service.get_subscription(bid)["reminder_stage"] == "H1"

    subscription_service.renew_subscription(bid, admin["id"])
    assert subscription_service.get_subscription(bid)["reminder_stage"] is None
    print("test_reminder_stage_resets_on_renewal OK")


def test_sweep_moves_active_to_grace_after_period_end():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    past_due = (now - timedelta(days=1)).isoformat()
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?", (past_due, bid))

    result = subscription_service.run_lifecycle_sweep()
    assert bid in result["graced"], result
    sub = subscription_service.get_subscription(bid)
    assert sub["status"] == "GRACE"
    assert sub["grace_started_at"] is not None
    # Business itself must STILL be ACTIVE during grace — AI Admin keeps working.
    business = repo.get_business(bid)
    assert business["status"] == "ACTIVE", "tenant harus tetap ACTIVE selama masa GRACE"
    print("test_sweep_moves_active_to_grace_after_period_end OK")


def test_sweep_suspends_after_grace_window_elapses():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    grace_started = (now - timedelta(days=4)).isoformat()  # default grace_days=3, so 4 days ago = elapsed
    db.execute(
        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ?, period_end = ? WHERE business_id = ?",
        (grace_started, (now - timedelta(days=5)).isoformat(), bid),
    )
    # Sanity: business still ACTIVE before sweep (grace never touches business status).
    assert repo.get_business(bid)["status"] == "ACTIVE"

    result = subscription_service.run_lifecycle_sweep()
    assert bid in result["suspended"], result
    sub = subscription_service.get_subscription(bid)
    assert sub["status"] == "SUSPENDED"
    business = repo.get_business(bid)
    assert business["status"] == "SUSPENDED"
    print("test_sweep_suspends_after_grace_window_elapses OK")


def test_grace_window_not_yet_elapsed_stays_in_grace():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    grace_started = (now - timedelta(days=1)).isoformat()  # only 1 day into a 3-day grace window
    db.execute(
        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ? WHERE business_id = ?",
        (grace_started, bid),
    )
    result = subscription_service.run_lifecycle_sweep()
    assert bid not in result["suspended"], result
    assert repo.get_business(bid)["status"] == "ACTIVE"
    print("test_grace_window_not_yet_elapsed_stays_in_grace OK")


# ---------------------------------------------------------------------------
# 3. Suspension is non-destructive: every other tenant table survives untouched
# ---------------------------------------------------------------------------
def test_suspension_preserves_all_tenant_data():
    reset_db()
    admin, uid, bid = _activate_fully()

    # Seed one row in every table the requirement explicitly names.
    db.execute(
        "INSERT INTO tenant_appointments (business_id, customer_phone, customer_name, request_text, status) "
        "VALUES (?, ?, ?, ?, 'REQUESTED')",
        (bid, "62811111111", "Budi", "mau booking"),
    )
    db.execute(
        "INSERT INTO tenant_payment_reviews (business_id, customer_phone, customer_name, amount_claimed, status) "
        "VALUES (?, ?, ?, ?, 'PENDING_OWNER_VERIFICATION')",
        (bid, "62811111111", "Budi", 100000),
    )
    whatsapp_config_before = repo.get_whatsapp_config(bid)
    tenant_config_before = repo.get_tenant_config_row(bid)
    ai_settings_before = repo.get_ai_settings(bid)
    profile_before = repo.get_business_profile(bid)
    projects_before = projects_repo.list_projects_for_business(bid)

    # Force straight into SUSPENDED via the sweep.
    now = datetime.now(timezone.utc)
    db.execute(
        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ? WHERE business_id = ?",
        ((now - timedelta(days=10)).isoformat(), bid),
    )
    subscription_service.run_lifecycle_sweep()
    assert repo.get_business(bid)["status"] == "SUSPENDED"

    # Everything else must be byte-identical to before suspension.
    assert repo.get_whatsapp_config(bid) == whatsapp_config_before
    assert repo.get_tenant_config_row(bid) == tenant_config_before
    assert repo.get_ai_settings(bid)["normalized_config"] == ai_settings_before["normalized_config"]
    assert repo.get_business_profile(bid) == profile_before
    assert projects_repo.list_projects_for_business(bid) == projects_before
    appt = db.query_one("SELECT * FROM tenant_appointments WHERE business_id = ?", (bid,))
    assert appt is not None and appt["customer_name"] == "Budi"
    review = db.query_one("SELECT * FROM tenant_payment_reviews WHERE business_id = ?", (bid,))
    assert review is not None and review["amount_claimed"] == 100000
    print("test_suspension_preserves_all_tenant_data OK")


# ---------------------------------------------------------------------------
# 4. Renewal reactivates WITHOUT re-onboarding
# ---------------------------------------------------------------------------
def test_renewal_reactivates_without_reonboarding():
    reset_db()
    admin, uid, bid = _activate_fully()
    ai_settings_before = repo.get_ai_settings(bid)
    onboarding_status_before = repo.get_onboarding_status(bid)

    # Drive to SUSPENDED.
    now = datetime.now(timezone.utc)
    db.execute(
        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ? WHERE business_id = ?",
        ((now - timedelta(days=10)).isoformat(), bid),
    )
    subscription_service.run_lifecycle_sweep()
    assert repo.get_business(bid)["status"] == "SUSPENDED"

    # Renew.
    subscription_service.renew_subscription(bid, admin["id"])
    business = repo.get_business(bid)
    assert business["status"] == "ACTIVE", "renewal harus reaktivasi tenant tanpa onboarding ulang"
    sub = subscription_service.get_subscription(bid)
    assert sub["status"] == "ACTIVE"
    assert sub["period_end"] > now.isoformat()

    # Onboarding/AI setup state must be untouched — no re-run required.
    assert repo.get_ai_settings(bid)["normalized_config"] == ai_settings_before["normalized_config"]
    assert repo.get_onboarding_status(bid) == onboarding_status_before
    print("test_renewal_reactivates_without_reonboarding OK")


def test_renewal_before_suspension_just_extends_period():
    reset_db()
    admin, uid, bid = _activate_fully()
    sub_before = subscription_service.get_subscription(bid)
    subscription_service.renew_subscription(bid, admin["id"])
    sub_after = subscription_service.get_subscription(bid)
    assert sub_after["status"] == "ACTIVE"
    assert sub_after["period_end"] > sub_before["period_end"]
    assert repo.get_business(bid)["status"] == "ACTIVE"
    print("test_renewal_before_suspension_just_extends_period OK")


# ---------------------------------------------------------------------------
# 5. Creative-service projects stay independent of AI Admin subscription status
# ---------------------------------------------------------------------------
def test_creative_projects_unaffected_by_suspension():
    reset_db()
    admin, uid, bid = _activate_fully()
    photo_item = catalog_service.get_catalog_item("content_basic") if catalog_service.get_catalog_item("content_basic") else None
    # Use a generic custom project if no fixed content_basic key exists in this catalog build.
    if photo_item:
        project_id = projects_repo.create_fixed_price_project(bid, photo_item, uid)
    else:
        project_id = projects_repo.create_custom_project(
            bid, "PHOTO", "Foto produk", {"detail": "test"}, 500000, 1000000, uid,
        )
    projects_repo.set_project_status(project_id, "IN_PROGRESS", uid, bid, "mulai kerja")

    now = datetime.now(timezone.utc)
    db.execute(
        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ? WHERE business_id = ?",
        ((now - timedelta(days=10)).isoformat(), bid),
    )
    subscription_service.run_lifecycle_sweep()
    assert repo.get_business(bid)["status"] == "SUSPENDED"

    project = projects_repo.get_project(project_id)
    assert project["status"] == "IN_PROGRESS", "project kreatif harus tetap jalan walau AI Admin SUSPENDED"
    projects_repo.set_project_status(project_id, "COMPLETED", uid, bid, "selesai")
    assert projects_repo.get_project(project_id)["status"] == "COMPLETED"
    print("test_creative_projects_unaffected_by_suspension OK")


# ---------------------------------------------------------------------------
# 6. Banner never crashes / never leaks to a business without a subscription
# ---------------------------------------------------------------------------
def test_banner_none_when_no_subscription():
    reset_db()
    uid, bid = _make_owner_and_business(package="NONE")
    assert subscription_service.get_subscription_banner(bid) is None
    print("test_banner_none_when_no_subscription OK")


def test_banner_reflects_each_status():
    reset_db()
    admin, uid, bid = _activate_fully()
    banner = subscription_service.get_subscription_banner(bid)
    assert banner["status"] == "ACTIVE"
    assert banner["message"] is None  # no banner text needed for a healthy ACTIVE sub

    now = datetime.now(timezone.utc)
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(days=1)).isoformat(), bid))
    subscription_service.run_lifecycle_sweep()
    banner = subscription_service.get_subscription_banner(bid)
    assert banner["level"] == "info" and banner["message"]

    db.execute("UPDATE subscriptions SET status='GRACE', grace_started_at=? WHERE business_id=?",
               (now.isoformat(), bid))
    banner = subscription_service.get_subscription_banner(bid)
    assert banner["level"] == "warning" and "tenggang" in banner["message"]

    db.execute("UPDATE subscriptions SET status='SUSPENDED' WHERE business_id=?", (bid,))
    banner = subscription_service.get_subscription_banner(bid)
    assert banner["level"] == "danger" and "SUSPENDED" in banner["message"]
    print("test_banner_reflects_each_status OK")


# ---------------------------------------------------------------------------
# 7. Client dashboard + admin review pages render the subscription info without error
# ---------------------------------------------------------------------------
def test_client_dashboard_renders_with_subscription_banner():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    db.execute("UPDATE subscriptions SET status='GRACE', grace_started_at=? WHERE business_id=?",
               (now.isoformat(), bid))
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = uid
            sess["role"] = "CLIENT_OWNER"
        resp = c.get("/dashboard")
        assert resp.status_code == 200
        assert b"tenggang" in resp.data
    print("test_client_dashboard_renders_with_subscription_banner OK")


def test_admin_review_page_renders_with_subscription_card():
    reset_db()
    admin, uid, bid = _activate_fully()
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = admin["id"]
            sess["role"] = "KILAS_ADMIN"
        resp = c.get(f"/admin/business/{bid}")
        assert resp.status_code == 200
        assert b"AI Admin Subscription" in resp.data
    print("test_admin_review_page_renders_with_subscription_card OK")


def test_admin_renew_route_reactivates_suspended_business():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    db.execute(
        "UPDATE subscriptions SET status = 'GRACE', grace_started_at = ? WHERE business_id = ?",
        ((now - timedelta(days=10)).isoformat(), bid),
    )
    subscription_service.run_lifecycle_sweep()
    assert repo.get_business(bid)["status"] == "SUSPENDED"

    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = admin["id"]
            sess["role"] = "KILAS_ADMIN"
        resp = c.get(f"/admin/business/{bid}")  # loads CSRF-bearing page first (matches app convention)
        resp = c.post(f"/admin/business/{bid}/subscription/renew", data={}, follow_redirects=True)
        assert resp.status_code == 200
    assert repo.get_business(bid)["status"] == "ACTIVE"
    print("test_admin_renew_route_reactivates_suspended_business OK")


# ---------------------------------------------------------------------------
# Fix 1 — PostgreSQL datetime compatibility regression tests. A real psycopg2/PostgreSQL
# TIMESTAMPTZ column comes back as a native Python `datetime` object, NOT a string — these tests
# simulate that by writing actual `datetime` objects into the in-memory row dicts subscription_
# service.py's comparison helpers receive, proving _parse()/_lte()/_gt() (and everything built on
# them: renew_subscription, run_lifecycle_sweep, _days_remaining, get_subscription_banner) never
# assume a string and never TypeError on a real Postgres row. This is a COMPATIBILITY SIMULATION,
# not a substitute for an actual PostgreSQL smoke test (see the final report).
# ---------------------------------------------------------------------------
def test_parse_accepts_both_iso_string_and_datetime_object():
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.isoformat()
    assert subscription_service._parse(now_str) == subscription_service._parse(now_dt)
    assert subscription_service._parse(None) is None
    assert subscription_service._parse("") is None
    assert subscription_service._parse("not-a-date") is None
    assert subscription_service._parse(12345) is None  # unexpected type -> fail safe, not raise
    print("test_parse_accepts_both_iso_string_and_datetime_object OK")


def test_parse_naive_datetime_treated_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo, as some drivers/rows might hand back
    parsed = subscription_service._parse(naive)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
    print("test_parse_naive_datetime_treated_as_utc OK")


def test_lte_and_gt_never_typeerror_on_mixed_datetime_and_string():
    now_dt = datetime.now(timezone.utc)
    now_str = now_dt.isoformat()
    past_dt = now_dt - timedelta(days=1)
    future_dt = now_dt + timedelta(days=1)
    # datetime vs string, both directions — must never raise, must give the mathematically correct answer.
    assert subscription_service._lte(past_dt, now_str) is True
    assert subscription_service._lte(future_dt, now_str) is False
    assert subscription_service._gt(future_dt, now_str) is True
    assert subscription_service._gt(past_dt, now_str) is False
    # string vs datetime.
    assert subscription_service._lte(now_str, future_dt) is True
    # datetime vs datetime (pure Postgres-row-to-Postgres-row comparison).
    assert subscription_service._lte(past_dt, future_dt) is True
    # None on either side -> False, never raises.
    assert subscription_service._lte(None, now_str) is False
    assert subscription_service._gt(now_str, None) is False
    print("test_lte_and_gt_never_typeerror_on_mixed_datetime_and_string OK")


def test_run_lifecycle_sweep_works_when_period_end_is_a_datetime_object():
    """Simulates a psycopg2 row where subscriptions.period_end came back as a real datetime
    object (not a string) — proves run_lifecycle_sweep's ACTIVE->GRACE transition still fires
    correctly instead of TypeError-ing on `sub["period_end"] <= now`."""
    reset_db()
    admin, uid, bid = _activate_fully()
    past_datetime_obj = datetime.now(timezone.utc) - timedelta(days=1)
    # Directly simulate what a psycopg2 TIMESTAMPTZ column read would hand back: monkeypatch
    # get_subscription() for this one call so run_lifecycle_sweep sees a datetime object exactly
    # like it would against real Postgres, without needing a real Postgres connection.
    real_query_all = db.query_all

    def fake_query_all(query, params=()):
        rows = real_query_all(query, params)
        if "FROM subscriptions" in query:
            for row in rows:
                if row["business_id"] == bid:
                    row["period_end"] = past_datetime_obj  # simulate psycopg2 datetime return
        return rows

    with patch.object(db, "query_all", side_effect=fake_query_all):
        result = subscription_service.run_lifecycle_sweep()
    assert bid in result["graced"], result
    sub = subscription_service.get_subscription(bid)
    assert sub["status"] == "GRACE"
    print("test_run_lifecycle_sweep_works_when_period_end_is_a_datetime_object OK")


def test_renew_subscription_works_when_period_end_is_a_datetime_object():
    """Simulates the same psycopg2-datetime-return scenario for renew_subscription()'s
    `sub["period_end"] > now` comparison."""
    reset_db()
    admin, uid, bid = _activate_fully()
    future_datetime_obj = datetime.now(timezone.utc) + timedelta(days=15)
    real_get_subscription = subscription_service.get_subscription

    def fake_get_subscription(business_id):
        sub = real_get_subscription(business_id)
        if sub and sub["business_id"] == bid:
            sub = dict(sub)
            sub["period_end"] = future_datetime_obj
        return sub

    with patch.object(subscription_service, "get_subscription", side_effect=fake_get_subscription):
        result = subscription_service.renew_subscription(bid, admin["id"])
    assert result["status"] == "ACTIVE"
    # Extended FROM the future datetime (15 days out), not from "now" — proves the datetime
    # object was actually compared/used correctly, not silently treated as "always due now".
    # Read the REAL persisted row directly (outside the mock) for a clean, unmocked comparison.
    real_sub = subscription_service.get_subscription(bid)
    assert subscription_service._gt(real_sub["period_end"], future_datetime_obj.isoformat()), \
        (real_sub["period_end"], future_datetime_obj.isoformat())
    print("test_renew_subscription_works_when_period_end_is_a_datetime_object OK")


def test_days_remaining_and_banner_work_with_datetime_period_end():
    reset_db()
    admin, uid, bid = _activate_fully()
    near_datetime_obj = datetime.now(timezone.utc) + timedelta(days=2)
    real_get_subscription = subscription_service.get_subscription

    def fake_get_subscription(business_id):
        sub = real_get_subscription(business_id)
        if sub and sub["business_id"] == bid:
            sub = dict(sub)
            sub["period_end"] = near_datetime_obj
        return sub

    with patch.object(subscription_service, "get_subscription", side_effect=fake_get_subscription):
        banner = subscription_service.get_subscription_banner(bid)
    assert banner["days_remaining"] in (1, 2)  # timing-tolerant
    print("test_days_remaining_and_banner_work_with_datetime_period_end OK")


# ---------------------------------------------------------------------------
# Fix 6 — accurate reminder-delivery wording (dashboard-only, never claims a message was sent).
# ---------------------------------------------------------------------------
def test_reminder_audit_event_does_not_claim_delivery():
    reset_db()
    admin, uid, bid = _activate_fully()
    now = datetime.now(timezone.utc)
    db.execute("UPDATE subscriptions SET period_end = ? WHERE business_id = ?",
               ((now + timedelta(days=1)).isoformat(), bid))
    subscription_service.run_lifecycle_sweep()
    audit_rows = db.query_all(
        "SELECT * FROM audit_log WHERE business_id = ? AND action LIKE 'SUBSCRIPTION_REMINDER%'",
        (bid,),
    )
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "SUBSCRIPTION_REMINDER_STAGE_REACHED"
    assert "SENT" not in audit_rows[0]["action"], \
        "reminder audit event must not claim a message was actually delivered"
    print("test_reminder_audit_event_does_not_claim_delivery OK")


if __name__ == "__main__":
    test_activation_aborts_when_subscription_creation_fails()
    test_activation_failure_preserves_all_existing_tenant_data()
    test_successful_activation_creates_subscription_before_activating()
    test_activation_retry_after_failure_succeeds_once_transient_error_clears()
    test_activation_remains_idempotent_when_already_active()
    test_subscription_created_on_first_activation_basic()
    test_subscription_created_on_first_activation_pro()
    test_pricing_config_unchanged()
    test_sweep_sends_reminder_when_due_soon()
    test_reminder_stages_progress_h7_then_h3_then_h1()
    test_reminder_stage_jumps_straight_to_h1_if_sweep_was_skipped()
    test_reminder_stage_resets_on_renewal()
    test_parse_accepts_both_iso_string_and_datetime_object()
    test_parse_naive_datetime_treated_as_utc()
    test_lte_and_gt_never_typeerror_on_mixed_datetime_and_string()
    test_run_lifecycle_sweep_works_when_period_end_is_a_datetime_object()
    test_renew_subscription_works_when_period_end_is_a_datetime_object()
    test_days_remaining_and_banner_work_with_datetime_period_end()
    test_reminder_audit_event_does_not_claim_delivery()
    test_sweep_moves_active_to_grace_after_period_end()
    test_sweep_suspends_after_grace_window_elapses()
    test_grace_window_not_yet_elapsed_stays_in_grace()
    test_suspension_preserves_all_tenant_data()
    test_renewal_reactivates_without_reonboarding()
    test_renewal_before_suspension_just_extends_period()
    test_creative_projects_unaffected_by_suspension()
    test_banner_none_when_no_subscription()
    test_banner_reflects_each_status()
    test_client_dashboard_renders_with_subscription_banner()
    test_admin_review_page_renders_with_subscription_card()
    test_admin_renew_route_reactivates_suspended_business()
    print("ALL SUBSCRIPTION LIFECYCLE TESTS PASSED")
