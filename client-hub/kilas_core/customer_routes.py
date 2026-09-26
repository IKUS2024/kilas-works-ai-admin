"""Owner-facing Kilas Core Customers routes. AI Admin only; Finance remains separate."""
from flask import Blueprint, abort, redirect, render_template, request, url_for
import security
import platform_workspace
from kilas_core import customers, customer_insights, customer_action_jobs
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
    if platform_workspace.is_scope_business(bid):
        try:
            platform_workspace.sync_contacts()
        except Exception:
            pass
        # Reconcile only a small bounded batch on normal page loads. The raw keyword prefilter
        # never promotes; Customer Insight must independently confirm a concrete customer action.
        try:
            customer_action_jobs.reconcile_actionable_platform_leads(
                business, actor_id=security.current_user()["id"], limit=3
            )
        except Exception:
            pass
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
    # CRM counts the same WhatsApp Inbox sources used by Customer Insight.
    # Retired Web Chat history is intentionally excluded.
    for row in rows:
        row["conversation_count"] = len(
            customer_insights.whatsapp_conversation_rows(bid, row["id"])
        )
        if customer_insights.demo_conversation_row(bid, row):
            row["conversation_count"] += 1
        if customer_insights.platform_conversation_row(bid, row):
            row["conversation_count"] += 1
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
        conversations = customer_insights.whatsapp_conversation_rows(bid, customer_id)
    except customers.CustomerError as error:
        abort(error.status)
    platform = customer_insights.platform_conversation_row(bid, customer)
    if platform:
        conversations.insert(0, platform)
    demo = customer_insights.demo_conversation_row(bid, customer)
    if demo:
        conversations.insert(0, demo)
    insight, _ = customer_action_jobs.refresh_and_sync(
        business, customer, actor_id=security.current_user()["id"]
    )
    try:
        customer = customers.get_customer(bid, customer_id)
    except customers.CustomerError:
        pass
    return render_template("customer_detail.html", business=business, customer=customer,
                           conversations=conversations, insight=insight,
                           saved=request.args.get("saved") == "1",
                           linked_jobs=linked_context(business,customer_id))


@customers_bp.get("/business/<int:bid>/customers/<customer_id>/insight")
@security.login_required
def insight_fragment(bid, customer_id):
    business = _business(bid)
    try:
        customer = customers.get_customer(bid, customer_id)
    except customers.CustomerError as error:
        abort(error.status)
    insight, _ = customer_action_jobs.refresh_and_sync(
        business, customer, actor_id=security.current_user()["id"]
    )
    try:
        customer = customers.get_customer(bid, customer_id)
    except customers.CustomerError:
        pass
    return render_template("_customer_insight.html", business=business,
                           customer=customer, insight=insight)


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
        conversations = customer_insights.whatsapp_conversation_rows(bid, customer_id)
        platform = customer_insights.platform_conversation_row(bid, customer)
        if platform:
            conversations.insert(0, platform)
        demo = customer_insights.demo_conversation_row(bid, customer)
        if demo:
            conversations.insert(0, demo)
        insight = customer_insights.safe_refresh(business, customer)
        try:
            customer_action_jobs.sync_from_insight(business, customer, insight)
        except Exception:
            pass
        return render_template("customer_detail.html", business=business, customer=customer,
                               conversations=conversations, insight=insight, saved=False,
                               form_error="Periksa kembali data customer.",
                               linked_jobs=linked_context(business,customer_id)), 400
    # Promotion to Customer is the only point where this CRM contact becomes eligible
    # for an AI action Job. Re-read the authoritative profile and refresh Insight; if the
    # customer has not stated a concrete action, sync remains a no-op and Jobs stays empty.
    try:
        customer = customers.get_customer(bid, customer_id)
        if customer.get("stage") == "CUSTOMER":
            business = security.require_business_access(bid)
            insight = customer_insights.safe_refresh(business, customer)
            customer_action_jobs.sync_from_insight(business, customer, insight)
    except Exception:
        pass
    return redirect(url_for("core_customers.detail_page", bid=bid, customer_id=customer_id, saved=1))
