"""Service catalog browsing + custom project requests — Business Hub V2, Phase B (Section 4/7/8/9).
"""
import io
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file

import security
import repo
import db
import catalog_service
import projects_repo
import file_utils

projects_bp = Blueprint("projects", __name__)


@projects_bp.route("/services")
@security.login_required
def service_catalog_page():
    user = security.current_user()
    items = catalog_service.list_active_catalog()
    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)
    businesses = repo.list_businesses_for_user(user["id"]) if user["role"] != "KILAS_ADMIN" else []
    # New-customer purchase-flow fix, Section 6/8: when the customer has exactly ONE business (the
    # overwhelmingly common new-customer case), pre-compute which catalog items already have an
    # unfinished project for THAT business, so the template can show "Lanjutkan" instead of
    # "Pilih Layanan"/"Minta Penawaran" without needing JavaScript to react to a business-picker
    # dropdown. With 2+ businesses the picker stays dynamic (JS-driven, as before) — the
    # server-side reuse-on-click safety in start_fixed_checkout()/request_generic_quote() still
    # protects against duplicates either way, this only affects which LABEL is shown up front.
    single_business = businesses[0] if len(businesses) == 1 else None
    unfinished_by_catalog_key = {}
    if single_business:
        for item in items:
            existing = projects_repo.get_unfinished_project_for_catalog_key(single_business["id"], item["catalog_key"])
            if existing:
                unfinished_by_catalog_key[item["catalog_key"]] = existing
    return render_template(
        "service_catalog.html", by_category=by_category, format_price=catalog_service.format_price,
        businesses=businesses, single_business=single_business,
        unfinished_by_catalog_key=unfinished_by_catalog_key,
    )


@projects_bp.route("/services/<catalog_key>/checkout-fixed", methods=["POST"])
@security.login_required
def start_fixed_checkout(catalog_key):
    """FIXED_PRICE items are checkout-ready immediately (Section 6) — this creates the project
    (status APPROVED) so the very next step is payment_service.checkout()."""
    user = security.current_user()
    business_id = request.form.get("business_id", type=int)
    business = security.require_business_access(business_id, user)
    item = catalog_service.get_catalog_item(catalog_key)
    if item is None or item["pricing_mode"] not in ("FIXED_PRICE", "STARTING_FROM") or not item["is_active"]:
        abort(404)
    if item["category"] == "AI_ADMIN":
        # Business flow cleanup — AI Admin has exactly ONE purchase path: the business-info wizard
        # (dashboard "+ Tambah AI Admin"/"Buat Business" -> wizard -> review ->
        # client.ai_admin_checkout). This route is the generic instant-checkout path every OTHER
        # fixed-price service uses; it must never also be a second, wizard-bypassing way to buy AI
        # Admin (service_catalog.html no longer renders this form for the AI_ADMIN category at
        # all — this is a defense-in-depth guard against a stale cached page or a direct POST).
        flash("AI Admin diatur lewat Dashboard — isi data bisnis dulu sebelum pembayaran.", "error")
        return redirect(url_for("client.dashboard"))

    # Repeat-click / refresh safety (purchase-flow fix, Section 6): reuse an existing unfinished
    # project for this exact business+catalog_key instead of creating a second one — a customer
    # clicking "Pilih Layanan" again (double-click, back button, refresh) lands on the SAME
    # project/checkout, never a duplicate.
    existing = projects_repo.get_unfinished_project_for_catalog_key(business["id"], catalog_key)
    if existing:
        return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=existing["id"]))

    project_id = projects_repo.create_fixed_price_project(business["id"], item, user["id"])
    flash(f"{item['name']} ditambahkan. Lanjut ke checkout.", "success")
    return redirect(url_for("payments.checkout_page", project_id=project_id))


