"""Client Hub new-customer service selection + purchase flow — regression tests.

Run with:
    cd client-hub && python3 tests/test_service_selection_purchase_flow.py
"""
import os
import sys
import io
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import projects_repo  # noqa: E402
import payment_service  # noqa: E402
import ai_payment_review  # noqa: E402
import talent_service  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True


def fresh_client():
    return FLASK_APP.test_client()


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()


def _make_owner_and_business(name, email, package="NONE"):
    uid = repo.create_user(email, security.hash_password("password123"))
    bid = repo.create_business(uid, name, package=package)
    return uid, bid


def _make_admin_user():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


def _login_admin(client, admin):
    client.post("/login", data={"email": admin["email"], "password": "adminpass123"})


def _login_owner(client, email, password="password123"):
    client.post("/login", data={"email": email, "password": password})


# ---------------------------------------------------------------------------
# 1/2. New customer selects a fixed-price non-AI service -> reaches checkout.
# ---------------------------------------------------------------------------
def test_new_customer_can_select_fixed_price_service_and_reach_checkout():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Fixed", "fixed@test.com")
    client = fresh_client()
    _login_owner(client, "fixed@test.com")
    body_before = client.get("/services").data.decode()
    assert "Pilih Layanan" in body_before

    item = catalog_service.get_catalog_item("website_landing_page")
    resp = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 302
    assert "/checkout" in resp.headers["Location"] or "/projects/" in resp.headers["Location"]
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1
    assert projects[0]["status"] == "APPROVED"
    assert projects[0]["catalog_key"] == item["catalog_key"]
    print("test_new_customer_can_select_fixed_price_service_and_reach_checkout OK")


# ---------------------------------------------------------------------------
# 3. AI Admin still routes to onboarding, not generic checkout.
# ---------------------------------------------------------------------------
def test_ai_admin_never_uses_generic_checkout_route():
    reset_db()
    uid, bid = _make_owner_and_business("Biz AIAdmin", "aiadmin@test.com")
    client = fresh_client()
    _login_owner(client, "aiadmin@test.com")
    body = client.get("/services").data.decode()
    ai_idx = body.find("AI Admin Basic")
    assert ai_idx != -1
    section = body[ai_idx:ai_idx + 400]
    assert "Mulai di Dashboard" in section
    assert 'action="/services/ai_admin_basic/checkout-fixed"' not in section

    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    resp = client.post(f"/services/{ai_item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"], \
        "even a direct POST to the generic checkout route must redirect AI Admin to the dashboard, never create a project"
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 0, "AI Admin must never get a project via the generic instant-checkout path"
    print("test_ai_admin_never_uses_generic_checkout_route OK")


# ---------------------------------------------------------------------------
# 4. CUSTOM_QUOTE creates a quote/request flow without an invented price.
# ---------------------------------------------------------------------------
def test_custom_quote_generic_route_creates_request_without_price():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Quote", "quote@test.com")
    client = fresh_client()
    _login_owner(client, "quote@test.com")

    # No existing seeded CUSTOM_QUOTE item falls outside the whitelisted categories today — create
    # one via the same admin catalog-creation path a real admin would use, to genuinely exercise
    # the new generic route rather than one already covered by a dedicated flow.
    new_id = catalog_service.create_catalog_item("EVENT", "Dokumentasi Event Custom", "CUSTOM_QUOTE")
    item = catalog_service.get_catalog_item_by_id(new_id)

    body = client.get("/services").data.decode()
    assert "Minta Penawaran" in body

    resp = client.post(f"/services/{item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": str(bid), "notes": "Butuh dokumentasi untuk gathering kantor",
    })
    assert resp.status_code == 302
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1
    assert projects[0]["status"] == "WAITING_FOR_QUOTE"
    assert projects[0]["final_price"] is None, "a CUSTOM_QUOTE request must never have an invented price"
    print("test_custom_quote_generic_route_creates_request_without_price OK")


