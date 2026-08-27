import uuid

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, abort, send_file, jsonify
)
import io

import ai_onboarding
import file_utils
import repo
import security
import provisioning

client_bp = Blueprint("client", __name__, url_prefix="")

WIZARD_STEPS = ["basics", "services", "operations", "faq", "style", "upload"]
REQUIRED_STEPS_FOR_AI_SETUP = ["basics", "services", "operations", "faq", "style"]


def _business_or_404(business_id):
    user = security.current_user()
    return security.require_business_access(business_id, user=user)


@client_bp.route("/dashboard")
@security.login_required
def dashboard():
    user = security.current_user()
    businesses = repo.list_businesses_for_user(user["id"])
    enriched = []
    for b in businesses:
        enriched.append({
            **b,
            "completion_percent": repo.onboarding_completion_percent(b["id"]),
            "onboarding_status": repo.get_onboarding_status(b["id"]),
        })
    return render_template("client_dashboard.html", user=user, businesses=enriched)


@client_bp.route("/business/create", methods=["POST"])
@security.login_required
def create_business():
    user = security.current_user()
    name = (request.form.get("business_name") or "").strip()
    package = request.form.get("package") or "AI_ADMIN_BASIC"
    if package not in ("AI_ADMIN_BASIC", "AI_ADMIN_PRO"):
        package = "AI_ADMIN_BASIC"
    if not name:
        flash("Nama bisnis wajib diisi.", "error")
        return redirect(url_for("client.dashboard"))
    business_id = repo.create_business(user["id"], name, package=package)
    return redirect(url_for("client.wizard_step", business_id=business_id, step="basics"))


@client_bp.route("/business/<int:business_id>/wizard/<step>", methods=["GET", "POST"])
@security.login_required
def wizard_step(business_id, step):
    business = _business_or_404(business_id)
    if step not in WIZARD_STEPS:
        abort(404)
    if business["status"] in ("APPROVED", "ACTIVE", "SUSPENDED"):
        flash("Bisnis ini sudah melewati tahap onboarding — hubungi Kilas Works kalau perlu perubahan.", "error")
        return redirect(url_for("client.dashboard"))

    profile = repo.get_business_profile(business_id) or {}
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)

    if request.method == "GET":
        return render_template(
            "wizard.html", business=business, step=step, steps=WIZARD_STEPS, profile=profile,
            services=services, faqs=faqs, files=repo.list_business_files(business_id),
        )

    user = security.current_user()

    if step == "basics":
        raw = {
            "business_name": request.form.get("business_name", ""),
            "category": request.form.get("category", ""),
            "short_description": request.form.get("short_description", ""),
            "country": request.form.get("country", ""),
            "timezone": request.form.get("timezone", ""),
            "address": request.form.get("address", ""),
            "business_phone": request.form.get("business_phone", ""),
            "owner_name": request.form.get("owner_name", ""),
        }
        repo.save_onboarding_session(business_id, "basics", raw, user["id"])
        if raw["business_name"].strip():
            import db
            db.execute("UPDATE businesses SET business_name = ? WHERE id = ?", (raw["business_name"].strip(), business_id))
        repo.upsert_business_profile(business_id, raw)
        repo.mark_onboarding_step_done(business_id, "basics_done")

    elif step == "services":
        raw_text = request.form.get("services_raw", "")
        raw_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        repo.save_onboarding_session(business_id, "services", {"raw_lines": raw_lines}, user["id"])
        repo.replace_business_services(business_id, raw_lines)
        repo.mark_onboarding_step_done(business_id, "services_done")

    elif step == "operations":
        raw = {
            "operating_hours": request.form.get("operating_hours", ""),
            "closed_days": request.form.get("closed_days", ""),
            "online_or_offline": request.form.get("online_or_offline", ""),
            "appointment_rules_raw": request.form.get("appointment_rules_raw", ""),
        }
        repo.save_onboarding_session(business_id, "operations", raw, user["id"])
        repo.upsert_business_profile(business_id, {**profile, **raw})
        repo.mark_onboarding_step_done(business_id, "operations_done")

    elif step == "faq":
        raw_text = request.form.get("faq_raw", "")
        raw_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        repo.save_onboarding_session(business_id, "faq", {"raw_lines": raw_lines}, user["id"])
        repo.replace_business_faqs(business_id, raw_lines)
        repo.mark_onboarding_step_done(business_id, "faq_done")

    elif step == "style":
        additional = request.form.getlist("additional_languages")
        raw = {
            "tone": request.form.get("tone", "friendly"),
            "primary_language": request.form.get("primary_language", "id"),
            "additional_languages": additional,
            "customer_salutation": request.form.get("customer_salutation", "Kak"),
        }
        repo.save_onboarding_session(business_id, "style", raw, user["id"])
        repo.upsert_business_profile(business_id, {**profile, **raw})
        repo.mark_onboarding_step_done(business_id, "style_done")

    elif step == "upload":
        repo.mark_onboarding_step_done(business_id, "upload_done")

    if business["status"] == "DRAFT":
        repo.set_business_status(business_id, "ONBOARDING", user["id"], "client started onboarding")

    next_idx = WIZARD_STEPS.index(step) + 1
    if next_idx < len(WIZARD_STEPS):
        return redirect(url_for("client.wizard_step", business_id=business_id, step=WIZARD_STEPS[next_idx]))
    return redirect(url_for("client.review_page", business_id=business_id))


