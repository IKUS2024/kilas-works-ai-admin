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
    category_order = catalog_service.CUSTOMER_CATEGORY_ORDER
    items.sort(key=lambda item: category_order.index(item['category']) if item['category'] in category_order else len(category_order) - 1.5)
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
        service_description=catalog_service.service_description, display_price=catalog_service.display_price,
        public_name=catalog_service.public_name, transport_policy=catalog_service.pricing_config.TRANSPORT_POLICY,
        businesses=businesses, single_business=single_business,
        unfinished_by_catalog_key=unfinished_by_catalog_key,
    )


@projects_bp.route("/services/<catalog_key>/checkout-fixed", methods=["POST"])
@security.login_required
def start_fixed_checkout(catalog_key):
    return _start_catalog_brief(catalog_key, fixed_only=True)


@projects_bp.route("/business/<int:business_id>/projects/custom/<project_type>", methods=["GET", "POST"])
@security.login_required
def custom_project_request(business_id, project_type):
    return _custom_project_request_impl(project_type, business_id=business_id)


@projects_bp.route("/projects/custom/<project_type>", methods=["GET", "POST"])
@security.login_required
def custom_project_request_no_business(project_type):
    """Purchase-flow correction: CUSTOM_QUOTE services (Content/Video/Photo/Website/Application)
    must work end-to-end without ever requiring a business — a true parallel route (not a sentinel
    business_id that resolves/creates one), sharing the exact same implementation as the
    business-scoped route above via _custom_project_request_impl()."""
    return _custom_project_request_impl(project_type, business_id=None)


def _custom_project_request_impl(project_type, business_id):
    # Retain old URLs without keeping a second set of questions or a submission bypass.
    if business_id:
        security.require_business_access(business_id, security.current_user())
    if project_type.upper() not in ("VIDEO", "PHOTO", "WEBSITE", "APPLICATION", "CONTENT"):
        abort(404)
    flash("Pilih layanan untuk melanjutkan brief dan review order.", "info")
    return redirect(url_for("projects.service_catalog_page"))


_HISTORY_STATUSES = ("COMPLETED", "CANCELLED")


@projects_bp.route("/services/<catalog_key>/request-quote", methods=["POST"])
@security.login_required
def request_generic_quote(catalog_key):
    return _start_catalog_brief(catalog_key, custom_only=True)


def _start_catalog_brief(catalog_key, fixed_only=False, custom_only=False):
    user = security.current_user()
    item = catalog_service.get_catalog_item(catalog_key)
    if not item or not item['is_active'] or item['category'] == 'BUNDLE':
        abort(404)
    if item['category'] == 'AI_ADMIN':
        return redirect(url_for('client.dashboard'))
    if fixed_only and item['pricing_mode'] not in ('FIXED_PRICE', 'STARTING_FROM'):
        abort(404)
    if custom_only and item['pricing_mode'] != 'CUSTOM_QUOTE':
        abort(404)
    business_id = request.form.get('business_id', type=int)
    if business_id:
        security.require_business_access(business_id, user)
    with db.app_purchase_transaction(business_id, user['id']):
        existing = projects_repo.get_unfinished_project_for_catalog_key(business_id, catalog_key, user['id'])
        if existing:
            project_id = existing['id']
        else:
            if item['pricing_mode'] == 'CUSTOM_QUOTE':
                project_id = projects_repo.create_custom_project(
                    business_id, projects_repo._project_type_for_category(item['category']), item['name'],
                    {}, None, None, user['id'], catalog_key=catalog_key, draft=True)
            else:
                project_id = projects_repo.create_fixed_price_project(business_id, item, user['id'], draft=True)
            db.execute('UPDATE projects SET requirements_json=? WHERE id=?',
                       (json.dumps({'_app_brief': 1}), project_id))
    project = projects_repo.get_project(project_id)
    endpoint = 'projects.purchase_brief' if (project.get('requirements') or {}).get('_app_brief') == 1 else 'projects.project_view'
    return redirect(url_for(endpoint, project_id=project_id))