def test_custom_quote_talent_and_content_still_use_dedicated_flows():
    """Regression lock: TALENT/CONTENT/VIDEO/PHOTO/WEBSITE/APPLICATION must keep using their own
    dedicated, more detailed request flow — the new generic route must never intercept those."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz Dedicated", "dedicated@test.com")
    client = fresh_client()
    _login_owner(client, "dedicated@test.com")
    talent_item = catalog_service.get_catalog_item("talent_management")
    resp = client.post(f"/services/{talent_item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 404, "TALENT must never be reachable via the generic quote route"
    custom_video_item = catalog_service.get_catalog_item("custom_video")
    resp2 = client.post(f"/services/{custom_video_item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp2.status_code == 404, "VIDEO must never be reachable via the generic quote route either"
    print("test_custom_quote_talent_and_content_still_use_dedicated_flows OK")


# ---------------------------------------------------------------------------
# 5. Inactive service cannot be selected.
# ---------------------------------------------------------------------------
def test_inactive_service_cannot_be_selected():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Inactive", "inactive@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], is_active=False)
    client = fresh_client()
    _login_owner(client, "inactive@test.com")
    body = client.get("/services").data.decode()
    assert f">{item['name']}<" not in body, "an inactive service must not even be listed"

    resp = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 404, "a direct POST to an inactive service's checkout must be rejected"
    print("test_inactive_service_cannot_be_selected OK")


# ---------------------------------------------------------------------------
# 6/7. Repeated click does not duplicate; unfinished project uses Continue.
# ---------------------------------------------------------------------------
def test_repeated_click_reuses_existing_project_not_duplicate():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Repeat", "repeat@test.com")
    client = fresh_client()
    _login_owner(client, "repeat@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")

    resp1 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    resp2 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1, f"repeated click must reuse the same project, got {len(projects)}"
    # The two redirects don't have to be byte-identical URLs (the first click can go straight to
    # checkout; a repeat click reasonably lands on the project detail page instead) — what matters
    # is that both point at the SAME underlying project, never a second one.
    assert str(projects[0]["id"]) in resp1.headers["Location"] or "/checkout" in resp1.headers["Location"]
    assert str(projects[0]["id"]) in resp2.headers["Location"]
    print("test_repeated_click_reuses_existing_project_not_duplicate OK")


def test_unfinished_project_shows_lanjutkan_on_catalog_page():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Continue", "continue@test.com")
    client = fresh_client()
    _login_owner(client, "continue@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    body = client.get("/services").data.decode()
    assert "Lanjutkan" in body
    idx = body.find(f">{item['name']}<")
    assert idx != -1
    section = body[idx:idx + 800]
    assert "Lanjutkan" in section
    print("test_unfinished_project_shows_lanjutkan_on_catalog_page OK")


def test_cancelled_project_does_not_block_new_selection():
    """A CANCELLED project must never count as "unfinished" — the customer should be able to
    start a fresh selection for the same service after cancelling."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz Cancelled", "cancelled@test.com")
    client = fresh_client()
    _login_owner(client, "cancelled@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    project = projects_repo.list_projects_for_business(bid)[0]
    client.post(f"/business/{bid}/projects/{project['id']}/cancel", data={"csrf_token": "x"})

    resp2 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp2.status_code == 302
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 2, "a cancelled project must not block a fresh new selection"
    print("test_cancelled_project_does_not_block_new_selection OK")


# ---------------------------------------------------------------------------
# 8. Canonical live price is used.
# ---------------------------------------------------------------------------
def test_checkout_uses_canonical_live_price():
    reset_db()
    uid, bid = _make_owner_and_business("Biz Price", "price@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    catalog_service.update_catalog_item(item["id"], price_amount=888000)
    client = fresh_client()
    _login_owner(client, "price@test.com")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    project = projects_repo.list_projects_for_business(bid)[0]
    assert project["final_price"] == 888000, "the project must lock in the CURRENT canonical price at selection time"
    print("test_checkout_uses_canonical_live_price OK")


# ---------------------------------------------------------------------------
# ZERO-BUSINESS PURCHASE FLOW (only AI Admin requires a real business — no
# placeholder/auto-created business is ever created for anything else)
# ---------------------------------------------------------------------------
def _valid_png_bytes():
    from PIL import Image
    import io as _io
    img = Image.new("RGB", (10, 10), color="white")
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_zero_business_customer_sees_actionable_ctas_not_blocking_gate():
    reset_db()
    uid = repo.create_user("zero@test.com", security.hash_password("password123"))
    client = fresh_client()
    _login_owner(client, "zero@test.com")
    body = client.get("/services").data.decode()
    assert "Pilih Layanan" in body
    assert "Minta Penawaran" in body
    assert "Buat Bisnis Dulu" not in body
    print("test_zero_business_customer_sees_actionable_ctas_not_blocking_gate OK")


def test_zero_business_fixed_service_reaches_invoice_and_payment_no_business_created():
    """The full required end-to-end path: select -> project -> checkout -> invoice -> payment
    proof upload -> AI review -> ready for admin approval — entirely without a business, and
    confirming zero business rows are ever created along the way."""
    reset_db()
    uid = repo.create_user("zerofixed@test.com", security.hash_password("password123"))
    client = fresh_client()
    _login_owner(client, "zerofixed@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")

    r1 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": "",
    })
    assert r1.status_code == 302
    assert repo.list_businesses_for_user(uid) == [], "no business row may ever be created"

    r2 = client.get(r1.headers["Location"])
    assert r2.status_code == 200

    r3 = client.post(r1.headers["Location"])
    assert r3.status_code == 302
    invoice_url = r3.headers["Location"]
    invoice_id = int(invoice_url.rstrip("/").split("/")[-1])

    r4 = client.get(invoice_url)
    assert r4.status_code == 200

    r5 = client.post(invoice_url, data={
        "csrf_token": "x", "proof_file": (io.BytesIO(_valid_png_bytes()), "proof.png"),
    }, content_type="multipart/form-data")
    assert r5.status_code == 302

    payment = payment_service.get_payment_for_invoice(invoice_id)
    assert payment["status"] == "UNDER_REVIEW", "AI review must have run and moved the payment forward"
    assert payment["business_id"] is None

    r6 = client.get(f"/invoices/{invoice_id}/proof")
    assert r6.status_code == 200, "the customer must be able to view their own uploaded proof"

    assert repo.list_businesses_for_user(uid) == [], "STILL no business row after the full flow"
    print("test_zero_business_fixed_service_reaches_invoice_and_payment_no_business_created OK")


