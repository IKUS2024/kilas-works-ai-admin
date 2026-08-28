"""Tenant-persistence cycle — unit tests for the pure repo/logic modules added this cycle:

  - migration 0013 (tenant_appointments, tenant_payment_reviews)
  - appointments_repo.py
  - payment_reviews_repo.py
  - wa_project_bridge.py's new record-command classifier/resolvers (classify_owner_record_command,
    extract_owner_command_reason, extract_owner_command_target_name, resolve_appointment_target,
    resolve_payment_review_target)

None of this depends on ../app.py — see test_tenant_persistence_end_to_end.py (repo root) for the
full webhook-level wiring tests.

Run with:
    cd client-hub && python3 tests/test_tenant_persistence_repos.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import appointments_repo  # noqa: E402
import payment_reviews_repo  # noqa: E402
import wa_project_bridge as bridge  # noqa: E402


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()


def _make_business(name="Kedai Test"):
    user_id = repo.create_user(f"{name.lower().replace(' ', '')}@test.com", security.hash_password("password123"))
    return repo.create_business(user_id, name, package="AI_ADMIN_PRO")


# ---------------------------------------------------------------------------
# appointments_repo.py
# ---------------------------------------------------------------------------

def test_appointment_persists_and_is_readable_after_simulated_restart():
    reset_db()
    business_id = _make_business()
    appt_id = appointments_repo.create_appointment(business_id, "62811111111", "Budi", "besok jam 14:00")
    assert appt_id is not None

    # "Restart" = drop the in-process DB connection entirely and reconnect — nothing here reads
    # any in-process dict, only the DB connection, so this proves the row is REALLY persisted.
    db.reset_connection_for_new_db_path()

    row = appointments_repo.get_latest_for_customer(business_id, "62811111111")
    assert row is not None
    assert row["status"] == "REQUESTED"
    assert row["customer_name"] == "Budi"
    assert row["request_text"] == "besok jam 14:00"
    print("test_appointment_persists_and_is_readable_after_simulated_restart OK")


def test_appointment_confirm_reschedule_cancel_update_the_persisted_row():
    reset_db()
    business_id = _make_business()
    appt_id = appointments_repo.create_appointment(business_id, "62811111112", "Sari", "Jumat jam 10:00")

    appointments_repo.update_status(appt_id, "CONFIRMED")
    row = appointments_repo.get_latest_for_customer(business_id, "62811111112")
    assert row["status"] == "CONFIRMED"

    appointments_repo.update_request_text(appt_id, "Sabtu jam 11:00", status="RESCHEDULE_REQUESTED")
    row = appointments_repo.get_latest_for_customer(business_id, "62811111112")
    assert row["status"] == "RESCHEDULE_REQUESTED"
    assert row["request_text"] == "Sabtu jam 11:00"

    appointments_repo.update_status(appt_id, "CANCELLED", notes="customer batal")
    row = appointments_repo.get_latest_for_customer(business_id, "62811111112")
    assert row["status"] == "CANCELLED"
    assert row["notes"] == "customer batal"
    print("test_appointment_confirm_reschedule_cancel_update_the_persisted_row OK")


def test_appointments_isolated_between_two_businesses_same_phone():
    reset_db()
    biz_a = _make_business("Kedai A")
    biz_b = _make_business("Kedai B")
    same_phone = "62899999999"
    appointments_repo.create_appointment(biz_a, same_phone, "Budi", "besok jam 9")

    assert appointments_repo.get_latest_for_customer(biz_a, same_phone) is not None
    assert appointments_repo.get_latest_for_customer(biz_b, same_phone) is None
    print("test_appointments_isolated_between_two_businesses_same_phone OK")


def test_find_by_customer_name_ambiguous_vs_single_match():
    reset_db()
    business_id = _make_business()
    appointments_repo.create_appointment(business_id, "62811111113", "Budi Santoso", "besok jam 9")
    appointments_repo.create_appointment(business_id, "62811111114", "Budi Kurniawan", "besok jam 10")

    matches = appointments_repo.find_by_customer_name(business_id, "Budi")
    assert len(matches) == 2, "both Budis must match a bare 'Budi' fragment"

    single = appointments_repo.find_by_customer_name(business_id, "Santoso")
    assert len(single) == 1 and single[0]["customer_phone"] == "62811111113"
    print("test_find_by_customer_name_ambiguous_vs_single_match OK")


# ---------------------------------------------------------------------------
# payment_reviews_repo.py
# ---------------------------------------------------------------------------

def test_payment_review_created_pending_and_persists():
    reset_db()
    business_id = _make_business()
    review_id = payment_reviews_repo.create_review(
        business_id, "62822222222", "Budi", amount_detected=150000,
    )
    db.reset_connection_for_new_db_path()

    review = payment_reviews_repo.get_review(review_id)
    assert review is not None
    assert review["status"] == "PENDING_OWNER_VERIFICATION"
    assert review["amount_detected"] == 150000
    assert review["verified_at"] is None
    print("test_payment_review_created_pending_and_persists OK")


def test_payment_review_confirm_and_reject_set_verified_fields():
    reset_db()
    business_id = _make_business()
    review_id = payment_reviews_repo.create_review(business_id, "62822222223", "Sari")
    payment_reviews_repo.update_status(review_id, "CONFIRMED", verified_by="628111000111")
    review = payment_reviews_repo.get_review(review_id)
    assert review["status"] == "CONFIRMED"
    assert review["verified_by"] == "628111000111"
    assert review["verified_at"] is not None

    review_id_2 = payment_reviews_repo.create_review(business_id, "62822222224", "Dewi")
    payment_reviews_repo.update_status(review_id_2, "REJECTED", owner_note="nominal kurang", verified_by="628111000111")
    review2 = payment_reviews_repo.get_review(review_id_2)
    assert review2["status"] == "REJECTED"
    assert review2["owner_note"] == "nominal kurang"
    print("test_payment_review_confirm_and_reject_set_verified_fields OK")


def test_payment_review_isolated_between_two_businesses_same_customer_name():
    reset_db()
    biz_a = _make_business("Kedai A2")
    biz_b = _make_business("Kedai B2")
    payment_reviews_repo.create_review(biz_a, "62833333331", "Budi", amount_detected=100000)
    payment_reviews_repo.create_review(biz_b, "62833333332", "Budi", amount_detected=200000)

    a_matches = payment_reviews_repo.find_by_customer_name(biz_a, "Budi")
    b_matches = payment_reviews_repo.find_by_customer_name(biz_b, "Budi")
    assert len(a_matches) == 1 and a_matches[0]["amount_detected"] == 100000
    assert len(b_matches) == 1 and b_matches[0]["amount_detected"] == 200000

    # get_review_scoped must never resolve a business A id under business B.
    a_id = a_matches[0]["id"]
    assert payment_reviews_repo.get_review_scoped(a_id, biz_a) is not None
    assert payment_reviews_repo.get_review_scoped(a_id, biz_b) is None
    print("test_payment_review_isolated_between_two_businesses_same_customer_name OK")


def test_store_proof_image_reuses_project_files_table():
    reset_db()
    business_id = _make_business()
    file_id = payment_reviews_repo.store_proof_image(business_id, b"fake-image-bytes", "image/jpeg")
    row = db.query_one("SELECT * FROM project_files WHERE id = ?", (file_id,))
    assert row is not None
    assert row["kind"] == "TENANT_PAYMENT_PROOF"
    assert row["business_id"] == business_id
    assert row["project_id"] is None
    assert bytes(row["content"]) == b"fake-image-bytes"

    scoped = payment_reviews_repo.get_proof_file_scoped(file_id, business_id)
    assert scoped is not None
    other_biz = _make_business("Someone Else")
    assert payment_reviews_repo.get_proof_file_scoped(file_id, other_biz) is None
    print("test_store_proof_image_reuses_project_files_table OK")


# ---------------------------------------------------------------------------
# wa_project_bridge.py — record-command classifier/resolvers
# ---------------------------------------------------------------------------

def test_classify_owner_record_command_variants():
    assert bridge.classify_owner_record_command("Confirm booking Budi.") == "CONFIRM_APPOINTMENT"
    assert bridge.classify_owner_record_command("Tolak yang jam 4, bilang penuh.") == "REJECT_APPOINTMENT"
    assert bridge.classify_owner_record_command("Confirm pembayaran Budi.") == "CONFIRM_PAYMENT"
    assert bridge.classify_owner_record_command("Tolak pembayaran Budi, nominalnya kurang.") == "REJECT_PAYMENT"
    # Plain queries/notes/relays must never be misclassified as a record command.
    assert bridge.classify_owner_record_command("Ada booking besok?") is None
    assert bridge.classify_owner_record_command("Bales Budi bilang stoknya ada.") is None
    assert bridge.classify_owner_record_command("") is None
    print("test_classify_owner_record_command_variants OK")


def test_extract_owner_command_reason_and_name():
    assert bridge.extract_owner_command_reason("Tolak yang jam 4, bilang penuh.") == "penuh"
    assert bridge.extract_owner_command_reason("Tolak pembayaran Budi, nominalnya kurang.") == "nominalnya kurang"
    assert bridge.extract_owner_command_reason("Confirm booking Budi.") is None

    assert bridge.extract_owner_command_target_name("Confirm booking Budi.") == "Budi"
    assert bridge.extract_owner_command_target_name("Tolak pembayaran Budi, nominalnya kurang.") == "Budi"
    assert bridge.extract_owner_command_target_name("Tolak yang jam 4, bilang penuh.") is None
    print("test_extract_owner_command_reason_and_name OK")


def test_resolve_appointment_target_by_name_time_and_ambiguity():
    appts = [
        {"id": 1, "customer_phone": "62811", "customer_name": "Budi", "request_text": "besok jam 16:00"},
        {"id": 2, "customer_phone": "62812", "customer_name": "Sari", "request_text": "besok jam 10:00"},
    ]
    matched, ambiguous = bridge.resolve_appointment_target(appts, "Confirm booking Budi.")
    assert matched is not None and matched["id"] == 1 and ambiguous is None

    matched2, ambiguous2 = bridge.resolve_appointment_target(appts, "Tolak yang jam 4, bilang penuh.")
    assert matched2 is not None and matched2["id"] == 1 and ambiguous2 is None

    ambiguous_appts = [
        {"id": 3, "customer_phone": "62813", "customer_name": "Budi Santoso", "request_text": "jam 9"},
        {"id": 4, "customer_phone": "62814", "customer_name": "Budi Kurniawan", "request_text": "jam 9"},
    ]
    matched3, ambiguous3 = bridge.resolve_appointment_target(ambiguous_appts, "Confirm booking Budi.")
    assert matched3 is None and ambiguous3 is not None and len(ambiguous3) == 2
    print("test_resolve_appointment_target_by_name_time_and_ambiguity OK")


def test_resolve_payment_review_target_by_name():
    reviews = [
        {"id": 10, "customer_phone": "62821", "customer_name": "Budi", "amount_claimed": None},
        {"id": 11, "customer_phone": "62822", "customer_name": "Dewi", "amount_claimed": None},
    ]
    matched, ambiguous = bridge.resolve_payment_review_target(reviews, "Confirm pembayaran Budi.")
    assert matched is not None and matched["id"] == 10 and ambiguous is None

    # A tenant B customer sharing the SAME name as a tenant A customer must never be reachable
    # here — the caller is responsible for passing in only THIS tenant's own reviews, and this
    # pure resolver only ever looks inside the list it's given.
    unrelated_tenant_reviews = [{"id": 99, "customer_phone": "62899", "customer_name": "Budi"}]
    matched2, _ = bridge.resolve_payment_review_target(unrelated_tenant_reviews, "Confirm pembayaran Budi.")
    assert matched2["id"] == 99  # proves scoping is entirely the CALLER's responsibility (by list)
    print("test_resolve_payment_review_target_by_name OK")


if __name__ == "__main__":
    test_appointment_persists_and_is_readable_after_simulated_restart()
    test_appointment_confirm_reschedule_cancel_update_the_persisted_row()
    test_appointments_isolated_between_two_businesses_same_phone()
    test_find_by_customer_name_ambiguous_vs_single_match()
    test_payment_review_created_pending_and_persists()
    test_payment_review_confirm_and_reject_set_verified_fields()
    test_payment_review_isolated_between_two_businesses_same_customer_name()
    test_store_proof_image_reuses_project_files_table()
    test_classify_owner_record_command_variants()
    test_extract_owner_command_reason_and_name()
    test_resolve_appointment_target_by_name_time_and_ambiguity()
    test_resolve_payment_review_target_by_name()
    print("\nALL TENANT PERSISTENCE REPO TESTS PASSED")
