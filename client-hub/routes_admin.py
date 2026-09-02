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
import catalog_service
import projects_repo
import quotation_service
import payment_service
import talent_service
import platform_assets_service
import wa_takeover_service
import platform_inbox_service
import subscription_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

STATUS_FILTERS = ("READY_FOR_REVIEW", "NEEDS_REVISION", "APPROVED", "ACTIVE")


def get_display_status(business):
    """APPROVED-but-not-connected reads as a distinct pseudo-status in the UI (section 30).

    Ecosystem Sync Section 14: a business created WITHOUT AI Admin (package='NONE', Section 2)
    must NOT be shown/treated as part of the AI Admin status pipeline (NOT PURCHASED / PAYMENT
    PENDING / ONBOARDING / READY FOR REVIEW / APPROVED / WAITING WHATSAPP CONNECTION / WHATSAPP
    CONNECTED / ACTIVE / SUSPENDED) — it gets its own simple pseudo-status instead."""
    if business.get("package") == "NONE":
        return "ACTIVE_CUSTOMER_NO_AI_ADMIN"
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

    # Business Hub V2, Phase E / Final Operations Polish Section 8: a single "action center" so
    # normal day-to-day operation (new client onboarding review, quoting, payment verification,
    # talent requests, WhatsApp connection) never requires digging through separate pages to find
    # what's pending. Every count below is a real operational query, never a fabricated metric.
    all_projects = projects_repo.list_all_projects()
    projects_needing_action = [p for p in all_projects if p["status"] in ("REQUESTED", "WAITING_FOR_QUOTE", "PAID")]
    quotations_needing_action = [p for p in all_projects if p["status"] == "WAITING_FOR_QUOTE"]
    payments_needing_review = payment_service.list_payments_pending_review()
    talent_requests_waiting = [
        r for r in talent_service.list_all_talent_requests()
        if r["status"] == "WAITING_FOR_REVIEW"
    ]
    all_businesses = repo.list_all_businesses(status_filter=None)
    businesses_needing_review = [
        b for b in all_businesses if get_display_status(b) == "READY_FOR_REVIEW"
    ]
    new_client_requests = [
        b for b in all_businesses
        if b["status"] in ("DRAFT", "ONBOARDING") and b.get("package") != "NONE"
    ]
    whatsapp_waiting_connection = [
        b for b in all_businesses if get_display_status(b) == "APPROVED_WAITING_WHATSAPP_CONNECTION"
    ]

    action_center = {
        "new_client_requests": len(new_client_requests),
        "ai_onboarding_waiting_review": len(businesses_needing_review),
        "custom_projects_waiting_quote": len(quotations_needing_action),
        "quotations_needing_action": len(quotations_needing_action),
        "payments_waiting_verification": len(payments_needing_review),
        "talent_requests_waiting": len(talent_requests_waiting),
        "projects_waiting_admin_action": len(projects_needing_action),
        "whatsapp_tenants_waiting_connection": len(whatsapp_waiting_connection),
    }

    return render_template(
        "admin_dashboard.html",
        businesses=businesses,
        status_filter=status_filter,
        status_filters=STATUS_FILTERS,
        projects_needing_action=projects_needing_action,
        payments_needing_review=payments_needing_review,
        talent_requests_waiting=talent_requests_waiting,
        businesses_needing_review_count=len(businesses_needing_review),
        action_center=action_center,
    )


@admin_bp.route("/search")
@security.admin_required
def admin_search():
    """Final Operations Polish, Section 9: a simple global admin search across customer, business,
    project, quote, invoice, and talent records. Admin-only (route is behind @admin_required, same
    as every other route in this file) — no client ever reaches this."""
    query = (request.args.get("q") or "").strip()
    results = repo.admin_search(query) if query else None
    return render_template("admin_search.html", query=query, results=results)


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
    takeover_conversations = wa_takeover_service.list_takeover_conversations_for_business(business_id)
    subscription = subscription_service.get_subscription(business_id)
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
        takeover_conversations=takeover_conversations,
        subscription=subscription,
        is_admin_view=True,
    )