@client_bp.route("/business/<int:business_id>/files/upload", methods=["POST"])
@security.login_required
def upload_file(business_id):
    business = _business_or_404(business_id)
    user = security.current_user()
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Pilih file dulu.", "error")
        return redirect(url_for("client.wizard_step", business_id=business_id, step="upload"))

    content = f.read()
    try:
        safe_name, mime_type, extracted_text = file_utils.validate_and_extract(f.filename, content, f.mimetype)
    except file_utils.UploadRejected as e:
        flash(str(e), "error")
        return redirect(url_for("client.wizard_step", business_id=business_id, step="upload"))

    repo.save_business_file(business_id, safe_name, mime_type, len(content), content, extracted_text, user["id"])
    repo.write_audit(user["id"], business_id, "file_uploaded", safe_name)
    flash(f"File '{safe_name}' berhasil diupload.", "success")
    return redirect(url_for("client.wizard_step", business_id=business_id, step="upload"))


@client_bp.route("/business/<int:business_id>/files/<int:file_id>/download")
@security.login_required
def download_file(business_id, file_id):
    _business_or_404(business_id)
    row = repo.get_business_file_content(file_id, business_id)
    if not row:
        abort(404)
    return send_file(
        io.BytesIO(row["content"]), mimetype=row["mime_type"],
        as_attachment=True, download_name=row["original_filename"],
    )


@client_bp.route("/business/<int:business_id>/ai-setup/run", methods=["POST"])
@security.login_required
def run_ai_setup(business_id):
    business = _business_or_404(business_id)
    user = security.current_user()
    status = repo.get_onboarding_status(business_id)
    missing_steps = [s for s in REQUIRED_STEPS_FOR_AI_SETUP if not status.get(f"{s}_done")]
    if missing_steps:
        flash(f"Lengkapi dulu step: {', '.join(missing_steps)}.", "error")
        return redirect(url_for("client.review_page", business_id=business_id))

    repo.set_business_status(business_id, "READY_FOR_AI_SETUP", user["id"], "client triggered AI setup")
    repo.set_ai_status(business_id, "RUNNING")

    profile = repo.get_business_profile(business_id)
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)
    files = repo.list_business_files(business_id)
    extracted_texts = []
    for fmeta in files:
        full = repo.get_business_file_content(fmeta["id"], business_id)
        if full and full.get("extracted_text"):
            extracted_texts.append((full["original_filename"], full["extracted_text"]))

    config, error = ai_onboarding.normalize_business_data(
        business, profile, [s["raw_input"] for s in services], [f["raw_input"] for f in faqs], extracted_texts,
    )

    if error:
        repo.set_ai_status(business_id, "FAILED", error)
        repo.write_audit(user["id"], business_id, "ai_normalization_failed", error)
        flash("AI setup gagal diproses saat ini. Data kamu AMAN dan tersimpan — coba klik 'Jalankan AI Setup' lagi.", "error")
        return redirect(url_for("client.review_page", business_id=business_id))

    for svc_row, ai_svc in zip(services, config.get("services", [])):
        repo.update_normalized_service(
            svc_row["id"], ai_svc.get("service_name"), ai_svc.get("description"),
            ai_svc.get("price_from"), ai_svc.get("price_to"), ai_svc.get("currency") or "IDR",
            ai_svc.get("needs_review", True),
        )
    for faq_row, ai_faq in zip(faqs, config.get("faqs", [])):
        repo.update_normalized_faq(
            faq_row["id"], ai_faq.get("question"), ai_faq.get("answer"),
            ai_faq.get("category") or "general", ai_faq.get("needs_review", True),
        )

    repo.save_ai_normalized_config(business_id, config.get("description"), config, config.get("missing_fields", []))
    repo.set_business_status(business_id, "READY_FOR_REVIEW", user["id"], "AI normalization completed")
    repo.write_audit(user["id"], business_id, "ai_normalization_run", "success")
    flash("AI setup selesai! Cek hasilnya di bawah sebelum submit ke Kilas Works.", "success")
    return redirect(url_for("client.review_page", business_id=business_id))


