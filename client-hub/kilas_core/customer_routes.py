"""Owner-facing Kilas Core Customers routes. AI Admin only; Finance remains separate."""
from flask import Blueprint, abort, redirect, render_template, request, url_for
import security
from kilas_core import customers
from kilas_core.job_routes import linked_context

customers_bp = Blueprint("core_customers", __name__)


def _business(bid):
    business = security.require_business_access(bid)
    if not customers.enabled() or business.get("package") not in customers.AI_PACKAGES:
        abort(404)
    return business


@customers_bp.get("/business/<int:bid>/customers")
@security.login_required
def list_page(bid):
    business = _business(bid)
    # Demo WhatsApp uses a privacy-scoped mirrored Inbox instead of a Core conversation row.
    # Reconcile its durable binding into CRM on read so historical bindings created before
    # Lead sync was introduced become visible without requiring the prospect to chat again.
    try:
        from routes_client import sync_demo_kilas_lead
        sync_demo_kilas_lead(bid)
    except Exception:
        # Customers remains usable even if the demo mirror is temporarily unavailable.
        pass
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int) or 1
    stage = (request.args.get("stage") or "LEAD").strip().upper()
    if stage not in ("LEAD", "CUSTOMER"):
        stage = "LEAD"
    rows, total, page, pages = customers.list_customers(bid, q, page, stage)
    stage_label = {"LEAD": "lead", "CUSTOMER": "customer"}[stage]
    return render_template("customers.html", business=business, customers=rows,
                           total=total, page=page, pages=pages, search=q,
                           stage=stage, stage_label=stage_label)


@customers_bp.get("/business/<int:bid>/customers/<customer_id>")
@security.login_required
def detail_page(bid, customer_id):
    business = _business(bid)
    try:
        customer = customers.get_customer(bid, customer_id)
        conversations = customers.customer_conversations(bid, customer_id)
    except customers.CustomerError as error:
        abort(error.status)
    return render_template("customer_detail.html", business=business, customer=customer,
                           conversations=conversations, saved=request.args.get("saved") == "1",
                           linked_jobs=linked_context(business,customer_id))


@customers_bp.post("/business/<int:bid>/customers/<customer_id>")
@security.login_required
def update_profile(bid, customer_id):
    _business(bid)
    user = security.current_user()
    try:
        customers.update_customer(
            bid, customer_id,
            display_name=request.form.get("display_name"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            notes=request.form.get("notes"),
            stage=request.form.get("stage"),
            actor_id=user["id"],
        )
    except customers.CustomerError as error:
        if error.status == 404:
            abort(404)
        customer = customers.get_customer(bid, customer_id)
        business = security.require_business_access(bid)
        conversations = customers.customer_conversations(bid, customer_id)
        return render_template("customer_detail.html", business=business, customer=customer,
                               conversations=conversations, saved=False,
                               form_error="Periksa kembali data customer.",
                               linked_jobs=linked_context(business,customer_id)), 400
    return redirect(url_for("core_customers.detail_page", bid=bid, customer_id=customer_id, saved=1))
