"""Quotation viewing + customer approve/reject — Business Hub V2, Phase C (Section 11).

Admin-side quotation CREATION lives in routes_admin.py (admin-only action, alongside project
review) — this blueprint is the customer-facing view + approve/reject actions.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

import security
import quotation_service

quotations_bp = Blueprint("quotations", __name__)


@quotations_bp.route("/business/<int:business_id>/quotations/<int:quotation_id>")
@security.login_required
def quotation_detail(business_id, quotation_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    quotation = quotation_service.get_quotation(quotation_id)
    if quotation is None or quotation["business_id"] != business["id"]:
        abort(404)
    if user["role"] != "KILAS_ADMIN":
        quotation_service.mark_viewed(quotation_id)
        quotation = quotation_service.get_quotation(quotation_id)  # re-fetch post-view-mark
    return render_template("quotation_detail.html", business=business, quotation=quotation)


@quotations_bp.route("/business/<int:business_id>/quotations/<int:quotation_id>/approve", methods=["POST"])
@security.login_required
def approve_quotation(business_id, quotation_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    try:
        quotation_service.approve_quotation(quotation_id, business["id"], user["id"])
    except ValueError as e:
        flash(f"Tidak bisa approve: {e}", "error")
        return redirect(url_for("quotations.quotation_detail", business_id=business_id, quotation_id=quotation_id))
    flash("Quotation disetujui. Checkout sekarang tersedia.", "success")
    return redirect(url_for("quotations.quotation_detail", business_id=business_id, quotation_id=quotation_id))


@quotations_bp.route("/business/<int:business_id>/quotations/<int:quotation_id>/reject", methods=["POST"])
@security.login_required
def reject_quotation(business_id, quotation_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    note = (request.form.get("note") or "").strip() or None
    try:
        quotation_service.reject_quotation(quotation_id, business["id"], user["id"], note)
    except ValueError as e:
        flash(f"Tidak bisa menolak: {e}", "error")
        return redirect(url_for("quotations.quotation_detail", business_id=business_id, quotation_id=quotation_id))
    flash("Quotation ditolak / diminta revisi. Tim Kilas Works akan menghubungi.", "success")
    return redirect(url_for("quotations.quotation_detail", business_id=business_id, quotation_id=quotation_id))
