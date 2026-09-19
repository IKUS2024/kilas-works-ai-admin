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
import quotation_service
import file_utils

projects_bp = Blueprint("projects", __name__)


@projects_bp.route("/services")
@security.login_required
def service_catalog_page():
    user = security.current_user()
    search = (request.args.get("q") or "").strip()
    needle = search.casefold()

    # Talent has a dedicated visual marketplace where the customer picks a real talent first.
    # Keep the generic service catalog from creating a second, ambiguous Talent Management flow.
    items = [item for item in catalog_service.list_active_catalog() if item["category"] != "TALENT"]
    category_order = catalog_service.CUSTOMER_CATEGORY_ORDER
    items.sort(key=lambda item: category_order.index(item['category']) if item['category'] in category_order else len(category_order) - 1.5)

    if needle:
        items = [
            item for item in items
            if needle in str(catalog_service.public_name(item) or "").casefold()
            or needle in str(item.get("name") or "").casefold()
            or needle in str(item.get("category") or "").casefold()
            or needle in str(catalog_service.service_description(item) or "").casefold()
            or needle in str(catalog_service.display_price(item) or "").casefold()
        ]

    services_total = len(items)
    per_page = 10
    total_pages = max(1, (services_total + per_page - 1) // per_page)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    page_items = items[start:start + per_page]

    by_category = {}
    for item in page_items:
        by_category.setdefault(item["category"], []).append(item)

    businesses = repo.list_businesses_for_user(user["id"]) if user["role"] != "KILAS_ADMIN" else []
    single_business = businesses[0] if len(businesses) == 1 else None
    unfinished_by_catalog_key = {}
    if single_business:
        for item in page_items:
            existing = projects_repo.get_unfinished_project_for_catalog_key(single_business["id"], item["catalog_key"])
            if existing:
                unfinished_by_catalog_key[item["catalog_key"]] = existing

    show_talent_entry = not needle or any(term in needle for term in ("talent", "creator", "influencer"))
    return render_template(
        "service_catalog.html", by_category=by_category, format_price=catalog_service.format_price,
        service_description=catalog_service.service_description, display_price=catalog_service.display_price,
        public_name=catalog_service.public_name, transport_policy=catalog_service.pricing_config.TRANSPORT_POLICY,
        businesses=businesses, single_business=single_business,
        unfinished_by_catalog_key=unfinished_by_catalog_key,
        search=search, services_total=services_total, page=page, total_pages=total_pages,
        show_talent_entry=show_talent_entry,
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


def _legacy_talent_project(project):
    return (
        project.get("catalog_key") == "talent_management"
        and db.query_one("SELECT id FROM talent_requests WHERE project_id=?", (project["id"],)) is None
    )


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
    if item['category'] == 'TALENT' or item['catalog_key'] == 'talent_management':
        return redirect(url_for('talent.talent_list'))
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


@projects_bp.route('/projects')
@security.login_required
def my_project_list():
    """Customer project list with view filter, search, and bounded pagination."""
    user = security.current_user()
    view = request.args.get('view', 'active')
    if view not in ('active', 'history', 'all'):
        view = 'active'
    search = (request.args.get('q') or '').strip()
    needle = search.casefold()

    projects = projects_repo.list_businessless_projects_for_user(user['id'], include_history=True)
    for business in repo.list_businesses_for_user(user['id']):
        projects.extend(projects_repo.list_projects_for_business(business['id']))
    if view == 'history':
        projects = [p for p in projects if p['status'] in _HISTORY_STATUSES]
    elif view == 'active':
        projects = [p for p in projects if p['status'] not in _HISTORY_STATUSES]
    projects = [p for p in projects if not _legacy_talent_project(p)]
    if needle:
        projects = [
            p for p in projects
            if needle in str(p.get('title') or '').casefold()
            or needle in str(p.get('project_type') or '').casefold()
            or needle in str(p.get('status') or '').casefold()
            or needle in str(p.get('id') or '').casefold()
            or needle in str(p.get('final_price') or '').casefold()
        ]
    projects.sort(key=lambda p: p['id'], reverse=True)

    projects_total = len(projects)
    per_page = 10
    total_pages = max(1, (projects_total + per_page - 1) // per_page)
    page = request.args.get('page', 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    projects = projects[start:start + per_page]
    return render_template(
        'project_list.html', business=None, projects=projects, view=view, search=search,
        projects_total=projects_total, page=page, total_pages=total_pages,
    )


@projects_bp.route("/business/<int:business_id>/projects")
@security.login_required
def project_list(business_id):
    """Business-scoped project list with search + 10 rows per page."""
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    view = request.args.get("view", "active")
    if view not in ("active", "history", "all"):
        view = "active"
    search = (request.args.get("q") or "").strip()
    needle = search.casefold()

    projects = projects_repo.list_projects_for_business(business["id"])
    if view == "active":
        projects = [p for p in projects if p["status"] not in _HISTORY_STATUSES]
    elif view == "history":
        projects = [p for p in projects if p["status"] in _HISTORY_STATUSES]
    projects = [p for p in projects if not _legacy_talent_project(p)]
    if needle:
        projects = [
            p for p in projects
            if needle in str(p.get("title") or "").casefold()
            or needle in str(p.get("project_type") or "").casefold()
            or needle in str(p.get("status") or "").casefold()
            or needle in str(p.get("id") or "").casefold()
            or needle in str(p.get("final_price") or "").casefold()
        ]

    projects_total = len(projects)
    per_page = 10
    total_pages = max(1, (projects_total + per_page - 1) // per_page)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    projects = projects[start:start + per_page]
    return render_template(
        "project_list.html", business=business, projects=projects, view=view, search=search,
        projects_total=projects_total, page=page, total_pages=total_pages,
    )


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
    if _legacy_talent_project(loaded) and loaded["status"] not in _HISTORY_STATUSES:
        flash("Flow Talent sudah diperbarui. Pilih profil talent dari marketplace untuk membuat request baru.", "info")
        return redirect(url_for("talent.talent_list"))
    if (loaded.get('requirements') or {}).get('_app_brief') == 1 and (project['business_id'] is None or project['status'] == 'REQUESTED'):
        return redirect(url_for('projects.purchase_brief', project_id=project_id))
    if project["business_id"] is not None:
        return redirect(url_for("projects.project_detail", business_id=project["business_id"], project_id=project_id))
    return render_template("project_view_no_business.html", project=project,
                           quotation=quotation_service.get_latest_quotation_for_project(project_id),
                           can_cancel=projects_repo.customer_can_cancel(project))


@projects_bp.route("/business/<int:business_id>/projects/<int:project_id>")
@security.login_required
def project_detail(business_id, project_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    project = projects_repo.get_project(project_id)
    if project is None or project["business_id"] != business["id"]:
        abort(404)
    if _legacy_talent_project(project) and project["status"] not in _HISTORY_STATUSES:
        flash("Flow Talent sudah diperbarui. Pilih profil talent dari marketplace untuk membuat request baru.", "info")
        return redirect(url_for("talent.talent_list"))
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
    return projects_repo.customer_can_cancel(project, payment)


@projects_bp.route("/business/<int:business_id>/projects/<int:project_id>/cancel", methods=["POST"])
@security.login_required
def cancel_project(business_id, project_id):
    return _cancel_project_for_customer(project_id, business_id)


@projects_bp.route('/projects/<int:project_id>/cancel', methods=['POST'])
@security.login_required
def cancel_personal_project(project_id):
    return _cancel_project_for_customer(project_id)


def _cancel_project_for_customer(project_id, business_id=None):
    user = security.current_user()
    project = security.require_project_access(project_id, user)
    if business_id is not None and project['business_id'] != business_id:
        abort(404)
    # Reuse the order's existing lock; attached WhatsApp orders keep their sender lock.
    session_row = db.query_one('SELECT phone_hash FROM wa_checkout_sessions WHERE project_id=?', (project_id,))
    transaction = (db.commerce_transaction(session_row['phone_hash']) if session_row else
                   db.app_purchase_transaction(project['business_id'], project['created_by_user_id']))
    with transaction:
        # PostgreSQL payment rows are locked before reading their state. SQLite's owner-row
        # write already serializes writers. No payment, invoice or quotation is changed here.
        if db.BACKEND == 'postgres':
            db.query_all('SELECT p.id FROM payments p JOIN invoices i ON i.id=p.invoice_id '
                         'WHERE i.project_id=? ORDER BY p.id FOR UPDATE OF p', (project_id,))
            db.query_all('SELECT id FROM invoices WHERE project_id=? ORDER BY id FOR UPDATE', (project_id,))
            db.query_one('SELECT id FROM projects WHERE id=? FOR UPDATE', (project_id,))
        project = security.require_project_access(project_id, user)
        if business_id is not None and project['business_id'] != business_id:
            abort(404)
        if not _project_can_be_self_cancelled(project, None):
            flash('Pesanan tidak dapat dibatalkan: pembayaran sedang direview atau sudah diproses.', 'error')
        else:
            detail = f'Dibatalkan oleh customer (project_id={project_id}); riwayat tetap tersimpan'
            projects_repo.set_project_status(project_id, 'CANCELLED', user['id'], project['business_id'], detail)
            if project['business_id'] is None:
                repo.write_audit(user['id'], None, 'PROJECT_STATUS_CHANGED', detail, project_id=project_id)
            flash('Pesanan dibatalkan. Riwayat transaksi tetap tersimpan.', 'success')
    return redirect(url_for('client.dashboard'))


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