@projects_bp.route("/business/<int:business_id>/projects/custom/<project_type>", methods=["GET", "POST"])
@security.login_required
def custom_project_request(business_id, project_type):
    project_type = project_type.upper()
    if project_type not in ("VIDEO", "PHOTO", "WEBSITE", "APPLICATION", "CONTENT"):
        abort(404)
    user = security.current_user()
    business = security.require_business_access(business_id, user)

    if request.method == "GET":
        return render_template("custom_project_request.html", business=business, project_type=project_type)

    form = request.form
    budget_min = form.get("budget_min", type=int)
    budget_max = form.get("budget_max", type=int)

    catalog_key = None
    if project_type == "CONTENT":
        requirements = {
            "need": form.get("need"), "quantity": form.get("quantity"),
            "platform": form.get("platform"), "location": form.get("location"),
            "deadline": form.get("deadline"), "style": form.get("style"),
            "notes": form.get("notes"),
        }
        title = f"Custom Content — {form.get('project_name') or 'Tanpa nama'}"
        catalog_key = "custom_content"
    elif project_type == "VIDEO":
        requirements = {
            "num_videos": form.get("num_videos"), "duration": form.get("duration"),
            "platform": form.get("platform"), "location": form.get("location"),
            "preferred_date": form.get("preferred_date"), "style": form.get("style"),
            "reference": form.get("reference"), "editing_required": form.get("editing_required") == "on",
            "notes": form.get("notes"),
        }
        title = f"Custom Video — {form.get('project_name') or 'Tanpa nama'}"
    elif project_type == "PHOTO":
        requirements = {
            "photoshoot_type": form.get("photoshoot_type"), "num_final_photos": form.get("num_final_photos"),
            "location": form.get("location"), "preferred_date": form.get("preferred_date"),
            "usage": form.get("usage"), "style": form.get("style"), "notes": form.get("notes"),
        }
        title = f"Custom Photo — {form.get('project_name') or 'Tanpa nama'}"
    else:  # WEBSITE / APPLICATION
        requirements = {
            "goal": form.get("goal"), "pages_features": form.get("pages_features"),
            "references": form.get("references"), "target_date": form.get("target_date"),
            "notes": form.get("notes"),
        }
        title = f"Custom {project_type.title()} — {form.get('project_name') or 'Tanpa nama'}"

    project_id = projects_repo.create_custom_project(
        business["id"], project_type, title, requirements, budget_min, budget_max, user["id"],
        catalog_key=catalog_key,
    )

    # Optional "Upload Brief / Referensi" attachment (Section: custom project attachments). Never
    # blocks the request itself — a rejected/missing file just skips this step with a flash message,
    # the project is still created (matches the existing text-only reference field's behavior).
    upload = request.files.get("attachment")
    if upload and upload.filename:
        content = upload.read()
        try:
            safe_name, mime_type = file_utils.validate_project_attachment_upload(upload.filename, content)
            db.execute(
                "INSERT INTO project_files (business_id, project_id, kind, original_filename, "
                "mime_type, size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'REFERENCE', ?, ?, ?, ?, ?)",
                (business["id"], project_id, safe_name, mime_type, len(content), content, user["id"]),
            )
        except file_utils.UploadRejected as e:
            flash(f"Permintaan terkirim, tapi file lampiran ditolak: {e}", "error")

    flash("Permintaan custom terkirim. Tim Kilas Works akan menyiapkan penawaran.", "success")
    return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))


_HISTORY_STATUSES = ("COMPLETED", "CANCELLED")


@projects_bp.route("/services/<catalog_key>/request-quote", methods=["POST"])
@security.login_required
def request_generic_quote(catalog_key):
    """Generic "Minta Penawaran" for CUSTOM_QUOTE catalog items whose category has no
    dedicated requirement-specific form (BUNDLE, ADS, EVENT, or any future category) — the
    purchase-flow fix's Section 1/4/5 gap: these previously had literally no actionable CTA on
    the catalog page (service_catalog.html rendered a bare, unclickable "Custom Quote" label).
    Reuses the SAME generic projects_repo.create_custom_project() every type-specific custom
    request already goes through — this is a simpler ENTRY POINT (one free-text notes field
    instead of a type-specific requirements form), not a second data path. Never invents a price:
    the created project starts at WAITING_FOR_QUOTE with final_price=NULL, identical to every
    other custom request."""
    user = security.current_user()
    business_id = request.form.get("business_id", type=int)
    business = security.require_business_access(business_id, user)
    item = catalog_service.get_catalog_item(catalog_key)
    if item is None or item["pricing_mode"] != "CUSTOM_QUOTE" or not item["is_active"]:
        abort(404)
    if item["category"] in ("TALENT", "CONTENT", "VIDEO", "PHOTO", "WEBSITE", "APPLICATION"):
        # These categories already have their own dedicated, more detailed request flow
        # (talent.talent_list / custom_project_request) — this generic route is only the
        # fallback for categories that don't, so it never becomes a second, competing path for
        # a category that already has a purpose-built one.
        abort(404)

    # Repeat-click / refresh safety (Section 6): reuse an existing unfinished quote request for
    # this exact business+catalog_key rather than creating a second one.
    existing = projects_repo.get_unfinished_project_for_catalog_key(business["id"], catalog_key)
    if existing:
        return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=existing["id"]))

    project_type = item["category"] if item["category"] in projects_repo.PROJECT_TYPES else "OTHER"
    notes = (request.form.get("notes") or "").strip()
    requirements = {"notes": notes} if notes else {}
    project_id = projects_repo.create_custom_project(
        business["id"], project_type, item["name"], requirements, None, None, user["id"],
        catalog_key=catalog_key,
    )
    flash(f"Permintaan penawaran untuk {item['name']} terkirim. Tim Kilas Works akan follow up.", "success")
    return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))


@projects_bp.route("/business/<int:business_id>/projects")
@security.login_required
def project_list(business_id):
    """Final Operations Polish, Section 10/13: ACTIVE / HISTORY / ALL views — completed/cancelled
    projects are never permanently hidden, just filtered by default so day-to-day use isn't
    cluttered with old records. Tenant isolation is unchanged (require_business_access above)."""
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    view = request.args.get("view", "active")
    if view not in ("active", "history", "all"):
        view = "active"
    projects = projects_repo.list_projects_for_business(business["id"])
    if view == "active":
        projects = [p for p in projects if p["status"] not in _HISTORY_STATUSES]
    elif view == "history":
        projects = [p for p in projects if p["status"] in _HISTORY_STATUSES]
    return render_template("project_list.html", business=business, projects=projects, view=view)