@client_bp.route("/business/<int:business_id>/review")
@security.login_required
def review_page(business_id):
    business = _business_or_404(business_id)
    ai_settings = repo.get_ai_settings(business_id)
    return render_template(
        "review.html", business=business, profile=repo.get_business_profile(business_id),
        services=repo.get_business_services(business_id), faqs=repo.get_business_faqs(business_id),
        files=repo.list_business_files(business_id), ai_settings=ai_settings,
        onboarding_status=repo.get_onboarding_status(business_id),
        missing_required=repo.required_fields_missing(business_id),
        is_admin_view=False,
    )


@client_bp.route("/business/<int:business_id>/submit-for-review", methods=["POST"])
@security.login_required
def submit_for_review(business_id):
    business = _business_or_404(business_id)
    user = security.current_user()
    ai_settings = repo.get_ai_settings(business_id)
    if not ai_settings or ai_settings.get("ai_status") != "DONE":
        flash("Jalankan AI Setup dulu sebelum submit ke Kilas Works.", "error")
        return redirect(url_for("client.review_page", business_id=business_id))
    missing = repo.required_fields_missing(business_id)
    if missing:
        flash(f"Lengkapi dulu data wajib: {', '.join(missing)}.", "error")
        return redirect(url_for("client.review_page", business_id=business_id))

    repo.mark_onboarding_step_done(business_id, "reviewed_done")
    repo.set_business_status(business_id, "READY_FOR_REVIEW", user["id"], "client submitted for Kilas review")
    repo.write_audit(user["id"], business_id, "submitted_for_review", None)
    provisioning.record_business_submitted(business_id, user["id"])
    flash("Terkirim! Tim Kilas Works akan review setup AI Admin kamu.", "success")
    return redirect(url_for("client.dashboard"))


@client_bp.route("/business/<int:business_id>/simulate")
@security.login_required
def simulate_page(business_id):
    business = _business_or_404(business_id)
    token = session.get(f"sim_token_{business_id}")
    if not token:
        token = uuid.uuid4().hex
        session[f"sim_token_{business_id}"] = token
    history = repo.get_simulation_history(business_id, token)
    return render_template("simulate.html", business=business, history=history, is_admin_view=False)


@client_bp.route("/business/<int:business_id>/simulate/message", methods=["POST"])
@security.login_required
def simulate_message(business_id):
    business = _business_or_404(business_id)
    token = session.get(f"sim_token_{business_id}")
    if not token:
        return jsonify({"error": "no_session"}), 400

    user_message = (request.json or {}).get("message", "").strip()
    if not user_message:
        return jsonify({"error": "empty_message"}), 400

    ai_settings = repo.get_ai_settings(business_id)
    config = ai_settings.get("normalized_config") if ai_settings else None

    history_rows = repo.get_simulation_history(business_id, token, limit=20)
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    reply, error = ai_onboarding.simulate_customer_reply(business, config, history, user_message)
    repo.save_simulation_message(business_id, token, "user", user_message)
    if error:
        reply = "(Simulasi gagal memproses pesan ini — coba lagi. Detail teknis dicatat untuk Kilas Works.)"
        repo.write_audit(security.current_user()["id"], business_id, "simulation_error", error)
    repo.save_simulation_message(business_id, token, "assistant", reply)
    repo.mark_onboarding_step_done(business_id, "simulated_done")

    latest = repo.get_simulation_history(business_id, token, limit=1)
    return jsonify({"reply": reply, "message_id": latest[0]["id"] if latest else None})


@client_bp.route("/business/<int:business_id>/simulate/flag", methods=["POST"])
@security.login_required
def simulate_flag(business_id):
    _business_or_404(business_id)
    data = request.json or {}
    message_id = data.get("message_id")
    note = (data.get("note") or "").strip()
    if not message_id:
        return jsonify({"error": "missing message_id"}), 400
    repo.flag_simulation_message(int(message_id), business_id, note)
    return jsonify({"status": "ok"})
