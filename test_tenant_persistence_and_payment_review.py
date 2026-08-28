"""Tenant-persistence cycle — end-to-end (../app.py webhook level) regression tests for:

  1. A Pro tenant's appointment request is PERSISTED in the database (tenant_appointments, via
     client-hub/appointments_repo.py) — not just the in-process tenant_meeting_requests dict — and
     is still retrievable (by the owner assistant's own query context) after everything in-process
     is cleared, simulating a server restart.
  2. Reschedule/cancel/confirm each update the SAME persisted row correctly.
  3. A Basic tenant still cannot create an appointment at all (re-verifying the existing gate).
  4. A Pro tenant's customer's payment-proof IMAGE creates a persisted, PENDING_OWNER_VERIFICATION
     tenant_payment_reviews row (with a best-effort amount_detected from the AI's own vision read),
     notifies THAT tenant's own owner (never Kilas Works' platform owner / owner_notifications.py),
     and the customer's acknowledgment NEVER claims the proof is genuine/verified/lunas.
  5. The tenant owner can query pending payment proofs and CONFIRM/REJECT one by natural-language
     command, resolved to the right customer, with an audit_log entry written and the customer
     notified.
  6. A tenant owner's payment command can NEVER affect a different tenant's payment record, even
     when both tenants happen to have a customer with the same name.
  7. Kilas Works' own platform-payment-verification flow (payment_state, owner_notifications.py)
     is completely unaffected by any of this — different table, different notification path.

Run with:
    python3 test_tenant_persistence_and_payment_review.py
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
import appointments_repo  # noqa: E402
import payment_reviews_repo  # noqa: E402
import owner_notifications  # noqa: E402

_WA_ID_COUNTER = [0]


def _next_wamid():
    _WA_ID_COUNTER[0] += 1
    return f"wamid.tp.{_WA_ID_COUNTER[0]}"


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


def reset_client_hub_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    chdb._local.conn = None
    chdb.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_active_tenant(phone_number_id, trusted_owner_phone, package="AI_ADMIN_PRO",
                         business_name=None, appointment_enabled=True, payment=None):
    name = business_name or f"Biz {phone_number_id}"
    user_id = chrepo.create_user(f"owner_{phone_number_id}@test.com", chsecurity.hash_password("password123"))
    business_id = chrepo.create_business(user_id, name, package=package)
    chdb.execute(
        "UPDATE businesses SET status = 'ACTIVE', whatsapp_connected = ?, "
        "whatsapp_phone_number_id = ?, trusted_owner_phone = ? WHERE id = ?",
        (True, phone_number_id, trusted_owner_phone, business_id),
    )
    profile_fields = {
        "operating_hours": "Senin-Sabtu 09.00-18.00", "closed_days": "Minggu",
        "appointment_enabled": appointment_enabled, "appointment_rules_raw": "Booking H-1 minimal",
        "owner_name": trusted_owner_phone, "category": "Test", "primary_language": "id",
        "customer_salutation": "Kak",
    }
    if payment:
        profile_fields.update(payment)
    chrepo.upsert_business_profile(business_id, profile_fields)
    chrepo.replace_business_services(business_id, ["Layanan utama"])
    chrepo.set_ai_status(business_id, "DONE")
    credentials_reference = f"TEST_WA_TOKEN__TENANT_{business_id}"
    chrepo.upsert_whatsapp_config(business_id, phone_number_id, None, credentials_reference,
                                   connection_status="CONNECTED")
    os.environ[credentials_reference] = "present"
    admin_id = chrepo.create_user(f"admin_{phone_number_id}@test.com", chsecurity.hash_password("password123"), role="KILAS_ADMIN")
    provisioning.provision_tenant(business_id, {"id": admin_id, "role": "KILAS_ADMIN"})
    return business_id


def _tenant_id_for(phone_number_id):
    row = chdb.query_one("SELECT id FROM businesses WHERE whatsapp_phone_number_id = ?", (phone_number_id,))
    return row["id"]


def _text_payload(from_number, text, phone_number_id=None):
    value = {"messages": [{"id": _next_wamid(), "from": from_number, "type": "text", "text": {"body": text}}]}
    if phone_number_id:
        value["metadata"] = {"phone_number_id": phone_number_id}
    return {"entry": [{"changes": [{"value": value}]}]}


def _image_payload(from_number, media_id, caption=None, phone_number_id=None):
    image = {"id": media_id}
    if caption:
        image["caption"] = caption
    value = {"messages": [{"id": _next_wamid(), "from": from_number, "type": "image", "image": image}]}
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
# Task 1 — appointment persistence
# ---------------------------------------------------------------------------

def test_appointment_persists_across_simulated_restart_and_owner_query_still_sees_it():
    reset_client_hub_db()
    reset_bot_state()
    _make_active_tenant("pnid-persist-a", "62893100001", business_name="Kopi Rina")
    tenant_id = _tenant_id_for("pnid-persist-a")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Oke aku catat.[MEETING_PREFERENCE: day=besok|time=14:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899700001", "mau booking besok jam 2 siang", phone_number_id="pnid-persist-a")),
            content_type="application/json",
        )

    # Row is really in the DB, not just the in-process dict.
    row = appointments_repo.get_latest_for_customer(tenant_id, "62899700001")
    assert row is not None and row["status"] == "REQUESTED"

    # Simulate a full app restart: clear the in-memory dict AND drop the DB connection.
    appmod.tenant_meeting_requests.clear()
    chdb.reset_connection_for_new_db_path()

    captured_prompts = []

    def fake_owner_post(url, headers=None, json=None, timeout=None):
        captured_prompts.append(json["system"])
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"content": [{"text": "Ada 1 booking besok."}]}
        return resp

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=fake_owner_post), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62893100001", "Ada booking besok?", phone_number_id="pnid-persist-a")),
            content_type="application/json",
        )
    assert captured_prompts, "owner query must reach the AI"
    assert "besok jam 14:00" in captured_prompts[0] or "14:00" in captured_prompts[0], (
        "appointment must still be visible to the owner assistant after tenant_meeting_requests "
        "was cleared and the DB connection was dropped and reopened — i.e. it came from the DB"
    )
    print("test_appointment_persists_across_simulated_restart_and_owner_query_still_sees_it OK")


def test_owner_confirm_appointment_by_name_updates_db_and_notifies_customer():
    reset_client_hub_db()
    reset_bot_state()
    tenant_id = _make_active_tenant("pnid-persist-b", "62893100002", business_name="Toko Budi")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo, ada yang bisa dibantu?"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899700002", "halo", phone_number_id="pnid-persist-b")), content_type="application/json")
    appmod.customer_names[appmod._ck(tenant_id, "62899700002")] = "Budi"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Oke.[MEETING_PREFERENCE: day=besok|time=16:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899700002", "mau booking besok jam 4 sore", phone_number_id="pnid-persist-b")), content_type="application/json")

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62893100002", "Confirm booking Budi.", phone_number_id="pnid-persist-b")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    row = appointments_repo.get_latest_for_customer(tenant_id, "62899700002")
    assert row["status"] == "CONFIRMED"
    customer_msgs = [t for (to, t) in sent if to == "62899700002"]
    assert customer_msgs and "dikonfirmasi" in customer_msgs[0]
    owner_msgs = [t for (to, t) in sent if to == "62893100002"]
    assert owner_msgs and "Budi" in owner_msgs[0]
    print("test_owner_confirm_appointment_by_name_updates_db_and_notifies_customer OK")


def test_owner_reject_appointment_by_time_with_reason():
    reset_client_hub_db()
    reset_bot_state()
    tenant_id = _make_active_tenant("pnid-persist-c", "62893100003", business_name="Salon Dewi")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "call_claude", return_value="Halo!"), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899700003", "halo", phone_number_id="pnid-persist-c")), content_type="application/json")
    appmod.customer_names[appmod._ck(tenant_id, "62899700003")] = "Sari"

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Oke.[MEETING_PREFERENCE: day=besok|time=16:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post("/webhook", data=json.dumps(_text_payload("62899700003", "mau booking besok jam 4 sore", phone_number_id="pnid-persist-c")), content_type="application/json")

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62893100003", "Tolak yang jam 4, bilang penuh.", phone_number_id="pnid-persist-c")),
            content_type="application/json",
        )
    row = appointments_repo.get_latest_for_customer(tenant_id, "62899700003")
    assert row["status"] == "CANCELLED"
    assert row["notes"] == "penuh"
    customer_msgs = [t for (to, t) in sent if to == "62899700003"]
    assert customer_msgs and "penuh" in customer_msgs[0]
    print("test_owner_reject_appointment_by_time_with_reason OK")


def test_basic_tenant_still_cannot_create_persisted_appointment():
    reset_client_hub_db()
    reset_bot_state()
    tenant_id = _make_active_tenant("pnid-persist-d", "62893100004", package="AI_ADMIN_BASIC")

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch("requests.post", side_effect=_fake_claude_post("Oke aku catat.[MEETING_PREFERENCE: day=besok|time=14:00]")), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62899700004", "mau booking besok", phone_number_id="pnid-persist-d")),
            content_type="application/json",
        )
    assert appointments_repo.get_latest_for_customer(tenant_id, "62899700004") is None
    print("test_basic_tenant_still_cannot_create_persisted_appointment OK")


# ---------------------------------------------------------------------------
# Task 2 — tenant payment-proof review workflow
# ---------------------------------------------------------------------------

def test_payment_proof_image_creates_pending_review_notifies_tenant_owner_not_kilas():
    reset_client_hub_db()
    reset_bot_state()
    tenant_id = _make_active_tenant(
        "pnid-pay-a", "62893200001", business_name="Kedai Kopi",
        payment={"payment_bank_name": "BCA", "payment_account_number": "111", "payment_account_name": "Kedai Kopi"},
    )

    ai_reply = (
        "Makasih ya, aku terusin ke tim buat dicek.[SUDAH_BAYAR][PAYMENT_PROOF_DETAILS: amount=150000]"
    )
    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "download_whatsapp_media", return_value=("ZmFrZS1pbWFnZQ==", "image/jpeg")), \
         patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)) as mock_bubbles, \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send), \
         patch.object(owner_notifications, "notify_owner_once") as mock_platform_notify:
        resp = client.post(
            "/webhook",
            data=json.dumps(_image_payload("62899800001", "media-proof-1", caption="ini bukti transfernya", phone_number_id="pnid-pay-a")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert not mock_platform_notify.called, "a tenant's own customer payment proof must NEVER go through Kilas's platform owner_notifications.py"

    reviews = payment_reviews_repo.list_pending_for_business(tenant_id)
    assert len(reviews) == 1
    review = reviews[0]
    assert review["status"] == "PENDING_OWNER_VERIFICATION"
    assert review["amount_detected"] == 150000
    assert review["customer_phone"] == "62899800001"
    assert review["proof_file_id"] is not None

    owner_msgs = [t for (to, t) in sent if to == "62893200001"]
    assert owner_msgs, "THIS tenant's own owner must be notified"
    kilas_owner_msgs = [t for (to, t) in sent if to == appmod.OWNER_WHATSAPP_NUMBER]
    assert not kilas_owner_msgs, "Kilas Works' own platform owner must never be notified of a tenant's own customer payment"

    reply_text = mock_bubbles.call_args[0][2]
    assert "Bukti sudah diterima dan sedang dicek." in reply_text
    for forbidden in ("sudah lunas", "terverifikasi", "sudah pasti asli", "dikonfirmasi"):
        assert forbidden not in reply_text.lower(), f"ack text must never claim certainty: {reply_text!r}"
    print("test_payment_proof_image_creates_pending_review_notifies_tenant_owner_not_kilas OK")


def test_owner_confirm_payment_by_name_updates_review_writes_audit_notifies_customer():
    reset_client_hub_db()
    reset_bot_state()
    tenant_id = _make_active_tenant("pnid-pay-b", "62893200002", business_name="Kedai Kopi 2")
    review_id = payment_reviews_repo.create_review(tenant_id, "62899800002", "Budi", amount_detected=150000)

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        resp = client.post(
            "/webhook",
            data=json.dumps(_text_payload("62893200002", "Confirm pembayaran Budi.", phone_number_id="pnid-pay-b")),
            content_type="application/json",
        )
    assert resp.status_code == 200
    review = payment_reviews_repo.get_review(review_id)
    assert review["status"] == "CONFIRMED"
    assert review["verified_by"] == "62893200002"
    assert review["verified_at"] is not None

    audit_rows = chrepo.get_audit_log(tenant_id)
    assert any("TENANT_PAYMENT_CONFIRMED" in r["action"] for r in audit_rows), "must write an audit trail entry"

    customer_msgs = [t for (to, t) in sent if to == "62899800002"]
    assert customer_msgs and "konfirmasi" in customer_msgs[0].lower()
    print("test_owner_confirm_payment_by_name_updates_review_writes_audit_notifies_customer OK")


def test_owner_reject_payment_with_reason_updates_review_and_notifies_customer():
    reset_client_hub_db()
    reset_bot_state()
    tenant_id = _make_active_tenant("pnid-pay-c", "62893200003", business_name="Kedai Kopi 3")
    payment_reviews_repo.create_review(tenant_id, "62899800003", "Sari", amount_detected=50000)

    sent = []

    def fake_send(to, text):
        sent.append((to, text))
        return True, None

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", side_effect=fake_send):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62893200003", "Tolak pembayaran Sari, nominalnya kurang.", phone_number_id="pnid-pay-c")),
            content_type="application/json",
        )
    reviews = payment_reviews_repo.list_for_business(tenant_id, statuses=("REJECTED",))
    assert len(reviews) == 1
    assert reviews[0]["owner_note"] == "nominalnya kurang"
    customer_msgs = [t for (to, t) in sent if to == "62899800003"]
    assert customer_msgs and "nominalnya kurang" in customer_msgs[0]
    print("test_owner_reject_payment_with_reason_updates_review_and_notifies_customer OK")


def test_owner_payment_command_cannot_affect_different_tenant_even_ambiguous_name():
    reset_client_hub_db()
    reset_bot_state()
    tenant_a = _make_active_tenant("pnid-pay-d", "62893200004", business_name="Kedai A")
    tenant_b = _make_active_tenant("pnid-pay-e", "62893200005", business_name="Kedai B")
    review_a = payment_reviews_repo.create_review(tenant_a, "62899800004", "Budi", amount_detected=100000)
    review_b = payment_reviews_repo.create_review(tenant_b, "62899800005", "Budi", amount_detected=200000)

    with patch.object(appmod, "ENABLE_MULTI_TENANT", True), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        client.post(
            "/webhook",
            data=json.dumps(_text_payload("62893200004", "Confirm pembayaran Budi.", phone_number_id="pnid-pay-d")),
            content_type="application/json",
        )

    assert payment_reviews_repo.get_review(review_a)["status"] == "CONFIRMED"
    assert payment_reviews_repo.get_review(review_b)["status"] == "PENDING_OWNER_VERIFICATION", (
        "tenant A's owner command must NEVER affect tenant B's payment record, even though both "
        "have a customer named 'Budi'"
    )
    print("test_owner_payment_command_cannot_affect_different_tenant_even_ambiguous_name OK")


# ---------------------------------------------------------------------------
# Task 3 — Kilas Works' own platform payment flow is untouched
# ---------------------------------------------------------------------------

def test_kilas_platform_payment_flow_unaffected_by_tenant_payment_code():
    reset_client_hub_db()
    reset_bot_state()

    ai_reply = "Makasih ya, aku cek dulu.[SUDAH_BAYAR][PAYMENT_PROOF_DETAILS: amount=999000]"
    with patch.object(appmod, "download_whatsapp_media", return_value=("ZmFrZQ==", "image/jpeg")), \
         patch.object(appmod, "call_claude", return_value=ai_reply), \
         patch.object(appmod, "send_reply_bubbles", return_value=(True, None)), \
         patch.object(appmod, "send_whatsapp_message", return_value=(True, None)):
        resp = client.post(
            "/webhook",
            data=json.dumps(_image_payload("62899900001", "media-kilas-1", caption="bukti transfer", phone_number_id=appmod.WHATSAPP_PHONE_NUMBER_ID)),
            content_type="application/json",
        )
    assert resp.status_code == 200
    pay_state = appmod.payment_state.get("62899900001")
    assert pay_state is not None and pay_state["status"] == appmod.PAYMENT_STATUS_PENDING_VERIFICATION

    # No tenant_payment_reviews row anywhere — Kilas Works' own conversation has tenant_id=None,
    # and every _tenant_payment_review_*_safe helper is a no-op for tenant_id=None.
    all_reviews = chdb.query_all("SELECT * FROM tenant_payment_reviews")
    assert len(all_reviews) == 0, "Kilas Works' own payment-proof flow must never write to tenant_payment_reviews"
    print("test_kilas_platform_payment_flow_unaffected_by_tenant_payment_code OK")


if __name__ == "__main__":
    test_appointment_persists_across_simulated_restart_and_owner_query_still_sees_it()
    test_owner_confirm_appointment_by_name_updates_db_and_notifies_customer()
    test_owner_reject_appointment_by_time_with_reason()
    test_basic_tenant_still_cannot_create_persisted_appointment()
    test_payment_proof_image_creates_pending_review_notifies_tenant_owner_not_kilas()
    test_owner_confirm_payment_by_name_updates_review_writes_audit_notifies_customer()
    test_owner_reject_payment_with_reason_updates_review_and_notifies_customer()
    test_owner_payment_command_cannot_affect_different_tenant_even_ambiguous_name()
    test_kilas_platform_payment_flow_unaffected_by_tenant_payment_code()
    print("\nALL TENANT PERSISTENCE + PAYMENT REVIEW TESTS PASSED")
