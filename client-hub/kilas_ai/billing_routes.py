"""Customer checkout and authorized Kilas admin payment review."""
import io

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for

import payment_service
import security
from . import billing, topups, payment_gateways
from .routes import ai_bp, enabled

admin_bp = Blueprint("kilas_ai_admin", __name__, url_prefix="/admin/kilas-ai")


@admin_bp.before_request
def admin_access():
    if not enabled():
        abort(404)
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or user["role"] != "KILAS_ADMIN":
        abort(404)


@ai_bp.post("/checkout")
def checkout():
    try:
        invoice_id = payment_gateways.current().subscription(session["user_id"])
    except billing.BillingError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_ai.invoice_page", invoice_id=invoice_id), code=303)


@ai_bp.get("/invoices/<int:invoice_id>")
def invoice_page(invoice_id):
    item = billing.invoice(session["user_id"], invoice_id)
    if not item:
        abort(404)
    return render_template("kilas_ai/invoice.html", invoice=item,
                           payment=billing.proof_status(session["user_id"], invoice_id),
                           bank=payment_service.BANK_DETAILS)


@ai_bp.post("/invoices/<int:invoice_id>/proof")
def proof_upload(invoice_id):
    if not billing.invoice(session["user_id"], invoice_id):
        abort(404)
    try:
        billing.submit_proof(session["user_id"], invoice_id, request.files.get("proof"))
    except billing.BillingError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_ai.invoice_page", invoice_id=invoice_id), code=303)


@ai_bp.post("/topups")
def topup_checkout():
    try:
        order_id = payment_gateways.current().capacity(session["user_id"], request.form.get("pack"))
    except topups.TopupError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_ai.topup_invoice", order_id=order_id), code=303)


@ai_bp.get("/topups/<int:order_id>")
def topup_invoice(order_id):
    item = topups.order(session["user_id"], order_id)
    if not item:
        abort(404)
    return render_template("kilas_ai/topup_invoice.html", invoice=item, bank=payment_service.BANK_DETAILS)


@ai_bp.post("/topups/<int:order_id>/proof")
def topup_proof_upload(order_id):
    if not topups.order(session["user_id"], order_id):
        abort(404)
    try:
        topups.submit_proof(session["user_id"], order_id, request.files.get("proof"))
    except topups.TopupError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_ai.topup_invoice", order_id=order_id), code=303)


@admin_bp.get("/payments")
def payments():
    from . import economics, audio_billing
    return render_template("kilas_ai/admin_payments.html", payments=billing.pending_payments(),
                           topup_payments=topups.pending_orders(), audio_payments=audio_billing.pending(), economics=economics.admin_snapshot())


@admin_bp.get("/topups/<int:order_id>/proof")
def topup_proof_view(order_id):
    item = topups.admin_proof(order_id)
    if not item:
        abort(404)
    response = send_file(io.BytesIO(bytes(item["proof_content"])), mimetype=item["proof_mime_type"],
                         as_attachment=False, download_name=item["proof_filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@admin_bp.post("/topups/<int:order_id>/review")
def topup_review(order_id):
    try:
        topups.review(order_id, session["user_id"], (request.form.get("decision") or "").upper(), request.form.get("note"))
    except topups.TopupError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_ai_admin.payments"), code=303)


@admin_bp.get("/payments/<int:payment_id>/proof")
def proof_view(payment_id):
    item = billing.admin_proof(payment_id)
    if not item:
        abort(404)
    response = send_file(io.BytesIO(bytes(item["proof_content"])), mimetype=item["proof_mime_type"],
                         as_attachment=False, download_name=item["proof_filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@admin_bp.post("/payments/<int:payment_id>/review")
def review(payment_id):
    decision = (request.form.get("decision") or "").upper()
    try:
        billing.review(payment_id, session["user_id"], decision, request.form.get("note"))
    except billing.BillingError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_ai_admin.payments"), code=303)