def _review_version(brief):
    import hashlib
    return hashlib.sha256(json.dumps(brief, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


@projects_bp.route('/projects/<int:project_id>/brief', methods=['GET', 'POST'])
@security.login_required
def purchase_brief(project_id):
    import wa_checkout as shared
    import payment_service
    import quotation_service
    user = security.current_user()
    security.require_project_access(project_id, user)
    project = projects_repo.get_project(project_id)
    if (project.get('requirements') or {}).get('_app_brief') != 1:
        return redirect(url_for('projects.project_view', project_id=project_id))
    item = catalog_service.get_catalog_item(project['catalog_key'])
    if not item or item['category'] == 'AI_ADMIN':
        abort(404)
    item = dict(item, pricing_mode=project['pricing_mode'])
    error = None
    if request.method == 'POST':
        notify_submitted = False
        try:
            with db.app_purchase_transaction(project['business_id'], project['created_by_user_id']):
                security.require_project_access(project_id, user)
                project = projects_repo.get_project(project_id)
                saved = project.get('requirements') or {}
                action = request.form.get('action')
                if action == 'brief' and project['status'] == 'REQUESTED':
                    brief = shared.clean(request.form, item)
                    if shared.missing(item, brief):
                        raise ValueError('brief_incomplete')
                    upload = request.files.get('reference_file')
                    if upload and upload.filename:
                        content = upload.read(file_utils.MAX_ATTACHMENT_UPLOAD_BYTES + 1)
                        name, mime = file_utils.validate_project_attachment_upload(upload.filename, content)
                        existing = db.query_one("SELECT id FROM project_files WHERE project_id=? AND kind='REFERENCE' AND original_filename=? AND content=?", (project_id, name, content))
                        if not existing:
                            db.execute("INSERT INTO project_files (business_id,project_id,kind,original_filename,mime_type,size_bytes,content,uploaded_by_user_id) VALUES (?,?,'REFERENCE',?,?,?,?,?)", (project['business_id'],project_id,name,mime,len(content),content,user['id']))
                    brief.update(_app_brief=1, _review_version=_review_version(brief))
                    db.execute('UPDATE projects SET requirements_json=? WHERE id=?', (json.dumps(brief, ensure_ascii=False), project_id))
                elif action == 'confirm' and project['status'] == 'REQUESTED':
                    brief = shared.clean(saved, item)
                    if shared.missing(item, brief) or not saved.get('_review_version') or request.form.get('review_version') != saved['_review_version']:
                        raise ValueError('review_required')
                    saved['_brief_confirmed'] = True
                    db.execute('UPDATE projects SET requirements_json=? WHERE id=?', (json.dumps(saved, ensure_ascii=False), project_id))
                    status = 'WAITING_FOR_QUOTE' if project['pricing_mode'] == 'CUSTOM_QUOTE' else 'APPROVED'
                    projects_repo.set_project_status(project_id, status, user['id'], project['business_id'], 'Customer confirmed service brief')
                    notify_submitted = status == 'WAITING_FOR_QUOTE'
                    if status == 'APPROVED':
                        invoice_id = payment_service.checkout(project_id, project['business_id'], user['id'])
                        return redirect(url_for('payments.invoice_page', invoice_id=invoice_id))
                elif action == 'approve' and project['status'] == 'QUOTED':
                    quote = quotation_service.get_latest_quotation_for_project(project_id)
                    if not quote or str(quote['id']) != request.form.get('quotation_id'):
                        raise ValueError('quote_changed')
                    quotation_service.approve_quotation(quote['id'], project['business_id'], user['id'])
                    invoice_id = payment_service.checkout(project_id, project['business_id'], user['id'])
                    return redirect(url_for('payments.invoice_page', invoice_id=invoice_id))
                elif project['status'] == 'REQUESTED':
                    raise ValueError('review_required')
            if notify_submitted:
                import owner_notifications
                try:
                    owner_notifications.notify_custom_project_submitted(project_id, project['business_id'], project['project_type'], project['title'])
                except Exception:
                    pass  # Notification failure must not undo an already committed brief.
            return redirect(url_for('projects.purchase_brief', project_id=project_id))
        except (ValueError, file_utils.UploadRejected):
            error = 'Lengkapi brief dan periksa kembali review atau lampiran sebelum melanjutkan.'
    project = projects_repo.get_project(project_id)
    saved = project.get('requirements') or {}
    brief = {k:v for k,v in saved.items() if k in shared.FIELDS}
    if error and request.form.get('action') == 'brief':
        try:
            brief = shared.clean(request.form, item)
        except ValueError:
            pass
    review = project['status'] == 'REQUESTED' and bool(saved.get('_review_version')) and request.args.get('edit') != '1' and not error
    required, optional = shared.fields(item)
    price = 'Penawaran' if project['pricing_mode'] == 'CUSTOM_QUOTE' else catalog_service.format_price(project['final_price'], item['price_unit'])
    return render_template('service_brief.html', project=project, item=item, brief=brief, labels=shared.FIELDS,
                           required=required, optional=optional, review=review, version=saved.get('_review_version'),
                           error=error, price=price, description=catalog_service.service_description(item),
                           invoice=payment_service.get_latest_invoice_for_project(project_id),
                           quote=quotation_service.get_latest_quotation_for_project(project_id)), 400 if error else 200


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


@projects_bp.route("/projects/<int:project_id>")
@security.login_required
def project_view(project_id):
    """Business-less project view (purchase-flow correction) — the canonical URL for a project
    that has no business attached yet (business_id IS NULL): a general fixed-price selection
    before checkout, or a custom-quote/Talent request, made by a customer who has never created a
    business. Uses require_project_access() (owner-based, since there's no business_memberships
    row to check) instead of require_business_access(). If the project DOES have a business
    (already attached, or simply a normal business-scoped project), redirect to the existing
    canonical business-scoped URL instead of duplicating that page here."""
    user = security.current_user()
    project = security.require_project_access(project_id, user)
    loaded = projects_repo.get_project(project_id)
    if (loaded.get('requirements') or {}).get('_app_brief') == 1 and (project['business_id'] is None or project['status'] == 'REQUESTED'):
        return redirect(url_for('projects.purchase_brief', project_id=project_id))
    if project["business_id"] is not None:
        return redirect(url_for("projects.project_detail", business_id=project["business_id"], project_id=project_id))
    return render_template("project_view_no_business.html", project=project)


@projects_bp.route("/business/<int:business_id>/projects/<int:project_id>")
@security.login_required
def project_detail(business_id, project_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    project = projects_repo.get_project(project_id)
    if project is None or project["business_id"] != business["id"]:
        abort(404)
    if (project.get('requirements') or {}).get('_app_brief') == 1 and project['status'] == 'REQUESTED':
        return redirect(url_for('projects.purchase_brief', project_id=project_id))
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