@admin_bp.route("/business/<int:business_id>/subscription/renew", methods=["POST"])
@security.admin_required
def renew_subscription(business_id):
    """Gap-fix Area E — admin marks a renewal payment verified and extends/reactivates the
    tenant's AI Admin subscription. Never touches creative-service projects, never re-runs
    onboarding, never re-provisions the tenant — see subscription_service.renew_subscription()'s
    docstring for the exact (minimal) side effects."""
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    admin = security.current_user()
    try:
        subscription_service.renew_subscription(business_id, admin["id"])
    except ValueError as e:
        flash(f"Belum bisa perpanjang: {e}. Subscription record belum ada untuk business ini.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    flash("Subscription AI Admin diperpanjang. Business aktif kembali (kalau sebelumnya SUSPENDED).", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


@admin_bp.route("/subscriptions/sweep", methods=["GET", "POST"])
def subscriptions_sweep():
    """Cron-secured lifecycle sweep trigger — same shape/secret convention as ../app.py's existing
    /cron/followups and /cron/owner-notifications endpoints. Intended to be called periodically
    (e.g. once a day) by an external scheduler (cron-job.org or similar), exactly like those two.
    Deliberately NOT behind @security.admin_required (a cron job has no logged-in admin session) —
    protected instead by a shared secret query param, matching the existing /cron/* pattern
    elsewhere in this codebase."""
    import os
    key = request.args.get("key", "")
    secret = os.environ.get("CLIENT_HUB_CRON_SECRET", "")
    if not secret or key != secret:
        return {"status": "error", "message": "Akses ditolak, key salah/kosong."}, 403
    result = subscription_service.run_lifecycle_sweep()
    return {"status": "ok", **result}, 200


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
    # Production bug fix (AI_RESPONSE_SHAPE_INVALID: missing keys ['features_enabled']):
    # features_enabled must reflect this tenant's REAL package entitlement, never the model's own
    # guess — see ai_onboarding._normalize_features_enabled() for why.
    tenant_features = repo.get_tenant_features(business_id)
    config, error = ai_onboarding.normalize_business_data(
        business, profile, services, faqs, extracted_texts, tenant_features=tenant_features,
    )

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
    """Section 30/section 3-of-19, hardened by the multi-tenant runtime safety cycle (Task A): the
    admin still types in the phone_number_id + trusted owner phone after doing the real Meta
    connection themselves, but this route no longer takes that input on faith. Before this tenant
    can be marked connected, provisioning.validate_and_connect_whatsapp() must confirm (a) this
    Phone Number ID isn't already claimed by a DIFFERENT tenant, and (b) — best-effort, see that
    function's docstring for exactly how failures are handled — a live Meta Graph API read against
    it succeeds. businesses.whatsapp_connected (the V1 activation gate) is ONLY ever set True on an
    actual "CONNECTED" verdict; a failed validation leaves it False and the tenant_whatsapp_config
    row VALIDATION_FAILED, so provisioning.activate_tenant() can never be reached for an
    unvalidated channel. The real access-token value is NEVER surfaced here — not in a flash
    message, not in a log line, not in the audit description (see validate_and_connect_whatsapp's
    own docstring)."""
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
    credentials_reference = (request.form.get("credentials_reference") or "").strip() or None
    if not phone_number_id or not trusted_owner_phone:
        flash("Isi WhatsApp Phone Number ID dan nomor owner terpercaya.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    # Task 8 (credential architecture) — LEFT BLANK on purpose means this tenant shares Kilas
    # Works' own default server-side WHATSAPP_ACCESS_TOKEN (the common case: this tenant's phone
    # number lives under the same Meta Business Portfolio/WABA Kilas Works already manages), so
    # onboarding a new client does NOT require adding a brand-new Render env var. Only fill this in
    # when the client genuinely has their OWN separate Meta app/token — see
    # app.py's _get_tenant_whatsapp_channel_safe docstring for the full design decision.

    try:
        result = provisioning.validate_and_connect_whatsapp(
            business_id, admin, phone_number_id, waba_id, credentials_reference
        )
    except provisioning.ProvisioningError as e:
        flash(f"Gagal menyimpan konfigurasi WhatsApp: {e}", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    if result["status"] != "CONNECTED":
        # Never touch businesses.whatsapp_connected/whatsapp_phone_number_id on a failed
        # validation — the V1 activation gate must stay exactly as it was before this attempt.
        flash(
            "Validasi WhatsApp GAGAL — Phone Number ID belum bisa dikonfirmasi "
            f"({result['reason']}). Business TIDAK ditandai Connected/Active.",
            "error",
        )
        return redirect(url_for("admin.review_business", business_id=business_id))

    # Only reached on an actual validated CONNECTED verdict. Kept for backward compatibility with
    # V1 (businesses.whatsapp_connected drives the existing activation gate and display_status
    # logic) — dual-written alongside tenant_whatsapp_config, the Phase 2 canonical home.
    db.execute(
        "UPDATE businesses SET whatsapp_phone_number_id = ?, trusted_owner_phone = ?, "
        "whatsapp_connected = ?, updated_at = ? WHERE id = ?",
        (phone_number_id, trusted_owner_phone, True, repo._now(), business_id),
    )
    flash("WhatsApp terhubung & tervalidasi. Business siap di-Activate.", "success")
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


@admin_bp.route("/catalog")
@security.admin_required
def catalog_admin():
    """Business rule change: catalog editing has been REMOVED from the Admin Dashboard — the
    official catalog is now managed as a manually-maintained document/file, uploaded/replaced
    outside this app. This route stays as a READ-ONLY status view only (name/category/price/
    active/last-updated) — see admin_catalog.html. The underlying service_catalog table, and
    every AI/Client Hub capability that reads it (live pricing sync, /services browsing, the
    "DAFTAR KATEGORI LAYANAN AKTIF" knowledge block, etc.), is completely unaffected — only the
    EDIT UI/route is gone (catalog_update() below has been removed accordingly)."""
    items = catalog_service.list_all_catalog()
    return render_template("admin_catalog.html", items=items, format_price=catalog_service.format_price)


@admin_bp.route("/catalog/regenerate", methods=["POST"])
@security.admin_required
def catalog_regenerate():
    """Absolute Final Production Patch, Section 10: manual 'force refresh' for the live public
    catalog PDF (/catalog.pdf). Normal edits above already auto-invalidate the cache (see
    catalog_service.update_catalog_item / talent_service._bump_catalog_cache) — this button exists
    purely so an admin can get instant confidence the PDF reflects a change right now, without
    waiting for the next natural request to trigger regeneration."""
    import live_catalog_pdf
    path = live_catalog_pdf.get_cached_catalog_pdf_path(force=True)
    if path:
        flash("Katalog live berhasil di-regenerate.", "success")
    else:
        flash("Gagal regenerate katalog live — cek log server.", "error")
    return redirect(url_for("admin.catalog_admin"))


@admin_bp.route("/projects")
@security.admin_required
def projects_admin():
    """Final Operations Polish, Section 13: status (already existed), plus project_type and
    business_id filters so the admin project list is actually useful once there are many
    projects across many businesses."""
    status_filter = request.args.get("status") or None
    type_filter = request.args.get("type") or None
    business_filter = request.args.get("business_id", type=int)
    projects = projects_repo.list_all_projects(
        status_filter=status_filter, project_type_filter=type_filter, business_id_filter=business_filter,
    )
    businesses_by_id = {b["id"]: b for b in repo.list_all_businesses()}
    for p in projects:
        b = businesses_by_id.get(p["business_id"])
        p["business_name"] = b["business_name"] if b else "?"
    return render_template(
        "admin_projects.html", projects=projects, status_filter=status_filter,
        type_filter=type_filter, business_filter=business_filter,
        statuses=projects_repo.PROJECT_STATUSES, project_types=projects_repo.PROJECT_TYPES,
        all_businesses=repo.list_all_businesses(),
    )


@admin_bp.route("/projects/<int:project_id>")
@security.admin_required
def project_admin_detail(project_id):
    project = projects_repo.get_project(project_id)
    if project is None:
        abort(404)
    business = repo.get_business(project["business_id"])
    quotations = quotation_service.list_quotations_for_business(project["business_id"])
    quotations = [q for q in quotations if q["project_id"] == project_id]
    audit_trail = repo.get_project_audit_log(project_id)
    attachments = db.query_all(
        "SELECT id, original_filename, mime_type, size_bytes, created_at FROM project_files "
        "WHERE project_id = ? AND kind = 'REFERENCE' ORDER BY created_at DESC",
        (project_id,),
    )
    return render_template("admin_project_detail.html", project=project, business=business,
                            quotations=quotations, format_price=catalog_service.format_price,
                            audit_trail=audit_trail, attachments=attachments)


@admin_bp.route("/projects/<int:project_id>/quote", methods=["POST"])
@security.admin_required
def project_create_quotation(project_id):
    admin = security.current_user()
    project = projects_repo.get_project(project_id)
    if project is None:
        abort(404)
    final_price = request.form.get("final_price", type=int)
    if not final_price or final_price <= 0:
        flash("Harga final harus diisi dan lebih dari 0.", "error")
        return redirect(url_for("admin.project_admin_detail", project_id=project_id))
    quotation_service.create_quotation(
        project_id, project["business_id"],
        scope=request.form.get("scope"), deliverables=request.form.get("deliverables"),
        quantity=request.form.get("quantity", type=int), final_price=final_price,
        notes=request.form.get("notes"), created_by_user_id=admin["id"],
    )
    flash("Quotation dibuat dan dikirim ke customer.", "success")
    return redirect(url_for("admin.project_admin_detail", project_id=project_id))


@admin_bp.route("/projects/<int:project_id>/status", methods=["POST"])
@security.admin_required
def project_update_status(project_id):
    admin = security.current_user()
    project = projects_repo.get_project(project_id)
    if project is None:
        abort(404)
    new_status = request.form.get("status")
    if new_status not in projects_repo.PROJECT_STATUSES:
        flash("Status tidak valid.", "error")
        return redirect(url_for("admin.project_admin_detail", project_id=project_id))
    projects_repo.set_project_status(project_id, new_status, admin["id"], project["business_id"],
                                      "admin manual status update")
    flash("Status project diperbarui.", "success")
    return redirect(url_for("admin.project_admin_detail", project_id=project_id))


@admin_bp.route("/payments")
@security.admin_required
def payments_admin():
    pending = payment_service.list_payments_pending_review()
    return render_template("admin_payments.html", payments=pending)


@admin_bp.route("/payments/<int:payment_id>")
@security.admin_required
def payment_detail(payment_id):
    """Bug fix: the PAYMENT_PROOF_UPLOADED owner notification (owner_notifications.py) has always
    linked to this exact URL (/admin/payments/<id>) for the owner to review one payment, but no
    route existed here at all — only the /admin/payments LIST page did, so that link 404'd. This is
    the minimal single-payment detail view the notification was always meant to point at: shows the
    one payment/invoice/customer/business clearly, the uploaded proof image (reusing the existing
    payment_proof_view route, not duplicating that logic), and the SAME verify/reject actions the
    list page already uses (same forms/routes, no new verification logic). Admin-only, like every
    other route in this file — a non-admin never reaches this."""
    payment = payment_service.get_payment(payment_id)
    if payment is None:
        abort(404)
    invoice = payment_service.get_invoice(payment["invoice_id"])
    business = repo.get_business(payment["business_id"])
    project = projects_repo.get_project(invoice["project_id"]) if invoice else None
    return render_template(
        "admin_payment_detail.html",
        payment=payment, invoice=invoice, business=business, project=project,
    )


@admin_bp.route("/payments/<int:payment_id>/verify", methods=["POST"])
@security.admin_required
def payment_verify(payment_id):
    admin = security.current_user()
    payment = payment_service.get_payment(payment_id)
    if payment is None:
        abort(404)
    try:
        payment_service.verify_payment(payment_id, payment["business_id"], admin["id"],
                                        admin_notes=request.form.get("admin_notes"))
    except ValueError as e:
        flash(f"Tidak bisa verifikasi: {e}", "error")
        return redirect(url_for("admin.payments_admin"))
    flash("Pembayaran diverifikasi.", "success")
    return redirect(url_for("admin.payments_admin"))


@admin_bp.route("/payments/<int:payment_id>/proof")
@security.admin_required
def payment_proof_view(payment_id):
    """Final Operations Polish, Section 11: admin can open the uploaded payment proof safely —
    streamed by id from project_files, never a raw storage path."""
    payment = payment_service.get_payment(payment_id)
    if payment is None or not payment.get("proof_file_id"):
        abort(404)
    row = db.query_one("SELECT * FROM project_files WHERE id = ?", (payment["proof_file_id"],))
    if row is None:
        abort(404)
    return send_file(io.BytesIO(row["content"]), mimetype=row["mime_type"] or "application/octet-stream")


@admin_bp.route("/payments/<int:payment_id>/reject", methods=["POST"])
@security.admin_required
def payment_reject(payment_id):
    admin = security.current_user()
    payment = payment_service.get_payment(payment_id)
    if payment is None:
        abort(404)
    try:
        payment_service.reject_payment(payment_id, payment["business_id"], admin["id"],
                                        admin_notes=request.form.get("admin_notes"))
    except ValueError as e:
        flash(f"Tidak bisa menolak: {e}", "error")
        return redirect(url_for("admin.payments_admin"))
    flash("Pembayaran ditolak.", "success")
    return redirect(url_for("admin.payments_admin"))


@admin_bp.route("/talent")
@security.admin_required
def talent_admin():
    talents = talent_service.list_all_talents()
    requests = talent_service.list_all_talent_requests()
    return render_template("admin_talent.html", talents=talents, requests=requests,
                            availability_statuses=talent_service.AVAILABILITY_STATUSES)


@admin_bp.route("/talent/create", methods=["POST"])
@security.admin_required
def talent_create():
    """Final Operations Polish, Section 1: KILAS_ADMIN can add unlimited new talents from the app
    — no coding/deploy required. Only `name` is required; everything else can be filled in later
    via the normal edit form."""
    admin = security.current_user()
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Nama talent wajib diisi.", "error")
        return redirect(url_for("admin.talent_admin"))
    talent_service.create_talent(
        name=name,
        social_handle=request.form.get("social_handle"),
        niche=request.form.get("niche"),
        follower_count=request.form.get("follower_count", type=int),
        availability_status=request.form.get("availability_status") or "AVAILABLE",
        availability_note=request.form.get("availability_note"),
        internal_rate=request.form.get("internal_rate", type=int) or None,
        profile_photo_url=request.form.get("profile_photo_url"),
        created_by_user_id=admin["id"],
    )
    flash(f"Talent '{name}' ditambahkan.", "success")
    return redirect(url_for("admin.talent_admin"))


@admin_bp.route("/talent/<int:talent_id>/update", methods=["POST"])
@security.admin_required
def talent_update(talent_id):
    updated = talent_service.update_talent(
        talent_id,
        social_handle=(request.form.get("social_handle") or "").strip() or None,
        niche=(request.form.get("niche") or "").strip() or None,
        profile_photo_url=(request.form.get("profile_photo_url") or "").strip() or None,
        follower_count=request.form.get("follower_count", type=int),
        availability_status=request.form.get("availability_status"),
        availability_note=(request.form.get("availability_note") or "").strip() or None,
        display_order=request.form.get("display_order", type=int) or 0,
        is_active=request.form.get("is_active") == "on",
        public_notes=request.form.get("public_notes"),
        internal_notes=request.form.get("internal_notes"),
        internal_rate=request.form.get("internal_rate", type=int) or None,
    )
    if updated is None:
        abort(404)
    flash(f"{updated['name']} diperbarui.", "success")
    return redirect(url_for("admin.talent_admin"))


@admin_bp.route("/talent/<int:talent_id>/photo", methods=["POST"])
@security.admin_required
def talent_photo_upload(talent_id):
    """Final Operations Polish, Section 2: direct upload replaces pasted-URL as the normal
    workflow. Stored in platform_assets (see that module's docstring for why not project_files),
    validated the same defense-in-depth way as every other upload in this app (extension
    allow-list, size cap, real-image-bytes check via Pillow, sanitized filename — no path
    traversal, no raw filesystem path ever exposed)."""
    admin = security.current_user()
    talent = talent_service.get_talent(talent_id)
    if talent is None:
        abort(404)
    upload = request.files.get("photo")
    if not upload or not upload.filename:
        flash("Pilih file foto dulu.", "error")
        return redirect(url_for("admin.talent_admin"))
    content = upload.read()
    try:
        safe_name, mime_type = file_utils.validate_image_upload(upload.filename, content)
    except file_utils.UploadRejected as e:
        flash(str(e), "error")
        return redirect(url_for("admin.talent_admin"))

    old_asset_id = talent.get("profile_image_asset_id")
    asset_id = platform_assets_service.save_asset(
        "TALENT_PHOTO", safe_name, mime_type, len(content), content, admin["id"],
    )
    talent_service.update_talent(talent_id, profile_image_asset_id=asset_id)
    # The old asset row (if any) is deliberately left in place rather than deleted — cheap, and
    # avoids ever deleting a blob a concurrent request might still be streaming out.
    repo.write_audit(admin["id"], None, "TALENT_PHOTO_UPLOADED",
                      f"talent_id={talent_id} asset_id={asset_id} replaced={old_asset_id}")
    flash(f"Foto {talent['name']} diperbarui.", "success")
    return redirect(url_for("admin.talent_admin"))


@admin_bp.route("/assets/<int:asset_id>")
@security.login_required
def platform_asset_view(asset_id):
    """Serves a platform_assets image by id — never a raw filesystem path. login_required (not
    admin_required) because this is what <img src> tags on the customer-facing talent list also
    point at; platform_assets currently only ever holds TALENT_PHOTO kind, which is meant to be
    visible to any logged-in customer, so there is no tenant data to leak here."""
    asset = platform_assets_service.get_asset(asset_id)
    if asset is None:
        abort(404)
    return send_file(
        io.BytesIO(asset["content"]), mimetype=asset["mime_type"] or "application/octet-stream",
    )


@admin_bp.route("/talent/<int:talent_id>/archive", methods=["POST"])
@security.admin_required
def talent_archive(talent_id):
    """Section 1: soft delete only — NEVER hard-deletes a talent, so historical talent_requests /
    projects referencing this talent stay intact. The talent just stops showing up publicly."""
    admin = security.current_user()
    updated = talent_service.archive_talent(talent_id, actor_user_id=admin["id"])
    if updated is None:
        abort(404)
    flash(f"{updated['name']} diarsipkan (tidak tampil ke customer lagi).", "success")
    return redirect(url_for("admin.talent_admin"))


@admin_bp.route("/talent/<int:talent_id>/reactivate", methods=["POST"])
@security.admin_required
def talent_reactivate(talent_id):
    admin = security.current_user()
    updated = talent_service.reactivate_talent(talent_id, actor_user_id=admin["id"])
    if updated is None:
        abort(404)
    flash(f"{updated['name']} diaktifkan kembali.", "success")
    return redirect(url_for("admin.talent_admin"))


@admin_bp.route("/business/<int:business_id>/takeover", methods=["POST"])
@security.admin_required
def wa_takeover_toggle(business_id):
    admin = security.current_user()
    customer_phone = (request.form.get("customer_phone") or "").strip()
    action = request.form.get("action")
    if not customer_phone or action not in ("start", "return"):
        flash("Data takeover tidak lengkap.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    if action == "start":
        wa_takeover_service.start_human_takeover(business_id, customer_phone, admin["id"])
        flash(f"Human takeover aktif untuk {customer_phone}.", "success")
    else:
        wa_takeover_service.return_to_ai(business_id, customer_phone, admin["id"])
        flash(f"AI diaktifkan kembali untuk {customer_phone}.", "success")
    return redirect(url_for("admin.review_business", business_id=business_id))


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


# ---------------------------------------------------------------------------
# Kilas Works own WhatsApp Inbox — one professional web, database stays invisible.
# ---------------------------------------------------------------------------

@admin_bp.route("/inbox")
@security.admin_required
def platform_inbox():
    search = (request.args.get("q") or "").strip()
    mode_filter = (request.args.get("mode") or "").strip()
    if mode_filter not in ("", "AI_ACTIVE", "HUMAN_TAKEOVER"):
        mode_filter = ""
    conversations = platform_inbox_service.list_conversations(
        search=search,
        mode_filter=mode_filter or None,
    )
    selected_phone = platform_inbox_service.normalize_customer_phone(request.args.get("customer"))
    if not selected_phone and conversations:
        selected_phone = conversations[0]["customer_phone"]

    selected = None
    thread = []
    window = None
    if selected_phone:
        if not platform_inbox_service.customer_exists(selected_phone):
            abort(404)
        try:
            mode = platform_inbox_service.get_state(selected_phone)
        except Exception:
            mode = "STATE_UNAVAILABLE"
        selected = {
            "customer_phone": selected_phone,
            "customer_name": platform_inbox_service.get_customer_name(selected_phone),
            "mode": mode,
        }
        thread = platform_inbox_service.get_thread(selected_phone)
        window = platform_inbox_service.freeform_window_status(selected_phone)

    return render_template(
        "platform_inbox.html",
        conversations=conversations,
        selected=selected,
        thread=thread,
        window=window,
        search=search,
        mode_filter=mode_filter,
    )


@admin_bp.route("/inbox/takeover", methods=["POST"])
@security.admin_required
def platform_inbox_takeover():
    phone = platform_inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not platform_inbox_service.customer_exists(phone):
        abort(404)
    admin = security.current_user()
    platform_inbox_service.start_human_takeover(phone, admin["id"])
    repo.write_audit_no_business(admin["id"], "PLATFORM_HUMAN_TAKEOVER_STARTED", f"customer={phone}")
    flash("Lu ambil alih chat ini. AI Kilas Works akan diam khusus customer tersebut.", "success")
    return redirect(url_for("admin.platform_inbox", customer=phone))


@admin_bp.route("/inbox/return-ai", methods=["POST"])
@security.admin_required
def platform_inbox_return_ai():
    phone = platform_inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not platform_inbox_service.customer_exists(phone):
        abort(404)
    admin = security.current_user()
    platform_inbox_service.return_to_ai(phone, admin["id"])
    repo.write_audit_no_business(admin["id"], "PLATFORM_HUMAN_TAKEOVER_ENDED", f"customer={phone}")
    flash("Chat dikembalikan ke AI Kilas Works.", "success")
    return redirect(url_for("admin.platform_inbox", customer=phone))


@admin_bp.route("/inbox/reply", methods=["POST"])
@security.admin_required
def platform_inbox_reply():
    phone = platform_inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    text = (request.form.get("message") or "").strip()
    if not phone or not platform_inbox_service.customer_exists(phone):
        abort(404)
    if not text:
        flash("Pesan tidak boleh kosong.", "error")
        return redirect(url_for("admin.platform_inbox", customer=phone))

    ok, reason = platform_inbox_service.send_manual_reply(phone, text)
    admin = security.current_user()
    if ok:
        repo.write_audit_no_business(admin["id"], "PLATFORM_CS_MANUAL_REPLY_SENT", f"customer={phone}")
        if reason == "sent_history_write_failed":
            flash("Pesan terkirim, tapi history lokal gagal tersimpan. Cek log.", "success")
        else:
            flash("Pesan Kilas Works terkirim.", "success")
    else:
        friendly = {
            "human_takeover_required": "Klik Ambil Alih dulu sebelum balas manual.",
            "outside_24h_window": "Sudah di luar window WhatsApp 24 jam. Free-text tidak dikirim; perlu template message.",
            "no_customer_inbound": "Belum ada inbound customer yang membuka window WhatsApp 24 jam.",
            "takeover_state_unavailable": "Status takeover tidak bisa diverifikasi. Demi keamanan pesan tidak dikirim.",
            "bot_internal_bridge_unavailable": "Koneksi internal Client Hub → bot belum dikonfigurasi.",
            "bot_internal_bridge_network_error": "Bot WhatsApp sedang tidak terjangkau dari Client Hub. Coba lagi sebentar.",
            "bot_internal_bridge_timeout": "Bot WhatsApp terlalu lama merespons (kemungkinan cold start Render). Coba sekali lagi setelah bot sudah Live.",
            "message_too_long": "Pesan terlalu panjang. Maksimal 4096 karakter.",
        }.get(reason)

        if not friendly and str(reason).startswith("bot_internal_bridge_http_"):
            # Safe operational diagnostic only; never exposes tokens/secrets/message bodies.
            detail = str(reason).replace("bot_internal_bridge_http_", "HTTP ", 1)
            friendly = f"Bridge Client Hub → bot menolak request ({detail}). Kirim kode ini ke admin untuk diagnosis."
        if not friendly:
            friendly = f"Pesan belum berhasil dikirim. Diagnostic: {reason}"
        flash(friendly, "error")
    return redirect(url_for("admin.platform_inbox", customer=phone))
