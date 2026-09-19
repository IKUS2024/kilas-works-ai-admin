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
import inbox_media_service

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file

import ai_onboarding
import db
import repo
import security
import file_utils
import provisioning
import catalog_cache
import catalog_service
import pricing_config
import display_labels
import projects_repo
import quotation_service
import payment_service
import talent_service
import platform_assets_service
import wa_takeover_service
import platform_inbox_service
import subscription_service
import finance_entitlements

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
    finance_trials_only = request.args.get("finance") == "trial"
    brain_review_only = request.args.get("brain_review") == "changes"
    status_filter = None if (finance_trials_only or brain_review_only) else request.args.get("status") or None
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
    all_talent_requests = talent_service.list_all_talent_requests()
    talent_requests_waiting = [
        r for r in all_talent_requests if r["status"] == "WAITING_FOR_REVIEW"
    ]
    talent_request_by_project = {
        r["project_id"]: r for r in all_talent_requests if r.get("project_id")
    }
    talent_review_project_ids = {
        r["project_id"] for r in talent_requests_waiting if r.get("project_id")
    }
    # App-created REQUESTED rows are customer drafts until the brief is confirmed. They must
    # not look like admin work. Specific-talent requests use the Talent queue first so the same
    # request is not counted twice in both Talent and Projects.
    projects_needing_action = [
        p for p in projects_repo.list_projects_needing_action()
        if p["id"] not in talent_review_project_ids
        and not (p.get("catalog_key") == "talent_management" and p["id"] not in talent_request_by_project)
    ]
    quotations_needing_action = [
        p for p in all_projects
        if p["status"] == "WAITING_FOR_QUOTE" and p["id"] not in talent_review_project_ids
    ]
    payments_needing_review = payment_service.list_payments_pending_review()
    all_businesses = repo.list_all_businesses(status_filter=None)
    businesses_by_id = {b["id"]: b for b in all_businesses}
    recent_service_orders = []
    for project in all_projects:
        if project.get("catalog_key") in ("ai_admin", "ai_admin_basic", "ai_admin_pro"):
            continue
        if project.get("catalog_key") == "talent_management" and project["id"] not in talent_request_by_project:
            continue
        if project.get("status") == "CANCELLED" or projects_repo.is_unsubmitted_app_draft(project):
            continue
        item = dict(project)
        business = businesses_by_id.get(item.get("business_id"))
        item["business_name"] = business["business_name"] if business else "Pesanan pribadi"
        talent_request = talent_request_by_project.get(item["id"])
        item["talent_request_id"] = talent_request["id"] if talent_request else None
        recent_service_orders.append(item)
        if len(recent_service_orders) >= 3:
            break
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
    brain_changes_waiting = [
        b for b in all_businesses
        if b.get("package") != "NONE"
        and b.get("status") in ("APPROVED", "ACTIVE")
        and (repo.get_ai_settings(b["id"]) or {}).get("ai_status") == "STALE"
    ]
    brain_changes_waiting_ids = {b["id"] for b in brain_changes_waiting}

    # Use the same current entitlement calculation as Finance (paid takes precedence;
    # expired trials are never counted). Viewing this list does not activate trials.
    finance_trials = []
    finance_entitlements_by_id = {}
    for business in all_businesses:
        entitlement = finance_entitlements.state(business["id"])
        finance_entitlements_by_id[business["id"]] = entitlement
        if entitlement["status"] == "TRIAL_ACTIVE":
            finance_trials.append({**business, "finance_entitlement": entitlement,
                                   "display_status": get_display_status(business)})
    if brain_review_only:
        businesses = [
            {
                **business,
                "display_status": get_display_status(business),
                "finance_entitlement": finance_entitlements_by_id.get(
                    business["id"], {"status": "NOT_ACTIVATED", "active": False}
                ),
                "brain_review_pending": True,
            }
            for business in brain_changes_waiting
        ]
    elif not finance_trials_only:
        for business in businesses:
            business["finance_entitlement"] = finance_entitlements_by_id.get(
                business["id"], {"status": "NOT_ACTIVATED", "active": False}
            )
            business["brain_review_pending"] = business["id"] in brain_changes_waiting_ids
    finance_bills_review = db.query_one(
        "SELECT COUNT(*) AS n FROM finance_subscription_bills WHERE status='REVIEW'"
    )["n"]
    if finance_trials_only:
        businesses = finance_trials
        for business in businesses:
            business["brain_review_pending"] = business["id"] in brain_changes_waiting_ids

    # Keep the owner dashboard short on mobile. Pagination is UI-only; filters and counts still
    # operate on the complete matching client set.
    businesses_total = len(businesses)
    client_per_page = 5
    client_total_pages = max(1, (businesses_total + client_per_page - 1) // client_per_page)
    client_page = request.args.get("client_page", 1, type=int) or 1
    client_page = min(max(1, client_page), client_total_pages)
    client_start = (client_page - 1) * client_per_page
    businesses = businesses[client_start:client_start + client_per_page]

    action_center = {
        "finance_trials_active": len(finance_trials),
        "finance_bills_waiting_review": finance_bills_review,
        "new_client_requests": len(new_client_requests),
        "ai_onboarding_waiting_review": len(businesses_needing_review),
        "brain_changes_waiting_review": len(brain_changes_waiting),
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
        recent_service_orders=recent_service_orders,
        finance_trials_only=finance_trials_only,
        brain_review_only=brain_review_only,
        businesses_total=businesses_total,
        client_page=client_page,
        client_total_pages=client_total_pages,
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
    # Audit Log pagination (Section T: "do not dump an endless table") — ?audit_page=N in the URL,
    # 20 per page, newest first (unchanged ordering) — never deletes/hides rows from the database,
    # only how many render on one page load.
    audit_page = request.args.get("audit_page", 1, type=int)
    audit_page = max(1, audit_page)
    audit_log = repo.get_audit_log(business_id, limit=20, offset=(audit_page - 1) * 20)
    audit_log_total = repo.count_audit_log(business_id)
    audit_log_has_more = audit_page * 20 < audit_log_total
    flagged = repo.list_flagged_simulation_messages(business_id)
    whatsapp_config = repo.get_whatsapp_config(business_id)
    tenant_config_row = repo.get_tenant_config_row(business_id)
    business["display_status"] = get_display_status(business)
    takeover_conversations = wa_takeover_service.list_takeover_conversations_for_business(business_id)
    subscription = subscription_service.get_subscription(business_id)
    try:
        finance_state = finance_entitlements.state(business_id)
    except Exception:
        finance_state = {
            "status": "UNAVAILABLE", "active": False, "trial_used": False,
            "until": None, "until_local": None,
        }
    service_projects = [
        p for p in projects_repo.list_projects_for_business(business_id)
        if p.get("catalog_key") not in ("ai_admin", "ai_admin_basic", "ai_admin_pro")
    ]
    business_talent_requests = {
        r["project_id"]: r for r in talent_service.list_talent_requests_for_business(business_id)
        if r.get("project_id")
    }
    service_projects = [
        p for p in service_projects
        if not (p.get("catalog_key") == "talent_management" and p["id"] not in business_talent_requests)
    ]
    for project in service_projects:
        project["is_customer_draft"] = projects_repo.is_unsubmitted_app_draft(project)
        talent_request = business_talent_requests.get(project["id"])
        project["talent_request_id"] = talent_request["id"] if talent_request else None
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
        missing_required_labels=display_labels.humanize_missing_fields(missing_required),
        missing_required_sentence=display_labels.missing_fields_sentence(missing_required),
        audit_log=audit_log,
        audit_page=audit_page,
        audit_log_has_more=audit_log_has_more,
        flagged=flagged,
        whatsapp_config=whatsapp_config,
        tenant_config_row=tenant_config_row,
        takeover_conversations=takeover_conversations,
        subscription=subscription,
        finance_state=finance_state,
        service_projects=service_projects,
        activation_checklist=payment_service.build_activation_checklist(business_id),
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


def _normalize_brain_draft_for_review(business_id, actor_user_id):
    """Normalize the current customer draft without changing business lifecycle status.

    This is used for re-approval of an already APPROVED/ACTIVE Brain. The old tenant_configs
    snapshot remains live until provisioning succeeds, so a bad AI run cannot replace the last
    approved WhatsApp knowledge.
    """
    business = repo.get_business(business_id)
    if not business:
        return False, "business_not_found"
    profile = repo.get_business_profile(business_id) or {}
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)
    files = repo.list_business_files(business_id)
    extracted_texts = [
        (row["original_filename"], row["extracted_text"])
        for row in files if row.get("extracted_text")
    ]

    repo.set_ai_status(business_id, "RUNNING")
    config, error = ai_onboarding.normalize_business_data(
        business,
        profile,
        [row["raw_input"] for row in services],
        [row["raw_input"] for row in faqs],
        extracted_texts,
        tenant_features=repo.get_tenant_features(business_id),
    )
    if error:
        if business["status"] in ("APPROVED", "ACTIVE"):
            repo.set_ai_status(business_id, "STALE", error=error)
        else:
            repo.set_ai_status(business_id, "FAILED", error=error)
        repo.write_audit(actor_user_id, business_id, "ai_normalization_failed",
                         "Brain draft re-approval normalization failed")
        return False, error

    for row, normalized in zip(services, config.get("services", [])):
        repo.update_normalized_service(
            row["id"], normalized.get("service_name"), normalized.get("description"),
            normalized.get("price_from"), normalized.get("price_to"),
            normalized.get("currency") or "IDR", normalized.get("needs_review", True),
        )
    for row, normalized in zip(faqs, config.get("faqs", [])):
        repo.update_normalized_faq(
            row["id"], normalized.get("question"), normalized.get("answer"),
            normalized.get("category") or "general", normalized.get("needs_review", True),
        )
    repo.save_ai_normalized_config(
        business_id, config.get("description", ""), config, config.get("missing_fields", [])
    )
    repo.write_audit(actor_user_id, business_id, "ai_normalization_run",
                     "Brain draft normalized for admin re-approval")
    return True, None


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
    if ai_settings and ai_settings.get("ai_status") == "STALE":
        ok, _ = _normalize_brain_draft_for_review(business_id, admin["id"])
        if not ok:
            flash("Belum bisa approve — draft Brain gagal diproses. Versi sebelumnya tetap aman.", "error")
            return redirect(url_for("admin.review_business", business_id=business_id))
        ai_settings = repo.get_ai_settings(business_id)
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


@admin_bp.route("/business/<int:business_id>/approve-brain-changes", methods=["POST"])
@security.admin_required
def approve_brain_changes(business_id):
    """Approve a customer-edited Brain draft without taking an approved/live tenant offline."""
    business = repo.get_business(business_id)
    if not business:
        abort(404)
    if business.get("package") == "NONE":
        abort(404)
    if business["status"] not in ("APPROVED", "ACTIVE"):
        flash("Perubahan Brain memakai alur approve awal untuk status bisnis ini.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    admin = security.current_user()
    ai_settings = repo.get_ai_settings(business_id) or {}
    if ai_settings.get("ai_status") != "STALE":
        flash("Tidak ada perubahan Brain yang menunggu persetujuan.", "info")
        return redirect(url_for("admin.review_business", business_id=business_id))

    missing = repo.required_fields_missing(business_id)
    if missing:
        flash("Belum bisa menyetujui perubahan — data wajib masih belum lengkap.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    ok, _ = _normalize_brain_draft_for_review(business_id, admin["id"])
    if not ok:
        flash("Perubahan belum bisa disetujui karena pemrosesan Brain gagal. Versi live lama tetap berjalan.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    try:
        result = provisioning.provision_tenant(business_id, admin)
    except provisioning.ProvisioningError:
        # Keep the last approved tenant config untouched if validation/provisioning fails.
        repo.set_ai_status(business_id, "STALE")
        flash("Perubahan belum bisa dipromosikan ke versi live. Versi live lama tetap berjalan.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))

    repo.write_audit(
        admin["id"], business_id, "BRAIN_CHANGES_APPROVED",
        f"config_version={result['config_version']}"
    )
    if business["status"] == "ACTIVE":
        flash("Perubahan Brain disetujui. Versi baru sekarang live; WhatsApp tetap aktif selama proses.", "success")
    else:
        flash("Perubahan Brain disetujui dan konfigurasi client sudah diperbarui.", "success")
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
    # Owner/pengelola phone (Section J: "Do NOT create a second duplicate owner-phone data
    # source") — same normalize_owner_phone() the customer-facing wizard entry point uses, so
    # "0851...", "+62851...", "62851..." always converge on the SAME stored value regardless of
    # which of the two entry points (customer wizard vs admin WhatsApp-connect) was used.
    trusted_owner_phone = repo.normalize_owner_phone(request.form.get("trusted_owner_phone")) or ""
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
    try:
        repo.set_business_package(business_id, package, actor_user_id=admin["id"])
    except ValueError:
        flash("Perubahan paket belum diizinkan. Perubahan entitlement memerlukan pembayaran paket tujuan yang sudah diverifikasi.", "error")
        return redirect(url_for("admin.review_business", business_id=business_id))
    flash("Paket Kilas Brain berhasil diperbarui.", "success")
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


@admin_bp.route("/settings/official-links", methods=["GET", "POST"])
@security.admin_required
def official_links_admin():
    """Unified AI Brain v2, Section 1 — admin-editable source of truth for Kilas Works' own
    official links, consumed by the production SYSTEM_PROMPT (see app.py's
    _build_official_links_note_safe()) instead of being hardcoded/duplicated inside the prompt
    string. Reuses repo.get_official_links()/set_platform_setting() — the SAME functions any
    future admin surface for this should call, never a second config path."""
    if request.method == "POST":
        for key in ("landing_page", "app", "instagram", "demo", "catalog"):
            value = (request.form.get(key) or "").strip()
            if value:
                repo.set_platform_setting(f"official_link_{key}", value)
        catalog_cache.bump_version()
        flash("Link resmi diperbarui.", "success")
        return redirect(url_for("admin.official_links_admin"))
    return render_template("admin_official_links.html", links=repo.get_official_links())



@admin_bp.route("/catalog")
@security.admin_required
def catalog_admin():
    """Admin service catalog with search + bounded pages for mobile usability."""
    archived = request.args.get("view") == "archive"
    search = (request.args.get("q") or "").strip()
    needle = search.casefold()
    items = [item for item in catalog_service.list_all_catalog() if bool(item["is_active"]) != archived]
    if needle:
        items = [
            item for item in items
            if needle in str(item.get("name") or "").casefold()
            or needle in str(item.get("category") or "").casefold()
            or needle in str(item.get("pricing_mode") or "").casefold()
            or needle in str(item.get("description") or "").casefold()
            or needle in str(item.get("price_unit") or "").casefold()
        ]

    items_total = len(items)
    per_page = 10
    total_pages = max(1, (items_total + per_page - 1) // per_page)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    items = items[start:start + per_page]

    return render_template(
        "admin_catalog.html",
        items=items,
        items_total=items_total,
        page=page,
        total_pages=total_pages,
        search=search,
        archived=archived,
        format_price=catalog_service.format_price,
        safe_categories=catalog_service.SAFE_NEW_ITEM_CATEGORIES,
        pricing_modes=pricing_config.VALID_PRICING_MODES,
    )

@admin_bp.route("/catalog/create", methods=["POST"])
@security.admin_required
def catalog_create():
    name = (request.form.get("name") or "").strip()
    category = (request.form.get("category") or "").strip()
    pricing_mode = (request.form.get("pricing_mode") or "").strip()
    price_amount = request.form.get("price_amount", type=int)
    price_unit = (request.form.get("price_unit") or "").strip() or None
    description = (request.form.get("description") or "").strip() or None
    if not name or not category or not pricing_mode:
        flash("Isi nama, kategori, dan jenis harga dulu.", "error")
        return redirect(url_for("admin.catalog_admin"))
    try:
        catalog_service.create_catalog_item(
            category, name, pricing_mode, price_amount=price_amount, price_unit=price_unit,
            description=description,
        )
    except catalog_service.InvalidCatalogState as e:
        flash(f"Tidak bisa disimpan: {e}", "error")
        return redirect(url_for("admin.catalog_admin"))
    flash(f"{name} ditambahkan ke katalog.", "success")
    return redirect(url_for("admin.catalog_admin"))


@admin_bp.route("/catalog/<int:catalog_id>/update", methods=["POST"])
@security.admin_required
def catalog_update(catalog_id):
    price_amount = request.form.get("price_amount", type=int)
    price_unit = (request.form.get("price_unit") or "").strip() or None
    is_active = request.form.get("is_active") == "on"
    name = (request.form.get("name") or "").strip() or None
    description = request.form.get("description")
    cta_text = (request.form.get("cta_text") or "").strip() or None
    sort_order = request.form.get("sort_order", type=int)
    pricing_mode = request.form.get("pricing_mode") or None
    try:
        updated = catalog_service.update_catalog_item(
            catalog_id, price_amount=price_amount, price_unit=price_unit, is_active=is_active,
            description=description, name=name, cta_text=cta_text, sort_order=sort_order,
            pricing_mode=pricing_mode,
        )
    except catalog_service.InvalidCatalogState as e:
        flash(f"Tidak bisa disimpan: {e}", "error")
        return redirect(url_for("admin.catalog_admin"))
    if updated is None:
        abort(404)
    flash(f"{updated['name']} diperbarui.", "success")
    return redirect(url_for("admin.catalog_admin"))


@admin_bp.route("/catalog/<int:catalog_id>/toggle-active", methods=["POST"])
@security.admin_required
def catalog_toggle_active(catalog_id):
    """Aktifkan/Nonaktifkan (Section G/H). Deactivating ONLY flips service_catalog.is_active —
    list_active_catalog() (the SAME function /services, project creation, and the bot's live
    knowledge block all call) immediately stops returning it everywhere at once, with no separate
    sync step. Never touches any existing projects/invoices/quotations row — those reference the
    catalog by catalog_key at the time they were created, not a live join, so historical orders
    are structurally unreachable from this action and remain exactly as they were."""
    item = catalog_service.get_catalog_item_by_id(catalog_id)
    if item is None:
        abort(404)
    if item['category'] == 'BUNDLE' and not item['is_active']:
        flash('Bundle tidak ditawarkan lagi; layanan dibeli terpisah.', 'error')
        return redirect(url_for('admin.catalog_admin', view='archive'))
    catalog_service.update_catalog_item(catalog_id, is_active=not item["is_active"])
    flash(f"{item['name']} {'diaktifkan' if not item['is_active'] else 'dinonaktifkan'}.", "success")
    return redirect(url_for("admin.catalog_admin"))


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
    """Admin projects: existing filters plus search and 10-row pagination."""
    status_filter = request.args.get("status") or None
    type_filter = request.args.get("type") or None
    business_filter = request.args.get("business_id", type=int)
    search = (request.args.get("q") or "").strip()
    needle = search.casefold()

    projects = projects_repo.list_all_projects(
        status_filter=status_filter, project_type_filter=type_filter, business_id_filter=business_filter,
    )
    all_businesses = repo.list_all_businesses()
    businesses_by_id = {b["id"]: b for b in all_businesses}
    linked_talent_projects = {
        r["project_id"] for r in talent_service.list_all_talent_requests() if r.get("project_id")
    }
    for p in projects:
        b = businesses_by_id.get(p["business_id"])
        p["business_name"] = b["business_name"] if b else "Pesanan pribadi"
        p["is_customer_draft"] = projects_repo.is_unsubmitted_app_draft(p)
        p["legacy_talent_flow"] = p.get("catalog_key") == "talent_management" and p["id"] not in linked_talent_projects

    if needle:
        projects = [
            p for p in projects
            if needle in str(p.get("title") or "").casefold()
            or needle in str(p.get("business_name") or "").casefold()
            or needle in str(p.get("project_type") or "").casefold()
            or needle in str(p.get("status") or "").casefold()
            or needle in str(p.get("id") or "").casefold()
        ]

    projects_total = len(projects)
    per_page = 10
    total_pages = max(1, (projects_total + per_page - 1) // per_page)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    projects = projects[start:start + per_page]

    return render_template(
        "admin_projects.html",
        projects=projects,
        projects_total=projects_total,
        page=page,
        total_pages=total_pages,
        search=search,
        status_filter=status_filter,
        type_filter=type_filter,
        business_filter=business_filter,
        statuses=projects_repo.PROJECT_STATUSES,
        project_types=projects_repo.PROJECT_TYPES,
        all_businesses=all_businesses,
    )

@admin_bp.route("/projects/<int:project_id>")
@security.admin_required
def project_admin_detail(project_id):
    project = projects_repo.get_project(project_id)
    if project is None:
        abort(404)
    talent_request = db.query_one("SELECT id FROM talent_requests WHERE project_id=?", (project_id,))
    if talent_request:
        return redirect(url_for("admin.talent_request_detail", request_id=talent_request["id"]))
    business = repo.get_business(project["business_id"])
    quotations = db.query_all("SELECT * FROM quotations WHERE project_id=? ORDER BY id DESC",(project_id,))
    audit_trail = repo.get_project_audit_log(project_id)
    attachments = db.query_all(
        "SELECT id, original_filename, mime_type, size_bytes, created_at FROM project_files "
        "WHERE project_id = ? AND kind = 'REFERENCE' ORDER BY created_at DESC",
        (project_id,),
    )
    import wa_checkout
    wa_order = wa_checkout.session_for_project(project_id)
    wa_link = wa_checkout.link(wa_order) if wa_order and wa_order["expires_at"] > __import__("time").time() else None
    return render_template("admin_project_detail.html", project=project, business=business,
                            wa_order=wa_order, wa_link=wa_link, wa_labels=wa_checkout.FIELDS, app_brief=(project.get('requirements') or {}).get('_app_brief') == 1,
                            wa_missing=wa_checkout.missing(catalog_service.get_catalog_item(wa_order["catalog_key"]), project.get("requirements") or {}) if wa_order else [],
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
    import wa_checkout
    try:
        wa_checkout.admin_quote(
            project_id, project["business_id"],
            scope=request.form.get("scope"), deliverables=request.form.get("deliverables"),
            quantity=request.form.get("quantity", type=int), final_price=final_price,
            notes=request.form.get("notes"), created_by_user_id=admin["id"],
        )
    except ValueError:
        flash("Brief belum dikonfirmasi atau status penawaran telah berubah. Muat ulang project.", "error")
        return redirect(url_for("admin.project_admin_detail", project_id=project_id))
    flash("Penawaran tersedia. Untuk order WhatsApp, kirim tautan order pribadi dari halaman project.", "success")
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
    search = (request.args.get("q") or "").strip()
    needle = search.casefold()

    businesses_by_id = {b["id"]: b for b in repo.list_all_businesses()}
    for p in pending:
        p["review_status"] = payment_service.derive_review_status(p)
        business = businesses_by_id.get(p.get("business_id"))
        p["business_name"] = business["business_name"] if business else "Pesanan pribadi"
        invoice = payment_service.get_invoice(p.get("invoice_id")) if p.get("invoice_id") else None
        p["invoice_number"] = invoice.get("invoice_number") if invoice else None
        project = projects_repo.get_project(invoice.get("project_id")) if invoice and invoice.get("project_id") else None
        p["project_title"] = project.get("title") if project else None

    if needle:
        pending = [
            p for p in pending
            if needle in str(p.get("id") or "").casefold()
            or needle in str(p.get("business_name") or "").casefold()
            or needle in str(p.get("invoice_number") or "").casefold()
            or needle in str(p.get("project_title") or "").casefold()
            or needle in str(p.get("review_status") or "").casefold()
            or needle in str(p.get("ai_extracted_bank") or "").casefold()
            or needle in str(p.get("ai_reference") or "").casefold()
            or needle in str(p.get("ai_extracted_amount") or "").casefold()
        ]

    payments_total = len(pending)
    per_page = 10
    total_pages = max(1, (payments_total + per_page - 1) // per_page)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    pending = pending[start:start + per_page]

    return render_template(
        "admin_payments.html",
        payments=pending,
        payments_total=payments_total,
        page=page,
        total_pages=total_pages,
        search=search,
    )

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
        review_status=payment_service.derive_review_status(payment),
        difference=(payment.get("ai_extracted_amount") - invoice["amount"]
                    if payment.get("ai_extracted_amount") is not None and invoice else None),
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


@admin_bp.route("/payments/<int:payment_id>/request-reupload", methods=["POST"])
@security.admin_required
def payment_request_reupload(payment_id):
    """Section 9/11's third action — distinct from Reject: asks the customer for a fresh upload
    without recording the payment as REJECTED. See payment_service.request_reupload()'s own
    docstring for why this is a separate action/audit event."""
    admin = security.current_user()
    payment = payment_service.get_payment(payment_id)
    if payment is None:
        abort(404)
    try:
        payment_service.request_reupload(payment_id, payment["business_id"], admin["id"],
                                          admin_notes=request.form.get("admin_notes"))
    except ValueError as e:
        flash(f"Tidak bisa minta upload ulang: {e}", "error")
        return redirect(url_for("admin.payments_admin"))
    flash("Customer diminta upload ulang bukti pembayaran.", "success")
    return redirect(url_for("admin.payments_admin"))



@admin_bp.route("/talent")
@security.admin_required
def talent_admin():
    all_talents = talent_service.list_all_talents()
    all_requests = talent_service.list_all_talent_requests()
    businesses = {b["id"]: b for b in repo.list_all_businesses()}
    talents_by_id = {t["id"]: t for t in all_talents}

    search = (request.args.get("q") or "").strip()
    needle = search.casefold()
    talents = all_talents
    requests = all_requests
    if needle:
        talents = [
            t for t in talents
            if needle in str(t.get("name") or "").casefold()
            or needle in str(t.get("social_handle") or "").casefold()
            or needle in str(t.get("niche") or "").casefold()
            or needle in str(t.get("availability_status") or "").casefold()
            or needle in str(t.get("id") or "").casefold()
        ]
        requests = [
            r for r in requests
            if needle in str(r.get("id") or "").casefold()
            or needle in str(r.get("status") or "").casefold()
            or needle in str(r.get("brief") or "").casefold()
            or needle in str((talents_by_id.get(r.get("talent_id")) or {}).get("name") or "").casefold()
            or needle in str((businesses.get(r.get("business_id")) or {}).get("business_name") or "Pesanan pribadi").casefold()
        ]

    per_page = 10
    talents_total = len(talents)
    talent_total_pages = max(1, (talents_total + per_page - 1) // per_page)
    talent_page = request.args.get("talent_page", 1, type=int) or 1
    talent_page = min(max(1, talent_page), talent_total_pages)
    talent_start = (talent_page - 1) * per_page
    talents = talents[talent_start:talent_start + per_page]

    requests_total = len(requests)
    request_total_pages = max(1, (requests_total + per_page - 1) // per_page)
    request_page = request.args.get("request_page", 1, type=int) or 1
    request_page = min(max(1, request_page), request_total_pages)
    request_start = (request_page - 1) * per_page
    requests = requests[request_start:request_start + per_page]

    return render_template(
        "admin_talent.html",
        talents=talents,
        talents_total=talents_total,
        talent_page=talent_page,
        talent_total_pages=talent_total_pages,
        requests=requests,
        requests_total=requests_total,
        request_page=request_page,
        request_total_pages=request_total_pages,
        search=search,
        businesses_by_id=businesses,
        talents_by_id=talents_by_id,
        availability_statuses=talent_service.AVAILABILITY_STATUSES,
    )

@admin_bp.route("/talent/requests/<int:request_id>", methods=["GET", "POST"])
@security.admin_required
def talent_request_detail(request_id):
    admin = security.current_user()
    talent_request = talent_service.get_talent_request(request_id)
    if talent_request is None:
        abort(404)
    talent = talent_service.get_talent(talent_request["talent_id"])
    project = projects_repo.get_project(talent_request["project_id"]) if talent_request.get("project_id") else None
    if talent is None or project is None:
        abort(404)
    business = repo.get_business(talent_request["business_id"]) if talent_request.get("business_id") else None
    quotation = quotation_service.get_latest_quotation_for_project(project["id"])

    if request.method == "POST":
        if request.form.get("action") != "quote":
            abort(400)
        if talent_request["status"] not in ("WAITING_FOR_REVIEW", "WAITING_FOR_QUOTE") or project["status"] not in ("REQUESTED", "WAITING_FOR_QUOTE"):
            flash("Request ini sudah diproses atau statusnya sudah berubah. Muat ulang halaman.", "error")
            return redirect(url_for("admin.talent_request_detail", request_id=request_id))
        final_price = request.form.get("final_price", type=int)
        quantity = request.form.get("quantity", type=int)
        scope = (request.form.get("scope") or "").strip()
        deliverables = (request.form.get("deliverables") or "").strip()
        notes = (request.form.get("notes") or "").strip() or None
        if not final_price or final_price <= 0 or not scope or not deliverables:
            flash("Isi pekerjaan, hasil yang diterima customer, dan harga penawaran.", "error")
            return redirect(url_for("admin.talent_request_detail", request_id=request_id))
        try:
            quotation_service.create_quotation(
                project["id"], project["business_id"], scope, deliverables,
                quantity if quantity and quantity > 0 else 1, final_price, notes, admin["id"],
            )
        except ValueError:
            flash("Penawaran belum bisa dikirim karena status request sudah berubah.", "error")
            return redirect(url_for("admin.talent_request_detail", request_id=request_id))
        flash("Request disetujui dan penawaran harga sudah dikirim ke customer.", "success")
        return redirect(url_for("admin.talent_request_detail", request_id=request_id))

    return render_template(
        "admin_talent_request_detail.html", talent_request=talent_request, talent=talent,
        business=business, project=project, quotation=quotation,
    )


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
    conversations_total = len(conversations)
    inbox_per_page = 10
    inbox_total_pages = max(1, (conversations_total + inbox_per_page - 1) // inbox_per_page)
    inbox_page = request.args.get("page", 1, type=int) or 1
    inbox_page = min(max(1, inbox_page), inbox_total_pages)
    inbox_start = (inbox_page - 1) * inbox_per_page
    conversations = conversations[inbox_start:inbox_start + inbox_per_page]

    selected_phone = platform_inbox_service.normalize_customer_phone(request.args.get("customer"))

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
        template_readiness=platform_inbox_service.template_readiness() if selected and selected["mode"] == "HUMAN_TAKEOVER" and not (window and window.get("allowed")) else None,
        conversations=conversations,
        selected=selected,
        thread=thread,
        window=window,
        search=search,
        mode_filter=mode_filter,
        conversations_total=conversations_total,
        inbox_page=inbox_page,
        inbox_total_pages=inbox_total_pages,
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


@admin_bp.route("/inbox/contact-name", methods=["POST"])
@security.admin_required
def platform_inbox_contact_name():
    phone = platform_inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not platform_inbox_service.customer_exists(phone):
        abort(404)
    name = request.form.get("customer_name") or ""
    admin = security.current_user()
    try:
        saved = platform_inbox_service.update_customer_name(phone, name)
    except ValueError:
        flash("Nama kontak belum valid. Isi 1–120 karakter.", "error")
        return redirect(url_for("admin.platform_inbox", customer=phone))
    repo.write_audit_no_business(admin["id"], "PLATFORM_INBOX_CONTACT_RENAMED", f"customer={phone}")
    flash(f"Nama kontak disimpan: {saved}.", "success")
    return redirect(url_for("admin.platform_inbox", customer=phone))


@admin_bp.route("/inbox/delete-conversation", methods=["POST"])
@security.admin_required
def platform_inbox_delete_conversation():
    phone = platform_inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not platform_inbox_service.customer_exists(phone):
        abort(404)
    if request.form.get("confirmed") != "yes":
        abort(400)
    admin = security.current_user()
    platform_inbox_service.delete_conversation(phone)
    repo.write_audit_no_business(admin["id"], "PLATFORM_INBOX_CONVERSATION_DELETED", f"customer={phone}")
    flash("Riwayat chat di Inbox Kilas sudah dihapus. Pesan di aplikasi WhatsApp tidak ikut terhapus.", "success")
    return redirect(url_for("admin.platform_inbox"))


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


@admin_bp.route("/inbox/send-template", methods=["POST"])
@security.admin_required
def platform_inbox_send_template():
    """Inbox unification, Section 4/5 — "Kirim Template & Lanjutkan" for Kilas Works' own inbox.
    See platform_inbox_service.send_template_reply()'s own docstring for the full safety/config
    rationale — same shared 24h-window/template logic as the tenant inbox's equivalent action
    (client.inbox_send_template), differing only in send transport (internal bridge to the bot
    process, since Client Hub never holds Kilas Works' own WhatsApp token)."""
    phone = platform_inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not platform_inbox_service.customer_exists(phone):
        abort(404)

    ok, reason = platform_inbox_service.send_template_reply(phone)
    admin = security.current_user()
    if ok:
        repo.write_audit_no_business(admin["id"], "PLATFORM_CS_TEMPLATE_REPLY_SENT", f"customer={phone}")
        flash("Template terkirim. Begitu customer membalas, window 24 jam aktif lagi.", "success")
    else:
        import wa_inbox_shared
        friendly = wa_inbox_shared.template_error_message(reason, platform=True)
        flash(friendly, "error")
    return redirect(url_for("admin.platform_inbox", customer=phone))


@admin_bp.route('/inbox/media/<media_key>')
@security.admin_required
def inbox_media(media_key):
    row = inbox_media_service.get(media_key, None)
    if not row:
        abort(404)
    return inbox_media_service.serve(row, lambda: inbox_media_service.platform_download(row))


@admin_bp.route('/inbox/media', methods=['POST'])
@security.admin_required
def inbox_media_send():
    if not request.content_length or request.content_length > 12 * 1024 * 1024:
        abort(413)
    phone = request.form.get('customer_phone', '')
    if not platform_inbox_service.customer_exists(phone):
        abort(404)
    ok, reason = inbox_media_service.platform_send(phone, request.files.get('file'), request.form.get('caption'))
    flash(*inbox_media_service.upload_flash(ok, reason))
    return redirect(url_for('admin.platform_inbox', customer=phone))


@admin_bp.route('/projects/<int:project_id>/reference/<int:file_id>')
@security.admin_required
def guest_project_reference(project_id,file_id):
    row=db.query_one("SELECT * FROM project_files WHERE id=? AND project_id=? AND kind='REFERENCE'",(file_id,project_id))
    if not row:abort(404)
    import io
    from flask import send_file
    return send_file(io.BytesIO(bytes(row['content'])),mimetype=row['mime_type'],as_attachment=True,download_name=row['original_filename'])


@admin_bp.route('/projects/<int:project_id>/wa-link', methods=['POST'])
@security.admin_required
def renew_wa_order_link(project_id):
    import wa_checkout
    if not wa_checkout.session_for_project(project_id):abort(404)
    wa_checkout.renew(project_id)
    flash('Tautan diperbarui. Salin dan kirim ke customer yang tercatat pada order ini.', 'success')
    return redirect(url_for('admin.project_admin_detail',project_id=project_id))


@admin_bp.route('/ai-usage')
@security.admin_required
def ai_usage_dashboard():
    import ai_usage
    import ai_usage_fx
    # Aggregate all scopes only behind the admin gate. Clients get their own count only.
    phase = 'request_schema'
    try:
        ai_usage.check_monthly_schema()
        phase = 'monthly'
        usage = ai_usage.monthly(admin=True)
        seen = {row['tenant_id'] for row in usage}
        phase = 'businesses'
        businesses = repo.list_all_businesses()
        names = {b['id']: b['business_name'] for b in businesses}
        for business in businesses:
            if business['package'] != 'NONE' and business['id'] not in seen:
                phase = 'monthly'
                usage.extend(ai_usage.monthly(business['id']))
        for row in usage:
            row['name'] = names.get(row['tenant_id'], 'Kilas Works platform' if row['tenant_id'] is None else 'Bisnis historis')
        fx = ai_usage_fx.get_usd_idr()
        usage = ai_usage_fx.display_rows(usage, fx)

        # Admin list UX: search first, then paginate so the page stays short on mobile.
        search = (request.args.get('q') or '').strip()
        needle = search.casefold()
        if needle:
            usage = [
                row for row in usage
                if needle in str(row.get('name') or '').casefold()
                or needle in str(row.get('status') or '').casefold()
                or needle in str(row.get('tenant_id') if row.get('tenant_id') is not None else 'platform').casefold()
            ]

        usage_total = len(usage)
        usage_per_page = 10
        usage_total_pages = max(1, (usage_total + usage_per_page - 1) // usage_per_page)
        usage_page = request.args.get('page', 1, type=int) or 1
        usage_page = min(max(1, usage_page), usage_total_pages)
        usage_start = (usage_page - 1) * usage_per_page
        usage = usage[usage_start:usage_start + usage_per_page]

        phase = 'render'
        return render_template(
            'admin_ai_usage.html',
            usage=usage,
            usage_total=usage_total,
            usage_page=usage_page,
            usage_total_pages=usage_total_pages,
            search=search,
            pricing_date=ai_usage.PRICING_DATE,
            unavailable=False,
            fx=fx,
        )
    except Exception as exc:
        ai_usage.log_dashboard_failure(exc, phase)
        try:
            return render_template(
                'admin_ai_usage.html',
                usage=[],
                usage_total=0,
                usage_page=1,
                usage_total_pages=1,
                search=(request.args.get('q') or '').strip(),
                pricing_date=ai_usage.PRICING_DATE,
                unavailable=True,
                fx=None,
            ), 503
        except Exception as render_exc:
            ai_usage.log_dashboard_failure(render_exc, 'fallback_render')
            return 'Pemakaian AI belum tersedia. Coba lagi sebentar.', 503
