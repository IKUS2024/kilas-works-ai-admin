"""Talent Management — customer-facing browse + request flow. Business Hub V2, Phase D (Section 15).
Admin editing lives in routes_admin.py.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort

import security
import repo
import talent_service

talent_bp = Blueprint("talent", __name__)


@talent_bp.route("/talent")
@security.login_required
def talent_list():
    user = security.current_user()
    talents = talent_service.list_active_talents()
    businesses = repo.list_businesses_for_user(user["id"]) if user["role"] != "KILAS_ADMIN" else []
    return render_template("talent_list.html", talents=talents, disclaimer=talent_service.PUBLIC_DISCLAIMER,
                            businesses=businesses)


@talent_bp.route("/business/<int:business_id>/talent/<int:talent_id>/request", methods=["GET", "POST"])
@security.login_required
def request_talent(business_id, talent_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    talent = talent_service.get_talent(talent_id)
    if talent is None or not talent["is_active"]:
        abort(404)

    if request.method == "GET":
        return render_template("talent_request_form.html", business=business, talent=talent)

    form = request.form
    fields = {
        "campaign_type": form.get("campaign_type"), "platform": form.get("platform"),
        "deliverables": form.get("deliverables"), "num_content_pieces": form.get("num_content_pieces", type=int),
        "posting_requirements": form.get("posting_requirements"), "target_date": form.get("target_date"),
        "location": form.get("location"), "usage_purpose": form.get("usage_purpose"),
        "budget": form.get("budget", type=int), "brief": form.get("brief"),
    }
    request_id, project_id = talent_service.create_talent_request(talent_id, business["id"], fields, user["id"])
    flash(f"Permintaan talent {talent['name']} terkirim. Tim Kilas Works akan follow up.", "success")
    return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))