@projects_bp.route("/business/<int:business_id>/projects/<int:project_id>")
@security.login_required
def project_detail(business_id, project_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    project = projects_repo.get_project(project_id)
    if project is None or project["business_id"] != business["id"]:
        abort(404)
    import quotation_service
    quotations = quotation_service.list_quotations_for_business(business["id"])
    quotations = [q for q in quotations if q["project_id"] == project_id]
    attachments = db.query_all(
        "SELECT id, original_filename, mime_type, size_bytes, created_at FROM project_files "
        "WHERE project_id = ? AND business_id = ? AND kind = 'REFERENCE' ORDER BY created_at DESC",
        (project_id, business["id"]),
    )
    # Customer order actions (Batch 1, Section 3) — the payment's OWN status (not just the
    # project's) determines whether self-cancel is safe: a project can be PAYMENT_PENDING with NO
    # payment attempt yet (safe to cancel) or PAYMENT_PENDING with a proof already under human
    # review (must NOT be self-cancellable — a human is actively reviewing money that may have
    # already been sent). Reuses payment_service's existing invoice/payment lookups, no new table.
    import payment_service
    invoice, payment = payment_service.get_latest_payment_for_project(project_id)
    can_cancel = _project_can_be_self_cancelled(project, payment)
    return render_template("project_detail.html", business=business, project=project,
                            quotations=quotations, attachments=attachments,
                            payment=payment, can_cancel=can_cancel)


def _project_can_be_self_cancelled(project, payment):
    """A customer may only cancel their OWN order before any money is genuinely in flight:
    WAITING_FOR_QUOTE (no price agreed yet) or APPROVED/PAYMENT_PENDING with NO payment proof
    uploaded yet (payment is None, or still PAYMENT_PENDING/REJECTED — REJECTED means an earlier
    proof was rejected and no new one is under review, so cancelling is still safe). Once a proof
    is UNDER_REVIEW, or the payment is VERIFIED, or the project has moved to PAID/IN_PROGRESS/
    COMPLETED, self-cancel is no longer offered — matches the exact behavior requested."""
    if project["status"] in ("CANCELLED", "REJECTED", "COMPLETED"):
        return False
    if project["status"] in ("WAITING_FOR_QUOTE", "APPROVED"):
        return True
    if project["status"] == "PAYMENT_PENDING":
        if payment is None:
            return True
        return payment["status"] in ("PAYMENT_PENDING", "REJECTED")
    return False


@projects_bp.route("/business/<int:business_id>/projects/<int:project_id>/cancel", methods=["POST"])
@security.login_required
def cancel_project(business_id, project_id):
    """Customer-initiated cancellation (Batch 1, Section 3) — reuses projects_repo.
    set_project_status() exactly as every other status transition in this codebase does (writes
    an audit row, never deletes anything). The project/invoice/payment rows all remain in the
    database permanently as a CANCELLED historical record — this route has no DELETE statement
    anywhere in it."""
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    project = projects_repo.get_project(project_id)
    if project is None or project["business_id"] != business["id"]:
        abort(404)
    import payment_service
    _invoice, payment = payment_service.get_latest_payment_for_project(project_id)
    if not _project_can_be_self_cancelled(project, payment):
        flash("Pesanan ini tidak bisa dibatalkan sendiri — bukti pembayaran sedang direview atau sudah diproses.", "error")
        return redirect(url_for("projects.project_detail", business_id=business_id, project_id=project_id))
    projects_repo.set_project_status(project_id, "CANCELLED", user["id"], business_id,
                                      detail=f"Dibatalkan oleh customer (project_id={project_id})")
    flash("Pesanan dibatalkan.", "success")
    return redirect(url_for("projects.project_list", business_id=business_id, view="all"))


@projects_bp.route("/business/<int:business_id>/projects/<int:project_id>/attachments/<int:file_id>")
@security.login_required
def project_attachment_download(business_id, project_id, file_id):
    """Serves a custom project's REFERENCE attachment (the optional "Upload Brief / Referensi"
    field). Same access pattern as payment-proof viewing: authenticated route only (never an
    unauthenticated static file URL), the owning customer's business can view its own attachment,
    KILAS_ADMIN can view any project's — security.require_business_access() already raises a clean
    404 (never the file) for any other logged-in user, same as every other tenant-scoped file
    download in this app."""
    business = security.require_business_access(business_id, security.current_user())
    row = db.query_one(
        "SELECT * FROM project_files WHERE id = ? AND project_id = ? AND business_id = ? AND kind = 'REFERENCE'",
        (file_id, project_id, business["id"]),
    )
    if row is None:
        abort(404)
    return send_file(
        io.BytesIO(row["content"]), mimetype=row["mime_type"] or "application/octet-stream",
        as_attachment=True, download_name=row["original_filename"],
    )