def test_zero_business_payment_proof_upload_and_ai_review_work_with_null_business():
    reset_db()
    uid = repo.create_user("zeroproof@test.com", security.hash_password("password123"))
    client = fresh_client()
    _login_owner(client, "zeroproof@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    r1 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={"csrf_token": "x", "business_id": ""})
    r3 = client.post(r1.headers["Location"])
    invoice_id = int(r3.headers["Location"].rstrip("/").split("/")[-1])

    proof_hash_before = ai_payment_review.compute_file_hash(_valid_png_bytes())
    client.post(r3.headers["Location"], data={
        "csrf_token": "x", "proof_file": (io.BytesIO(_valid_png_bytes()), "proof.png"),
    }, content_type="multipart/form-data")

    payment = payment_service.get_payment_for_invoice(invoice_id)
    assert payment["proof_file_hash"] == proof_hash_before, "proof_file_hash must still be computed and stored"
    assert payment["status"] == "UNDER_REVIEW"
    print("test_zero_business_payment_proof_upload_and_ai_review_work_with_null_business OK")


def test_zero_business_admin_verify_reject_reupload_all_work():
    reset_db()
    uid = repo.create_user("zeroadmin@test.com", security.hash_password("password123"))
    admin = _make_admin_user()
    client = fresh_client()
    _login_owner(client, "zeroadmin@test.com")

    def new_invoice(catalog_key):
        item = catalog_service.get_catalog_item(catalog_key)
        r1 = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={"csrf_token": "x", "business_id": ""})
        r3 = client.post(r1.headers["Location"])
        invoice_id = int(r3.headers["Location"].rstrip("/").split("/")[-1])
        client.post(r3.headers["Location"], data={
            "csrf_token": "x", "proof_file": (io.BytesIO(_valid_png_bytes()), "proof.png"),
        }, content_type="multipart/form-data")
        return payment_service.get_payment_for_invoice(invoice_id)

    admin_client = fresh_client()
    _login_admin(admin_client, admin)

    # Different catalog items per call — reusing the SAME one would hit the intentional repeat-
    # click reuse logic and collide with the previous (already-verified/rejected) payment.
    payment1 = new_invoice("website_landing_page")
    r_verify = admin_client.post(f"/admin/payments/{payment1['id']}/verify", data={"csrf_token": "x"})
    assert r_verify.status_code == 302
    assert payment_service.get_payment(payment1["id"])["status"] == "VERIFIED"

    payment2 = new_invoice("ads_management")
    r_reject = admin_client.post(f"/admin/payments/{payment2['id']}/reject", data={"csrf_token": "x", "admin_notes": "blur"})
    assert r_reject.status_code == 302
    assert payment_service.get_payment(payment2["id"])["status"] == "REJECTED"

    payment3 = new_invoice("website_company_profile")
    r_reupload = admin_client.post(f"/admin/payments/{payment3['id']}/request-reupload", data={"csrf_token": "x"})
    assert r_reupload.status_code == 302
    assert payment_service.get_payment(payment3["id"])["status"] == "PAYMENT_PENDING"

    assert repo.list_businesses_for_user(uid) == []
    print("test_zero_business_admin_verify_reject_reupload_all_work OK")


