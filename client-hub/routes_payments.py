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
    business = security.require_business_access(project["business_id"], user) if project["business_id"] else None
    if business is None:
        security.require_project_access(project_id, user)

    if request.method == "GET":
        try:
            # Bug fix (real production incident): PAYMENT_PENDING means checkout ALREADY
            # happened once for this project — that is a normal, expected state (customer
            # refreshed, went back, or revisited "Lanjut ke Pembayaran"), never a reason to bounce
            # them away. Only a status that genuinely ISN'T checkout-ready yet (WAITING_FOR_QUOTE,
            # DRAFT, etc.) gets the "not available yet" message — matches payment_service.
            # checkout()'s own gate exactly, so GET and POST never disagree about what's allowed.
            if project["status"] == "PAYMENT_PENDING":
                existing_invoice = payment_service.get_latest_invoice_for_project(project_id)
                if existing_invoice is not None:
                    return redirect(url_for("payments.invoice_page", invoice_id=existing_invoice["id"]))
                # PAYMENT_PENDING with no invoice yet found (data-integrity edge case) — fall
                # through to payment_service.checkout() below, which safely recovers this exact
                # case (creates the missing invoice idempotently, see its own docstring).
            elif project["status"] != "APPROVED":
                flash("Checkout belum tersedia — project ini menunggu quotation disetujui.", "error")
                if business:
                    return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))
                return redirect(url_for("projects.project_view", project_id=project_id))
        except Exception:
            abort(404)
        return render_template("checkout.html", business=business, project=project, bank=payment_service.BANK_DETAILS)

    try:
        invoice_id = payment_service.checkout(project_id, business["id"] if business else None, user["id"])
    except ValueError as e:
        flash(f"Checkout tidak tersedia: {e}", "error")
        if business:
            return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))
        return redirect(url_for("projects.project_view", project_id=project_id))
    return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))


@payments_bp.route("/invoices/<int:invoice_id>", methods=["GET", "POST"])
@security.login_required
def invoice_page(invoice_id):
    user = security.current_user()
    invoice = payment_service.get_invoice(invoice_id)
    if invoice is None:
        abort(404)
    business = security.require_business_access(invoice["business_id"], user) if invoice["business_id"] else None
    if business is None:
        project = projects_repo.get_project(invoice["project_id"])
        security.require_project_access(project["id"], user) if project else abort(404)
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
        (business["id"] if business else None, invoice["project_id"], safe_name, mime_type,
         len(content), content, user["id"]),
    )
    proof_hash = ai_payment_review.compute_file_hash(content)
    try:
        payment_service.upload_payment_proof(payment["id"], business["id"] if business else None, file_id,
                                              user["id"], proof_file_hash=proof_hash, image_bytes=content,
                                              image_mime=mime_type)
    except ValueError as e:
        flash(f"Tidak bisa upload bukti: {e}", "error")
        return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))

    try:
        import owner_notifications
        owner_notifications.notify_payment_proof_uploaded(
            payment["id"], invoice_id, business["id"] if business else None,
            business["business_name"] if business else None, invoice["amount"],
        )
    except Exception:
        pass

    flash("Bukti pembayaran terkirim. Tim Kilas Works akan verifikasi.", "success")
    return redirect(url_for("payments.invoice_page", invoice_id=invoice_id))


@payments_bp.route("/invoices/<int:invoice_id>/proof")
@security.login_required
def invoice_proof_view(invoice_id):
    """Final Operations Polish, Section 11: customer can see (open) their own uploaded proof —
    tenant-scoped through require_business_access exactly like invoice_page above when a business
    exists, or owner-based access (require_project_access, via the invoice's project) when it
    doesn't — streamed by id from project_files, never a raw storage path."""
    user = security.current_user()
    invoice = payment_service.get_invoice(invoice_id)
    if invoice is None:
        abort(404)
    if invoice["business_id"]:
        security.require_business_access(invoice["business_id"], user)
    else:
        project = projects_repo.get_project(invoice["project_id"])
        security.require_project_access(project["id"], user) if project else abort(404)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    if payment is None or not payment.get("proof_file_id"):
        abort(404)
    # Access to this exact invoice/payment was already verified above (business membership or
    # project ownership) — the file lookup itself matches by id + invoice's project_id, never a
    # bare business_id equality, so it works identically whether business_id is set or NULL.
    row = db.query_one(
        "SELECT * FROM project_files WHERE id = ? AND project_id = ?",
        (payment["proof_file_id"], invoice["project_id"]),
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
