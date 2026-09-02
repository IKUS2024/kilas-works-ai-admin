"""Checkout, invoice display, and payment-proof upload — Business Hub V2, Phase C (Section 12).
Verification (admin-only) lives in routes_admin.py.
"""
import io

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_file

import db
import security
import payment_service
import projects_repo
import file_utils
import ai_payment_review

payments_bp = Blueprint("payments", __name__)


@payments_bp.route("/projects/<int:project_id>/checkout", methods=["GET", "POST"])
@security.login_required
def checkout_page(project_id):
    user = security.current_user()
    project = projects_repo.get_project(project_id)
    if project is None:
        abort(404)
    business = security.require_business_access(project["business_id"], user)

    if request.method == "GET":
        try:
            # A GET here is a "can I even reach checkout" pre-check — if not APPROVED yet, bounce
            # back to the project detail with the correct guidance rather than a raw error.
            if project["status"] != "APPROVED":
                flash("Checkout belum tersedia — project ini menunggu quotation disetujui.", "error")
                return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))
        except Exception:
            abort(404)
        return render_template("checkout.html", business=business, project=project, bank=payment_service.BANK_DETAILS)

    try:
        invoice_id = payment_service.checkout(project_id, business["id"], user["id"])
    except ValueError as e:
        flash(f"Checkout tidak tersedia: {e}", "error")
        return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))
    return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))


@payments_bp.route("/invoices/<int:invoice_id>", methods=["GET", "POST"])
@security.login_required
def invoice_page(invoice_id):
    user = security.current_user()
    invoice = payment_service.get_invoice(invoice_id)
    if invoice is None:
        abort(404)
    business = security.require_business_access(invoice["business_id"], user)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    review_status = payment_service.derive_review_status(payment) if payment else None

    if request.method == "GET":
        return render_template("invoice.html", business=business, invoice=invoice, payment=payment,
                                review_status=review_status, bank=payment_service.BANK_DETAILS)

    upload = request.files.get("proof_file")
    if not upload or not upload.filename:
        flash("Pilih file bukti transfer dulu.", "error")
        return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))

    content = upload.read()
    try:
        safe_name, mime_type, _ = file_utils.validate_and_extract(upload.filename, content, upload.mimetype)
    except file_utils.UploadRejected as e:
        flash(str(e), "error")
        return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))

    file_id = db.insert_returning_id(
        "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, "
        "size_bytes, content, uploaded_by_user_id) VALUES (?, ?, 'PAYMENT_PROOF', ?, ?, ?, ?, ?)",
        (business["id"], invoice["project_id"], safe_name, mime_type, len(content), content, user["id"]),
    )
    proof_hash = ai_payment_review.compute_file_hash(content)
    try:
        payment_service.upload_payment_proof(payment["id"], business["id"], file_id, user["id"],
                                              proof_file_hash=proof_hash)
    except ValueError as e:
        flash(f"Tidak bisa upload bukti: {e}", "error")
        return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))

    try:
        import owner_notifications
        owner_notifications.notify_payment_proof_uploaded(
            payment["id"], invoice_id, business["id"], business["business_name"], invoice["amount"],
        )
    except Exception:
        pass

    flash("Bukti pembayaran terkirim. Tim Kilas Works akan verifikasi.", "success")
    return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))


@payments_bp.route("/invoices/<int:invoice_id>/proof")
@security.login_required
def invoice_proof_view(invoice_id):
    """Final Operations Polish, Section 11: customer can see (open) their own uploaded proof —
    tenant-scoped through require_business_access exactly like invoice_page above, streamed by id
    from project_files, never a raw storage path."""
    user = security.current_user()
    invoice = payment_service.get_invoice(invoice_id)
    if invoice is None:
        abort(404)
    business = security.require_business_access(invoice["business_id"], user)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    if payment is None or not payment.get("proof_file_id"):
        abort(404)
    row = db.query_one(
        "SELECT * FROM project_files WHERE id = ? AND business_id = ?",
        (payment["proof_file_id"], business["id"]),
    )
    if row is None:
        abort(404)
    return send_file(io.BytesIO(row["content"]), mimetype=row["mime_type"] or "application/octet-stream")


@payments_bp.route("/business/<int:business_id>/invoices")
@security.login_required
def invoice_list(business_id):
    """Final Operations Polish, Section 10: customer-facing invoice/payment history with
    ACTIVE / HISTORY / ALL views, same convention as the project list below."""
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    view = request.args.get("view", "active")
    if view not in ("active", "history", "all"):
        view = "active"
    payments = payment_service.list_payments_for_business(business["id"])
    enriched = []
    for p in payments:
        invoice = payment_service.get_invoice(p["invoice_id"])
        if invoice is None:
            continue
        enriched.append({**p, "invoice": invoice})
    if view == "active":
        enriched = [e for e in enriched if e["status"] not in ("VERIFIED", "REJECTED")]
    elif view == "history":
        enriched = [e for e in enriched if e["status"] in ("VERIFIED", "REJECTED")]
    return render_template("invoice_list.html", business=business, payments=enriched, view=view)