def test_zero_business_talent_request_creates_no_business():
    reset_db()
    uid = repo.create_user("zerotalent@test.com", security.hash_password("password123"))
    talent_service.seed_talents_if_needed()
    client = fresh_client()
    _login_owner(client, "zerotalent@test.com")
    talents = talent_service.list_active_talents()
    resp = client.post(f"/talent/{talents[0]['id']}/request", data={
        "csrf_token": "x", "campaign_type": "endorsement",
    })
    assert resp.status_code == 302
    assert repo.list_businesses_for_user(uid) == []
    projects = db.query_all("SELECT * FROM projects WHERE created_by_user_id = ?", (uid,))
    assert len(projects) == 1
    assert projects[0]["business_id"] is None
    print("test_zero_business_talent_request_creates_no_business OK")


def test_zero_business_custom_project_request_creates_no_business():
    reset_db()
    uid = repo.create_user("zerocustom@test.com", security.hash_password("password123"))
    client = fresh_client()
    _login_owner(client, "zerocustom@test.com")
    resp = client.post("/projects/custom/CONTENT", data={
        "csrf_token": "x", "need": "foto produk", "quantity": "10",
    })
    assert resp.status_code == 302
    assert repo.list_businesses_for_user(uid) == []
    projects = db.query_all("SELECT * FROM projects WHERE created_by_user_id = ?", (uid,))
    assert len(projects) == 1
    print("test_zero_business_custom_project_request_creates_no_business OK")


def test_zero_business_generic_quote_request_creates_no_business():
    reset_db()
    uid = repo.create_user("zeroquote@test.com", security.hash_password("password123"))
    new_id = catalog_service.create_catalog_item("EVENT", "Dokumentasi Event Custom 2", "CUSTOM_QUOTE")
    item = catalog_service.get_catalog_item_by_id(new_id)
    client = fresh_client()
    _login_owner(client, "zeroquote@test.com")
    resp = client.post(f"/services/{item['catalog_key']}/request-quote", data={
        "csrf_token": "x", "business_id": "", "notes": "test",
    })
    assert resp.status_code == 302
    assert repo.list_businesses_for_user(uid) == []
    projects = db.query_all("SELECT * FROM projects WHERE created_by_user_id = ?", (uid,))
    assert len(projects) == 1
    assert projects[0]["final_price"] is None
    print("test_zero_business_generic_quote_request_creates_no_business OK")


def test_zero_business_repeat_selection_reuses_same_project_no_business_ever():
    reset_db()
    uid = repo.create_user("zerorepeat@test.com", security.hash_password("password123"))
    client = fresh_client()
    _login_owner(client, "zerorepeat@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={"csrf_token": "x", "business_id": ""})
    client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={"csrf_token": "x", "business_id": ""})
    projects = db.query_all("SELECT * FROM projects WHERE created_by_user_id = ?", (uid,))
    assert len(projects) == 1, "repeat selection of the SAME service must reuse the same project"
    assert repo.list_businesses_for_user(uid) == []
    print("test_zero_business_repeat_selection_reuses_same_project_no_business_ever OK")


def test_ai_admin_still_requires_business_even_with_zero_businesses():
    """Regression lock: AI Admin must still land on the dashboard and never create a project via
    the generic checkout path, business or no business."""
    reset_db()
    uid = repo.create_user("zeroai@test.com", security.hash_password("password123"))
    client = fresh_client()
    _login_owner(client, "zeroai@test.com")
    ai_item = catalog_service.get_catalog_item("ai_admin_basic")
    resp = client.post(f"/services/{ai_item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": "",
    })
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]
    assert repo.list_businesses_for_user(uid) == []
    print("test_ai_admin_still_requires_business_even_with_zero_businesses OK")


def test_existing_business_purchase_flow_unaffected():
    """Regression lock: a customer who already has a business must see their normal business-
    scoped project/checkout flow, exactly as before this correction."""
    reset_db()
    uid, bid = _make_owner_and_business("Biz Existing", "existing@test.com")
    client = fresh_client()
    _login_owner(client, "existing@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    resp = client.post(f"/services/{item['catalog_key']}/checkout-fixed", data={
        "csrf_token": "x", "business_id": str(bid),
    })
    assert resp.status_code == 302
    projects = projects_repo.list_projects_for_business(bid)
    assert len(projects) == 1
    assert projects[0]["business_id"] == bid
    detail = client.get(f"/business/{bid}/projects/{projects[0]['id']}")
    assert detail.status_code == 200
    print("test_existing_business_purchase_flow_unaffected OK")


