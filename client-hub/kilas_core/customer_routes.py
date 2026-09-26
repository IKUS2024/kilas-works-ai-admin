"""Owner-facing Kilas Core Customers routes. AI Admin only; Finance remains separate."""
from flask import Blueprint, abort, redirect, render_template, request, url_for
import security
from kilas_core import customers, customer_insights
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
    # Reconcile any durable Demo WhatsApp binding before rendering CRM. This makes
    # historical demo chats immediately visible as Lead without requiring another message.
    try:
        customers.sync_demo_binding_lead(bid)
    except Exception:
        pass
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int) or 1
    stage = (request.args.get("stage") or "LEAD").strip().upper()
    if stage not in ("LEAD", "CUSTOMER"):
        stage = "LEAD"
    rows, total, page, pages = customers.list_customers(bid, q, page, stage)
    # Customer cards should reflect conversations visible in Inbox, not retired Web Chat counts.
    for row in rows:
        try:
            row["conversation_count"] = customer_insights.inbox_snapshot(
                bid, row["id"]
            )["conversation_count"]
        except Exception:
            row["conversation_count"] = int(row.get("conversation_count") or 0)
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
        snapshot = customer_insights.inbox_snapshot(bid, customer_id)
        insight = customer_insights.refresh(bid, customer_id, snapshot=snapshot)
    except customers.CustomerError as error:
        abort(error.status)
    return render_template("customer_detail.html", business=business, customer=customer,
                           insight=insight, inbox_snapshot=snapshot,
                           conversation_count=snapshot["conversation_count"],
                           saved=request.args.get("saved") == "1",
                           linked_jobs=linked_context(business,customer_id))




@customers_bp.post("/business/<int:bid>/customers/<customer_id>/insight/refresh")
@security.login_required
def refresh_insight(bid, customer_id):
    _business(bid)
    try:
        customers.get_customer(bid, customer_id)
        customer_insights.refresh(bid, customer_id, force=True)
    except customers.CustomerError as error:
        abort(error.status)
    return redirect(url_for("core_customers.detail_page", bid=bid, customer_id=customer_id), code=303)


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
        snapshot = customer_insights.inbox_snapshot(bid, customer_id)
        return render_template("customer_detail.html", business=business, customer=customer,
                               insight=customer_insights.get(bid, customer_id),
                               inbox_snapshot=snapshot,
                               conversation_count=snapshot["conversation_count"],
                               saved=False, form_error="Periksa kembali data customer.",
                               linked_jobs=linked_context(business,customer_id)), 400
    return redirect(url_for("core_customers.detail_page", bid=bid, customer_id=customer_id, saved=1))
