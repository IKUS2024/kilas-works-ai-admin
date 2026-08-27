"""Kilas Admin review / approve / activate workflow (sections 17, 18, 28, 30).

Every route here is guarded by @security.admin_required, so only role == "KILAS_ADMIN" can reach
any of it. Admin routes are the ONE place allowed to see across tenants (repo.list_all_businesses,
repo.get_business_file_content without a business_id filter isn't used — we still pass business_id
for defense in depth, admin just doesn't need a membership row).

Section 30 activation gate: a business only becomes ACTIVE when
  (a) it has been APPROVED by an admin, AND
  (b) whatsapp_connected == 1 (set via the "Connect WhatsApp" action below).
Until (b), the UI shows "APPROVED — WAITING_WHATSAPP_CONNECTION" even though the DB status column
is still literally "APPROVED" — see get_display_status() below, reused by templates.
"""
import io

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file

import ai_onboarding
import db
import repo
import security
import file_utils
import provisioning

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

STATUS_FILTERS = ("READY_FOR_REVIEW", "NEEDS_REVISION", "APPROVED", "ACTIVE")


def get_display_status(business):
    """APPROVED-but-not-connected reads as a distinct pseudo-status in the UI (section 30)."""
    if business["status"] == "APPROVED" and not business["whatsapp_connected"]:
        return "APPROVED_WAITING_WHATSAPP_CONNECTION"
    return business["status"]


@admin_bp.route("/")
@security.admin_required
def dashboard():
    status_filter = request.args.get("status") or None
    if status_filter not in (None, *STATUS_FILTERS):
        status_filter = None
    businesses = repo.list_all_businesses(status_filter=status_filter)
    for b in businesses:
        b["display_status"] = get_display_status(b)
    return render_template(
        "admin_dashboard.html",
        businesses=businesses,
        status_filter=status_filter,
        status_filters=STATUS_FILTERS,
    )


@admin_bp.route("/business/<int:business_id>")
@security.admin_required
def review_business(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    profile = repo.get_business_profile(business_id)
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)
    files = repo.list_business_files(business_id)
    ai_settings = repo.get_ai_settings(business_id)
    onboarding_status = repo.get_onboarding_status(business_id)
    missing_required = repo.required_fields_missing(business_id)
    audit_log = repo.get_audit_log(business_id)
    flagged = repo.list_flagged_simulation_messages(business_id)
    whatsapp_config = repo.get_whatsapp_config(business_id)
    tenant_config_row = repo.get_tenant_config_row(business_id)
    business["display_status"] = get_display_status(business)
    return render_template(
        "review.html",
        business=business,
        profile=profile,
        services=services,
        faqs=faqs,
        files=files,
        ai_settings=ai_settings,
        onboarding_status=onboarding_status,
        missing_required=missing_required,
        audit_log=audit_log,
        flagged=flagged,
        whatsapp_config=whatsapp_config,
        tenant_config_row=tenant_config_row,
        is_admin_view=True,
    )


