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
    search = (request.args.get("q") or "").strip()
    needle = search.casefold()
    talents = talent_service.list_active_talents()
    if needle:
        talents = [
            t for t in talents
            if needle in str(t.get("name") or "").casefold()
            or needle in str(t.get("social_handle") or "").casefold()
            or needle in str(t.get("platform") or "").casefold()
            or needle in str(t.get("niche") or "").casefold()
            or needle in str(t.get("availability_status") or "").casefold()
            or needle in str(t.get("availability_note") or "").casefold()
        ]

    talents_total = len(talents)
    per_page = 10
    total_pages = max(1, (talents_total + per_page - 1) // per_page)
    page = request.args.get("page", 1, type=int) or 1
    page = min(max(1, page), total_pages)
    start = (page - 1) * per_page
    talents = talents[start:start + per_page]

    businesses = repo.list_businesses_for_user(user["id"]) if user["role"] != "KILAS_ADMIN" else []
    return render_template(
        "talent_list.html", talents=talents, talents_total=talents_total, search=search,
        page=page, total_pages=total_pages, disclaimer=talent_service.PUBLIC_DISCLAIMER,
        businesses=businesses,
    )


@talent_bp.route("/business/<int:business_id>/talent/<int:talent_id>/request", methods=["GET", "POST"])
@security.login_required
def request_talent(business_id, talent_id):
    return _request_talent_impl(talent_id, business_id=business_id)


@talent_bp.route("/talent/<int:talent_id>/request", methods=["GET", "POST"])
@security.login_required
def request_talent_no_business(talent_id):
    """Purchase-flow correction: Talent is a CUSTOM_QUOTE service and must work end-to-end without
    ever requiring a business — a true parallel route (not a business_id=0 sentinel that
    resolves/creates one), sharing the exact same implementation as the business-scoped route
    above via _request_talent_impl()."""
    return _request_talent_impl(talent_id, business_id=None)


def _request_talent_impl(talent_id, business_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user) if business_id else None
    talent = talent_service.get_talent(talent_id)
    if talent is None or not talent["is_active"]:
        abort(404)

    if request.method == "GET":
        return render_template("talent_request_form.html", business=business, talent=talent, values={})

    form = request.form
    fields = {
        "campaign_type": (form.get("campaign_type") or "").strip(), "platform": (form.get("platform") or "").strip(),
        "deliverables": (form.get("deliverables") or "").strip(), "num_content_pieces": form.get("num_content_pieces", type=int),
        "posting_requirements": (form.get("posting_requirements") or "").strip(), "target_date": (form.get("target_date") or "").strip(),
        "location": (form.get("location") or "").strip(), "usage_purpose": (form.get("usage_purpose") or "").strip(),
        "budget": form.get("budget", type=int), "brief": (form.get("brief") or "").strip(),
    }
    if any(not fields[key] for key in ("campaign_type", "platform", "deliverables", "brief")):
        flash("Lengkapi jenis campaign, platform, kebutuhan dari talent, dan brief campaign.", "error")
        return render_template("talent_request_form.html", business=business, talent=talent, values=fields), 400
    request_id, project_id = talent_service.create_talent_request(
        talent_id, business["id"] if business else None, fields, user["id"],
    )
    flash(f"Permintaan talent {talent['name']} terkirim. Tim Kilas Works akan follow up.", "success")
    if business:
        return redirect(url_for("projects.project_detail", business_id=business["id"], project_id=project_id))
    return redirect(url_for("projects.project_view", project_id=project_id))