def test_business_scoped_tenant_isolation_unchanged():
    """Regression lock: a business-scoped project must still be completely inaccessible to a
    different business's owner — the owner-based fallback for business-less projects must never
    weaken this."""
    reset_db()
    uid1, bid1 = _make_owner_and_business("Biz A", "tenanta@test.com")
    uid2, bid2 = _make_owner_and_business("Biz B", "tenantb@test.com")
    client1 = fresh_client()
    _login_owner(client1, "tenanta@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    client1.post(f"/services/{item['catalog_key']}/checkout-fixed", data={"csrf_token": "x", "business_id": str(bid1)})
    project = projects_repo.list_projects_for_business(bid1)[0]

    client2 = fresh_client()
    _login_owner(client2, "tenantb@test.com")
    resp = client2.get(f"/business/{bid1}/projects/{project['id']}")
    assert resp.status_code == 404, "tenant B must never see tenant A's business-scoped project"
    print("test_business_scoped_tenant_isolation_unchanged OK")


def test_zero_business_project_not_accessible_to_a_different_user():
    """Owner-based access for business-less projects must still be genuinely scoped to the
    creating user, not open to any logged-in customer."""
    reset_db()
    uid1 = repo.create_user("owner1@test.com", security.hash_password("password123"))
    uid2 = repo.create_user("owner2@test.com", security.hash_password("password123"))
    client1 = fresh_client()
    _login_owner(client1, "owner1@test.com")
    item = catalog_service.get_catalog_item("website_landing_page")
    r1 = client1.post(f"/services/{item['catalog_key']}/checkout-fixed", data={"csrf_token": "x", "business_id": ""})
    project_id = int(r1.headers["Location"].rstrip("/").split("/")[2])

    client2 = fresh_client()
    _login_owner(client2, "owner2@test.com")
    resp = client2.get(f"/projects/{project_id}")
    assert resp.status_code == 404
    print("test_zero_business_project_not_accessible_to_a_different_user OK")


# ---------------------------------------------------------------------------
# MIGRATIONS 0021 + 0022 — fresh DB, populated DB, repeated idempotency.
# ---------------------------------------------------------------------------
def test_migrations_0021_0022_apply_cleanly_on_fresh_db():
    reset_db()  # a fresh init_schema() call already ran every migration in order
    conn = db.get_connection()
    for tbl, col in (("projects", "business_id"), ("invoices", "business_id"),
                      ("payments", "business_id"), ("project_files", "business_id"),
                      ("talent_requests", "business_id")):
        info = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
        col_info = next(r for r in info if r[1] == col)
        assert col_info[3] == 0, f"{tbl}.{col} must be nullable (notnull flag), got {col_info[3]}"
    print("test_migrations_0021_0022_apply_cleanly_on_fresh_db OK")


def test_migrations_0021_0022_apply_cleanly_on_populated_db():
    """Directly reproduces the real production scenario: migrations 0001-0020 already applied
    with real data in every affected child table, THEN 0021+0022 run on top. Replays db.py's own
    MIGRATIONS list with the SAME idempotent-execution behavior db.init_schema() itself uses
    (including its documented handling of "duplicate column name" from a plain ALTER TABLE ADD
    COLUMN migration being re-run) — never a bespoke, less-forgiving replay of the raw files."""
    import sqlite3
    db_path = tempfile.mktemp(suffix=".db")
    os.environ["CLIENT_HUB_DB_PATH"] = db_path
    db._local.conn = None
    conn = db.get_connection()

    def _run_migration(sqlite_name, postgres_name):
        path = db._migration_path(sqlite_name, postgres_name)
        with open(path, "r", encoding="utf-8") as f:
            script = f.read()
        try:
            conn.executescript(script)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e):
                raise
        conn.commit()

    cutoff_index = next(i for i, (s, p) in enumerate(db.MIGRATIONS) if "0021" in s)
    for sqlite_name, postgres_name in db.MIGRATIONS[:cutoff_index]:
        _run_migration(sqlite_name, postgres_name)

    catalog_service.seed_catalog_if_needed()
    talent_service.seed_talents_if_needed()
    uid = repo.create_user("populated@test.com", security.hash_password("password123"))
    bid = repo.create_business(uid, "Populated Biz", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(pid, bid, uid)
    conn.execute(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', 'p.png', "
        "'image/png', 10, ?, ?)",
        (bid, pid, b"fakeimg", uid),
    )
    talents = talent_service.list_active_talents()
    talent_service.create_talent_request(talents[0]["id"], bid, {"campaign_type": "x"}, uid)
    conn.commit()

    for sqlite_name, postgres_name in db.MIGRATIONS[cutoff_index:cutoff_index + 2]:
        _run_migration(sqlite_name, postgres_name)

    for tbl in ("projects", "invoices", "payments", "project_files", "talent_requests"):
        cur = conn.execute(f"SELECT COUNT(*) FROM {tbl}")
        assert cur.fetchone()[0] >= 1, f"{tbl} must retain its pre-migration data"
    print("test_migrations_0021_0022_apply_cleanly_on_populated_db OK")


def test_migrations_0021_0022_idempotent_on_repeated_init_schema():
    reset_db()
    uid = repo.create_user("idempotent@test.com", security.hash_password("password123"))
    bid = repo.create_business(uid, "Idempotent Biz", package="NONE")
    item = catalog_service.get_catalog_item("website_landing_page")
    pid = projects_repo.create_fixed_price_project(bid, item, uid)
    invoice_id = payment_service.checkout(pid, bid, uid)
    db.init_schema()
    db.init_schema()
    db.init_schema()
    invoice = payment_service.get_invoice(invoice_id)
    assert invoice is not None
    assert invoice["business_id"] == bid
    print("test_migrations_0021_0022_idempotent_on_repeated_init_schema OK")


# ---------------------------------------------------------------------------
# PAYMENT PROOF UPLOAD UX — gallery/files/camera, not camera-only.
# ---------------------------------------------------------------------------
def test_payment_proof_upload_does_not_force_camera_capture():
    with open("templates/invoice.html", encoding="utf-8") as f:
        html = f.read()
    idx = html.find('name="proof_file"')
    assert idx != -1
    input_tag = html[max(0, idx - 20):idx + 150]
    assert "capture=" not in input_tag, \
        "the payment proof file input must not force camera-only capture — it must allow gallery/files/camera equally"
    assert 'accept=".pdf,.png,.jpg,.jpeg,.webp,image/*"' in input_tag
    print("test_payment_proof_upload_does_not_force_camera_capture OK")


def test_payment_upload_route_and_verification_mechanism_unchanged():
    assert hasattr(payment_service, "upload_payment_proof")
    assert hasattr(ai_payment_review, "compute_file_hash")
    assert hasattr(ai_payment_review, "extract_payment_proof_fields")
    print("test_payment_upload_route_and_verification_mechanism_unchanged OK")


if __name__ == "__main__":

    test_new_customer_can_select_fixed_price_service_and_reach_checkout()
    test_ai_admin_never_uses_generic_checkout_route()
    test_custom_quote_generic_route_creates_request_without_price()
    test_custom_quote_talent_and_content_still_use_dedicated_flows()
    test_inactive_service_cannot_be_selected()
    test_repeated_click_reuses_existing_project_not_duplicate()
    test_unfinished_project_shows_lanjutkan_on_catalog_page()
    test_cancelled_project_does_not_block_new_selection()
    test_checkout_uses_canonical_live_price()
    test_zero_business_customer_sees_actionable_ctas_not_blocking_gate()
    test_zero_business_fixed_service_reaches_invoice_and_payment_no_business_created()
    test_zero_business_payment_proof_upload_and_ai_review_work_with_null_business()
    test_zero_business_admin_verify_reject_reupload_all_work()
    test_zero_business_talent_request_creates_no_business()
    test_zero_business_custom_project_request_creates_no_business()
    test_zero_business_generic_quote_request_creates_no_business()
    test_zero_business_repeat_selection_reuses_same_project_no_business_ever()
    test_ai_admin_still_requires_business_even_with_zero_businesses()
    test_existing_business_purchase_flow_unaffected()
    test_business_scoped_tenant_isolation_unchanged()
    test_zero_business_project_not_accessible_to_a_different_user()
    test_migrations_0021_0022_apply_cleanly_on_fresh_db()
    test_migrations_0021_0022_apply_cleanly_on_populated_db()
    test_migrations_0021_0022_idempotent_on_repeated_init_schema()
    test_payment_proof_upload_does_not_force_camera_capture()
    test_payment_upload_route_and_verification_mechanism_unchanged()
    print("ALL SERVICE SELECTION PURCHASE FLOW TESTS PASSED")