@admin_bp.route("/business/<int:business_id>/ai-setup/retry", methods=["POST"])
@security.admin_required
def retry_ai_setup(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    profile = repo.get_business_profile(business_id) or {}
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)
    files = repo.list_business_files(business_id)
    extracted_texts = [f["extracted_text"] for f in files if f.get("extracted_text")]

    repo.set_ai_status(business_id, "RUNNING")
    config, error = ai_onboarding.normalize_business_data(business, profile, services, faqs, extracted_texts)

    if error:
        repo.set_ai_status(business_id, "FAILED", error=error)
        repo.write_audit(admin["id"], business_id, "ai_normalization_failed", f"(admin retry) {error}")
        flash("AI setup masih gagal. Data client tetap aman — coba lagi nanti.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    for row, normalized in zip(services, config.get("services", [])):
        repo.update_normalized_service(
            row["id"], normalized.get("service_name"), normalized.get("description"),
            normalized.get("price_from"), normalized.get("price_to"),
            normalized.get("currency", "IDR"), normalized.get("needs_review", True),
        )
    for row, normalized in zip(faqs, config.get("faqs", [])):
        repo.update_normalized_faq(
            row["id"], normalized.get("question"), normalized.get("answer"),
            normalized.get("category", "general"), normalized.get("needs_review", True),
        )
    repo.save_ai_normalized_config(business_id, config.get("description", ""), config, config.get("missing_fields", []))
    repo.set_business_status(business_id, "READY_FOR_REVIEW", actor_user_id=admin["id"], detail="admin retried AI setup")
    repo.write_audit(admin["id"], business_id, "ai_normalization_run", "(admin retry) success")
    flash("AI setup berhasil dijalankan ulang.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/approve", methods=["POST"])
@security.admin_required
def approve(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    missing = repo.required_fields_missing(business_id)
    ai_settings = repo.get_ai_settings(business_id)
    if missing:
        flash(f"Belum bisa approve — field wajib belum lengkap: {', '.join(missing)}.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    if not ai_settings or ai_settings.get("ai_status") != "DONE":
        flash("Belum bisa approve — AI setup belum selesai/berhasil.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    try:
        provisioning.approve_and_provision(business_id, admin)
    except provisioning.ProvisioningError as e:
        flash(f"Approve gagal: {e}", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    flash("Business di-approve dan tenant config sudah dibuat. Selanjutnya hubungkan WhatsApp lalu Activate.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/request-revision", methods=["POST"])
@security.admin_required
def request_revision(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    note = (request.form.get("note") or "").strip()
    if not note:
        flash("Tulis catatan revisi untuk client.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    repo.request_revision(business_id, admin["id"], note)
    flash("Revisi diminta ke client.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/connect-whatsapp", methods=["POST"])
@security.admin_required
def connect_whatsapp(business_id):
    """Section 30/section 3-of-19: this is the ONE deliberately manual step in V1 — the admin
    types in the phone_number_id + trusted owner phone after doing the real Meta connection
    themselves. Nothing here talks to the Meta API — 'JANGAN mengotomatisasi Meta onboarding
    secara asal.'"""
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    if business["status"] != "APPROVED":
        flash("Business harus berstatus APPROVED dulu sebelum menghubungkan WhatsApp.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    phone_number_id = (request.form.get("whatsapp_phone_number_id") or "").strip()
    trusted_owner_phone = (request.form.get("trusted_owner_phone") or "").strip()
    waba_id = (request.form.get("waba_id") or "").strip() or None
    credentials_reference = (request.form.get("credentials_reference") or "").strip()
    if not phone_number_id or not trusted_owner_phone:
        flash("Isi WhatsApp Phone Number ID dan nomor owner terpercaya.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    if not credentials_reference:
        # Sensible default reference name — the ACTUAL token still lives only in env vars /
        # secret manager, never in this table. See provisioning.py / final report.
        credentials_reference = f"WHATSAPP_TOKEN__TENANT_{business_id}"

    # Kept for backward compatibility with V1 (businesses.whatsapp_connected drives the existing
    # activation gate and display_status logic below) — dual-written alongside the new
    # tenant_whatsapp_config table, which is the Phase 2 canonical home for this data going forward.
    db.execute(
        "UPDATE businesses SET whatsapp_phone_number_id = ?, trusted_owner_phone = ?, "
        "whatsapp_connected = ?, updated_at = ? WHERE id = ?",
        (phone_number_id, trusted_owner_phone, True, repo._now(), business_id),
    )
    try:
        provisioning.connect_whatsapp_credentials(business_id, admin, phone_number_id, waba_id, credentials_reference)
    except provisioning.ProvisioningError as e:
        flash(f"Gagal menyimpan konfigurasi WhatsApp: {e}", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    flash("WhatsApp terhubung. Business siap di-Activate.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/activate", methods=["POST"])
@security.admin_required
def activate(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    try:
        result = provisioning.activate_tenant(business_id, admin)
    except provisioning.ProvisioningError as e:
        flash(f"Belum bisa Activate: {e}", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    if result["changed"]:
        flash("Business ACTIVE. AI Admin engine sekarang bisa memakai tenant ini.", "success")
    else:
        flash("Business sudah ACTIVE sebelumnya — tidak ada perubahan.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/deactivate", methods=["POST"])
@security.admin_required
def deactivate(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    provisioning.deactivate_tenant(business_id, admin)
    flash("Business di-nonaktifkan (SUSPENDED).", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/package", methods=["POST"])
@security.admin_required
def change_package(business_id):
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    package = request.form.get("package")
    if package not in repo.DEFAULT_FEATURES:
        flash("Paket tidak valid.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    repo.set_business_package(business_id, package, actor_user_id=admin["id"])
    flash(f"Paket diubah ke {package}.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/business/<int:business_id>/files/<int:file_id>/download")
@security.admin_required
def download_file(business_id, file_id):
    row = repo.get_business_file_content(file_id, business_id)
    if not row:
        abort(404)
    return send_file(
        io.BytesIO(row["content"]),
        mimetype=row["mime_type"] or "application/octet-stream",
        as_attachment=True,
        download_name=row["original_filename"],
    )


@admin_bp.route("/business/<int:business_id>/simulate")
@security.admin_required
def simulate_page(business_id):
    """Admin can also open the Test-AI sandbox for any tenant (section 17: 'TEST AI' action).
    Reuses the exact same isolated simulation_messages table/session-token pattern as the client
    side — see routes_client.simulate_page for the customer-facing twin of this route."""
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    import uuid
    from flask import session
    token_key = f"sim_token_{business_id}"
    if token_key not in session:
        session[token_key] = uuid.uuid4().hex
    history = repo.get_simulation_history(business_id, session[token_key])
    return render_template("simulate.html", business=business, history=history, is_admin_view=True)
