"""Gap-fix Area G — talent admin photo upload: photo-only Gallery/Photos UX with
Preview/Replace/Remove before Save. Scope check: ONLY the talent admin photo upload changes;
payment-proof and custom-project-request uploads keep their original file-type support and
capture attribute untouched.

Run with:
    cd client-hub && python3 tests/test_talent_photo_upload_ux.py
"""
import os
import re
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402
import catalog_service  # noqa: E402
import talent_service  # noqa: E402
import app as client_hub_app  # noqa: E402

FLASK_APP = client_hub_app.app
FLASK_APP.testing = True

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "admin_talent.html")


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()
    catalog_service.seed_catalog_if_needed()
    talent_service.seed_talents_if_needed()


def _make_admin():
    admin_id = repo.create_user(f"admin_{os.urandom(4).hex()}@kilasworks.id",
                                 security.hash_password("adminpass123"), role="KILAS_ADMIN")
    return db.query_one("SELECT * FROM users WHERE id = ?", (admin_id,))


# ---------------------------------------------------------------------------
# 1. The talent photo file input is photo-only, no forced capture.
# ---------------------------------------------------------------------------
def test_talent_photo_input_is_image_only_no_forced_capture():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        html = f.read()
    # Find the photo upload <input type="file" name="photo" ...> tag specifically.
    match = re.search(r'<input type="file" name="photo"[^>]*>', html)
    assert match, "talent photo <input type=file name=photo> not found"
    tag = match.group(0)
    assert 'accept="image/*"' in tag, tag
    assert "capture=" not in tag, f"forced capture attribute must be removed: {tag}"
    print("test_talent_photo_input_is_image_only_no_forced_capture OK")


# ---------------------------------------------------------------------------
# 2. Preview / Replace / Remove UX elements and JS are present.
# ---------------------------------------------------------------------------
def test_preview_replace_remove_ux_present():
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        html = f.read()
    assert "talent-photo-preview-" in html, "preview <img> element missing"
    assert "talent-photo-pick-btn" in html, "pick/replace trigger button missing"
    assert "talent-photo-remove-btn" in html, "remove/cancel button missing"
    assert "FileReader" in html, "client-side preview (FileReader) JS missing"
    assert "readAsDataURL" in html
    print("test_preview_replace_remove_ux_present OK")


# ---------------------------------------------------------------------------
# 3. Scope check: payment-proof and custom-project-request uploads are UNCHANGED — still
#    accept their original (non-photo-only) file types and keep their capture attribute.
# ---------------------------------------------------------------------------
def test_other_uploads_unchanged_scope():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "templates", "invoice.html"), encoding="utf-8") as f:
        invoice_html = f.read()
    with open(os.path.join(repo_root, "templates", "custom_project_request.html"), encoding="utf-8") as f:
        custom_html = f.read()

    invoice_match = re.search(r'<input type="file" name="proof_file"[^>]*>', invoice_html)
    assert invoice_match, "payment proof file input not found"
    assert 'capture="environment"' in invoice_match.group(0), \
        "payment-proof upload must keep its original capture attribute (out of Area G scope)"
    assert ".pdf" in invoice_match.group(0), \
        "payment-proof upload must keep accepting non-image types (out of Area G scope)"

    custom_match = re.search(r'<input type="file" name="attachment"[^>]*>', custom_html)
    assert custom_match, "custom project attachment file input not found"
    assert 'capture="environment"' in custom_match.group(0), \
        "custom-project attachment upload must keep its original capture attribute (out of Area G scope)"
    assert ".pdf" in custom_match.group(0), \
        "custom-project attachment upload must keep accepting non-image types (out of Area G scope)"
    print("test_other_uploads_unchanged_scope OK")


# ---------------------------------------------------------------------------
# 4. The admin talent page still renders correctly (catches template syntax errors from the edit).
# ---------------------------------------------------------------------------
def test_admin_talent_page_renders_with_new_markup():
    reset_db()
    admin = _make_admin()
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = admin["id"]
            sess["role"] = "KILAS_ADMIN"
        resp = c.get("/admin/talent")
        assert resp.status_code == 200, resp.status_code
        assert b"talent-photo-pick-btn" in resp.data
    print("test_admin_talent_page_renders_with_new_markup OK")


# ---------------------------------------------------------------------------
# 5. Backend upload validation itself is untouched (still rejects non-images, still 5MB-capped) —
#    regression guard that Area G was frontend-only, per the "no architecture rewrite" rule.
# ---------------------------------------------------------------------------
def test_backend_photo_validation_unchanged():
    reset_db()
    admin = _make_admin()
    talent_id = db.query_one("SELECT id FROM talents LIMIT 1")["id"]
    with FLASK_APP.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = admin["id"]
            sess["role"] = "KILAS_ADMIN"
        import io
        resp = c.post(
            f"/admin/talent/{talent_id}/photo",
            data={"photo": (io.BytesIO(b"not a real image"), "fake.png")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Rejected (invalid image bytes) — must not silently succeed.
        talent_after = talent_service.get_talent(talent_id)
        assert talent_after.get("profile_image_asset_id") is None
    print("test_backend_photo_validation_unchanged OK")


if __name__ == "__main__":
    test_talent_photo_input_is_image_only_no_forced_capture()
    test_preview_replace_remove_ux_present()
    test_other_uploads_unchanged_scope()
    test_admin_talent_page_renders_with_new_markup()
    test_backend_photo_validation_unchanged()
    print("ALL TALENT PHOTO UPLOAD UX TESTS PASSED")
