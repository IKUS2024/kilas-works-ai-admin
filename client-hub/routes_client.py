import uuid
import traceback

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, abort, send_file, jsonify
)
import io

import ai_onboarding
import file_utils
import repo
import security
import provisioning
import projects_repo
import quotation_service
import feature_flags
import subscription_service
import inbox_service
import wa_takeover_service
import catalog_service
import db
import payment_service
import display_labels

client_bp = Blueprint("client", __name__, url_prefix="")

WIZARD_STEPS = ["basics", "services", "operations", "faq", "style", "upload"]
REQUIRED_STEPS_FOR_AI_SETUP = ["basics", "services", "operations", "faq", "style"]


def _business_or_404(business_id):
    user = security.current_user()
    return security.require_business_access(business_id, user=user)


_REQUIRED_FIELD_LABELS = {
    "business_name": "Nama bisnis",
    "owner_name": "Nama owner",
    "category": "Kategori bisnis",
    "primary_language": "Bahasa utama",
    "customer_salutation": "Sapaan customer",
    "core_product_or_service": "Produk / layanan utama",
}


def _step_for_missing_fields(missing):
    missing = set(missing or [])
    if missing & {"business_name", "owner_name", "category"}:
        return "basics"
    if "core_product_or_service" in missing:
        return "services"
    if missing & {"primary_language", "customer_salutation"}:
        return "style"
    return "basics"


def _merge_profile_patch(existing_profile, new_raw_fields):
    """Empty-value overwrite protection (Section G, real production incident: "customer sometimes
    fills fields and later sees them empty"). Root cause traced to source: every wizard step's
    <input> IS correctly bound to its saved value on page load (verified — no template prefill
    bug), so the actual mechanism is a SAVE-time one — a step's own form ALWAYS submits every one
    of its fields, even ones the browser happens to show blank on a stale/cached re-render (back
    button, autofill quirks, etc.). The previous `{**profile, **raw}` merge only protected fields
    from OTHER steps (missing from `raw` entirely) — repo.upsert_business_profile() already treats
    an absent key as "don't touch". It never protected THIS step's OWN fields: if `raw["owner_name"]`
    came back as "" while `profile["owner_name"]` already held a real value, the blank would
    unconditionally win and silently erase previously-good data.

    This applies PATCH semantics one level deeper: for each key in `new_raw_fields`, a
    falsy/blank new value NEVER overwrites an existing non-blank value for that same key — the
    existing value is kept. A non-blank new value always wins (a real edit/correction always
    applies). This intentionally means a field, once given a real value through this wizard,
    cannot be blanked back out through it — there is no legitimate business reason for a
    completed onboarding field (owner name, hours, address, ...) to need to become blank again,
    and protecting against silent data loss is the higher-value default. `False`/`0`/empty-list
    are treated as legitimate explicit values, not blanks — only `None` and `""` (after
    stripping whitespace for strings) count as "blank"."""
    existing_profile = existing_profile or {}
    merged = dict(existing_profile)
    for key, new_value in new_raw_fields.items():
        is_blank = new_value is None or (isinstance(new_value, str) and not new_value.strip())
        existing_value = existing_profile.get(key)
        existing_is_blank = existing_value is None or (isinstance(existing_value, str) and not existing_value.strip())
        if is_blank and not existing_is_blank:
            continue  # keep the existing non-blank value — do not overwrite with blank
        merged[key] = new_value
    return merged


def _human_missing_labels(missing):
    return [_REQUIRED_FIELD_LABELS.get(field, field) for field in (missing or [])]


@client_bp.route("/dashboard")
@security.login_required
def dashboard():
    user = security.current_user()
    businesses = repo.list_businesses_for_user(user["id"])
    enriched = []
    my_projects = []
    for b in businesses:
        enriched.append({
            **b,
            "completion_percent": repo.onboarding_completion_percent(b["id"]),
            "onboarding_status": repo.get_onboarding_status(b["id"]),
            # Gap-fix Area E — owner-facing subscription banner (renewal-due/GRACE/SUSPENDED),
            # this business's OWN AI Admin subscription only. None when there's no subscription
            # row yet (e.g. this business was never activated with an AI Admin package).
            "subscription_banner": subscription_service.get_subscription_banner(b["id"]),
        })
        # Business Hub V2, Phase E (Section 19): surface this customer's own projects/quotations
        # across every business they own, so "what's happening with my order" doesn't require
        # digging through each business separately.
        for p in projects_repo.list_projects_for_business(b["id"]):
            if p["status"] in ("COMPLETED", "CANCELLED"):
                continue
            latest_quote = quotation_service.get_latest_quotation_for_project(p["id"])
            # Section 1 of the payment-verification-strengthening request: project status and
            # payment status are genuinely different things (a project can be "Disetujui" while
            # payment is still pending) — never let one imply the other on this dashboard.
            invoice, payment = payment_service.get_latest_payment_for_project(p["id"])
            payment_review_status = payment_service.derive_review_status(payment) if payment else None
            my_projects.append({
                **p,
                "business_name": b["business_name"],
                "latest_quotation": latest_quote,
                "invoice": invoice,
                "payment": payment,
                "payment_review_status": payment_review_status,
            })
    return render_template(
        "client_dashboard.html", user=user, businesses=enriched, my_projects=my_projects
    )


@client_bp.route("/business/create", methods=["POST"])
@security.login_required
def create_business():
    """Ecosystem Sync Section 2 (priority gap): registration/business-creation must NOT force an
    AI Admin package pick. The form defaults to 'NONE' (no AI Admin yet) — a customer who picks
    that lands straight on the dashboard and can browse/buy any other Kilas Works service. Only a
    customer who actively selects AI Admin Basic/Pro here goes through the onboarding wizard."""
    user = security.current_user()
    name = (request.form.get("business_name") or "").strip()
    package = request.form.get("package") or "NONE"
    if not feature_flags.is_valid_package(package):
        package = "NONE"
    if not name:
        flash("Nama bisnis wajib diisi.", "error")
        return redirect(url_for("client.dashboard"))
    business_id = repo.create_business(user["id"], name, package=package)
    if package == "NONE":
        flash(f"Business \"{name}\" dibuat. Silakan pilih layanan Kilas Works yang kamu butuhkan.", "success")
        return redirect(url_for("client.dashboard"))
    return redirect(url_for("client.wizard_step", business_id=business_id, step="basics"))


@client_bp.route("/business/<int:business_id>/upgrade-ai-admin", methods=["POST"])
@security.login_required
def upgrade_to_ai_admin(business_id):
    """Ecosystem Sync Section 2: the explicit, simple 'upgrade' action for a business created
    without AI Admin. Only reachable for a business currently on package='NONE' — an existing AI
    Admin business is never re-routed through this."""
    user = security.current_user()
    business = _business_or_404(business_id)
    if business["package"] != "NONE":
        flash("Business ini sudah punya paket AI Admin.", "error")
        return redirect(url_for("client.dashboard"))
    package = request.form.get("package") or "AI_ADMIN_BASIC"
    if package not in ("AI_ADMIN_BASIC", "AI_ADMIN_PRO"):
        package = "AI_ADMIN_BASIC"
    repo.upgrade_business_package(business_id, package, user["id"])
    flash("AI Admin ditambahkan. Lanjutkan onboarding di bawah ini.", "success")
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
        print(f"WIZARD_PAGE_START business_id={business_id} step={step}")
        rendered = render_template(
            "wizard.html", business=business, step=step, steps=WIZARD_STEPS, profile=profile,
            services=services, faqs=faqs, files=repo.list_business_files(business_id),
            tenant_features=repo.get_tenant_features(business_id),
        )
        print(f"WIZARD_PAGE_RENDER_OK business_id={business_id} step={step}")
        return rendered

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
        repo.upsert_business_profile(business_id, _merge_profile_patch(profile, raw))
        missing_here = [
            label for key, label in (("business_name", "Nama bisnis"), ("category", "Kategori bisnis"), ("owner_name", "Nama owner"))
            if not (raw.get(key) or "").strip()
        ]
        if missing_here:
            flash("Lengkapi dulu: " + ", ".join(missing_here) + ".", "error")
            return redirect(url_for("client.wizard_step", business_id=business_id, step="basics"))
        repo.mark_onboarding_step_done(business_id, "basics_done")

    elif step == "services":
        raw_text = request.form.get("services_raw", "")
        raw_lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
        repo.save_onboarding_session(business_id, "services", {"raw_lines": raw_lines}, user["id"])
        repo.replace_business_services(business_id, raw_lines)
        if not raw_lines:
            flash("Isi minimal 1 produk atau layanan utama sebelum lanjut.", "error")
            return redirect(url_for("client.wizard_step", business_id=business_id, step="services"))
        repo.mark_onboarding_step_done(business_id, "services_done")

    elif step == "operations":
        print(f"PAYMENT_POST_START business_id={business_id}")
        print(f"PAYMENT_BUSINESS_OK business_id={business_id} status={business['status']}")
        raw = {
            "operating_hours": request.form.get("operating_hours", ""),
            "closed_days": request.form.get("closed_days", ""),
            "online_or_offline": request.form.get("online_or_offline", ""),
            "appointment_rules_raw": request.form.get("appointment_rules_raw", ""),
            # Pro tenant parity cycle (Tasks 3/4/5) — this tenant's OWN appointment toggle and OWN
            # payment/bank details for ITS OWN customers, never Kilas Works' own BCA account.
            "appointment_enabled": bool(request.form.get("appointment_enabled")),
            "payment_bank_name": request.form.get("payment_bank_name", ""),
            "payment_account_number": request.form.get("payment_account_number", ""),
            "payment_account_name": request.form.get("payment_account_name", ""),
            "payment_instructions": request.form.get("payment_instructions", ""),
        }
        # White-screen bug investigation — defensive error handling. A save failure here (e.g. a
        # production database that's missing a migration-added column, or any other unexpected
        # DB/driver error) must NEVER surface to the client as an unhandled 500/blank response.
        # db.execute() (see db.py) already rolls back the transaction internally on any exception
        # before re-raising, so it's always safe to catch here — this never leaves a half-written
        # row or a poisoned connection behind.
        #
        # LOGGING SAFETY: only business_id, step name, and (on failure) the exception TYPE/message
        # and a full server-side traceback are logged. The traceback can legitimately contain a
        # SQL error message (e.g. "column \"appointment_enabled\" of relation \"business_profiles\"
        # does not exist") but NEVER the payment field VALUES themselves (account number, account
        # holder name, payment instructions) — `raw`/`profile` dicts are never passed to a logging
        # call, only used as function arguments to the repo layer.
        try:
            print(f"PAYMENT_SAVE_START business_id={business_id}")
            repo.save_onboarding_session(business_id, "operations", raw, user["id"])
            repo.upsert_business_profile(business_id, _merge_profile_patch(profile, raw))
            # Owner/pengelola phone (Section I/J/K) — only meaningful (and only shown in the
            # template) for a package with owner_commands enabled; the form field itself is
            # absent from the template otherwise, so request.form.get() returning None/"" here for
            # a Basic tenant is expected and correctly results in set_trusted_owner_phone() being
            # a no-op (patch semantics — never overwrites with blank).
            if request.form.get("trusted_owner_phone"):
                repo.set_trusted_owner_phone(business_id, request.form.get("trusted_owner_phone"))
            # db.execute() commits internally on success (see db.py's execute()) — reaching this
            # line without an exception means the write already committed, so SAVE_OK and
            # COMMIT_OK are logged together rather than as two separately-timed checkpoints.
            print(f"PAYMENT_SAVE_OK business_id={business_id}")
            print(f"PAYMENT_COMMIT_OK business_id={business_id}")
        except Exception as e:
            print(f"PAYMENT_SAVE_FAILED business_id={business_id} error_type={type(e).__name__}: {e}")
            traceback.print_exc()
            flash("Data belum berhasil disimpan. Silakan coba lagi.", "error")
            return redirect(url_for("client.wizard_step", business_id=business_id, step="operations"))
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
        repo.upsert_business_profile(business_id, _merge_profile_patch(profile, raw))
        missing_here = []
        if raw["primary_language"] not in ("id", "en"):
            missing_here.append("Bahasa utama")
        if not (raw["customer_salutation"] or "").strip():
            missing_here.append("Sapaan customer")
        if missing_here:
            flash("Lengkapi dulu: " + ", ".join(missing_here) + ".", "error")
            return redirect(url_for("client.wizard_step", business_id=business_id, step="style"))
        repo.mark_onboarding_step_done(business_id, "style_done")

    elif step == "upload":
        repo.mark_onboarding_step_done(business_id, "upload_done")

    if business["status"] == "DRAFT":
        repo.set_business_status(business_id, "ONBOARDING", user["id"], "client started onboarding")

    # Stale-knowledge protection (Section I): if generated AI knowledge already exists (ai_status
    # DONE) and the client just edited ANY onboarding data, that knowledge no longer reflects what
    # was just saved — silently continuing to use it would risk stale info reaching customers.
    # Mark it STALE (reusing the existing ai_status TEXT column, no migration needed — see
    # repo.set_business_stale_if_done()'s own docstring) rather than leaving it DONE; the review
    # page/admin flow can prompt a rerun before this business moves forward.
    repo.set_business_stale_if_done(business_id)

    next_idx = WIZARD_STEPS.index(step) + 1
    if next_idx < len(WIZARD_STEPS):
        next_step = WIZARD_STEPS[next_idx]
        if step == "operations":
            print(f"PAYMENT_REDIRECT business_id={business_id} next_step={next_step}")
        return redirect(url_for("client.wizard_step", business_id=business_id, step=next_step))
    if step == "operations":
        print(f"PAYMENT_REDIRECT business_id={business_id} next_step=review")
    return redirect(url_for("client.review_page", business_id=business_id))


@client_bp.route("/business/<int:business_id>/settings", methods=["GET", "POST"])
@security.login_required
def business_settings(business_id):
    """Pro tenant parity cycle (Task 5) — appointment & payment settings, editable by the business
    owner themselves at ANY status (unlike the onboarding wizard, which locks once APPROVED/ACTIVE/
    SUSPENDED — see wizard_step's own comment) since these are ongoing operational settings a
    business needs to be able to change on its own, without engineering help, even after go-live.
    tenant_config_service.get_tenant_appointment_settings()/get_tenant_payment_config() read
    business_profiles LIVE (not the versioned, KILAS_ADMIN-only tenant_config snapshot), so this
    save takes effect on the bot's very next customer message with no re-provisioning step and no
    admin action needed."""
    business = _business_or_404(business_id)
    profile = repo.get_business_profile(business_id) or {}

    if request.method == "GET":
        return render_template("business_settings.html", business=business, profile=profile)

    user = security.current_user()
    raw = {
        "appointment_enabled": bool(request.form.get("appointment_enabled")),
        "operating_hours": request.form.get("operating_hours", profile.get("operating_hours") or ""),
        "closed_days": request.form.get("closed_days", profile.get("closed_days") or ""),
        "appointment_rules_raw": request.form.get("appointment_rules_raw", ""),
        "payment_bank_name": request.form.get("payment_bank_name", ""),
        "payment_account_number": request.form.get("payment_account_number", ""),
        "payment_account_name": request.form.get("payment_account_name", ""),
        "payment_instructions": request.form.get("payment_instructions", ""),
    }
    repo.upsert_business_profile(business_id, _merge_profile_patch(profile, raw))
    repo.write_audit(user["id"], business_id, "settings_updated", "appointment/payment settings diubah oleh owner")

    flash("Pengaturan appointment & pembayaran berhasil disimpan.", "success")
    return redirect(url_for("client.business_settings", business_id=business_id))


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


def _run_ai_normalization(business_id, business, user):
    """Shared normalization core — Gap-fix Area D. Used by BOTH the manual 'Jalankan (Ulang) AI
    Setup' button (unchanged, still available for re-runs/admin retries) AND the automatic
    normalization a normal client Submit now triggers on its own (see submit_for_review() below).

    Returns (ok: bool, error: str|None). On failure, the client's RAW onboarding data (profile,
    services, faqs, uploaded files) is left completely untouched — only ai_settings.ai_status/
    last_error changes — so a retry (clicking Submit again, or the manual button) is always safe
    and never re-asks the client to re-enter anything. Never invents/guesses a missing business
    fact — ai_onboarding.normalize_business_data() itself only reorganizes what the client actually
    provided (see that module for the "never invent" contract) and features_enabled always comes
    from repo.get_tenant_features(), never the model's own output."""
    repo.set_business_status(business_id, "READY_FOR_AI_SETUP", user["id"], "AI normalization triggered")
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

    # Production bug fix (AI_RESPONSE_SHAPE_INVALID: missing keys ['features_enabled']):
    # features_enabled must reflect this tenant's REAL package entitlement, never the model's own
    # guess — see ai_onboarding._normalize_features_enabled() for why.
    tenant_features = repo.get_tenant_features(business_id)
    config, error = ai_onboarding.normalize_business_data(
        business, profile, [s["raw_input"] for s in services], [f["raw_input"] for f in faqs], extracted_texts,
        tenant_features=tenant_features,
    )

    if error:
        repo.set_ai_status(business_id, "FAILED", error)
        repo.write_audit(user["id"], business_id, "ai_normalization_failed", error)
        return False, error

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
    return True, None


@client_bp.route("/business/<int:business_id>/ai-setup/run", methods=["POST"])
@security.login_required
def run_ai_setup(business_id):
    """Manual trigger — UNCHANGED from before Gap-fix Area D, still available for a client who
    wants to re-run normalization by hand (e.g. after editing services/FAQs) without going through
    Submit again."""
    business = _business_or_404(business_id)
    user = security.current_user()
    status = repo.get_onboarding_status(business_id)
    missing_steps = [s for s in REQUIRED_STEPS_FOR_AI_SETUP if not status.get(f"{s}_done")]
    if missing_steps:
        flash(f"Lengkapi dulu step: {', '.join(missing_steps)}.", "error")
        return redirect(url_for("client.review_page", business_id=business_id))

    ok, error = _run_ai_normalization(business_id, business, user)
    if not ok:
        flash("AI setup gagal diproses saat ini. Data kamu AMAN dan tersimpan — coba klik 'Jalankan AI Setup' lagi.", "error")
    else:
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
        missing_required_labels=_human_missing_labels(repo.required_fields_missing(business_id)),
        missing_required_sentence=display_labels.missing_fields_sentence(repo.required_fields_missing(business_id)),
        missing_fix_step=_step_for_missing_fields(repo.required_fields_missing(business_id)),
        is_admin_view=False,
        # Business flow cleanup: lets review.html show whether AI Admin payment is already done
        # (so "Lanjut ke Pembayaran" only appears when it's actually still needed) — same check
        # provisioning.activate_tenant() itself already uses to gate activation, so this is purely
        # a display convenience, never a second source of truth.
        has_ai_admin_payment=(
            business["package"] in ("AI_ADMIN_BASIC", "AI_ADMIN_PRO")
            and payment_service.has_verified_ai_admin_payment(business_id)
        ),
    )


@client_bp.route("/business/<int:business_id>/submit-for-review", methods=["POST"])
@security.login_required
def submit_for_review(business_id):
    """Gap-fix Area D: normal Submit no longer requires a separate manual 'Jalankan AI Setup'
    click first. Flow is now: validate onboarding completeness -> auto-run normalization (if not
    already DONE) -> save structured config -> READY_FOR_REVIEW. If normalization fails, the raw
    onboarding data stays exactly as the client entered it (see _run_ai_normalization()'s
    docstring) and the client gets a safe retry state — nothing is lost, nothing is invented."""
    business = _business_or_404(business_id)
    user = security.current_user()

    status = repo.get_onboarding_status(business_id)
    missing_steps = [s for s in REQUIRED_STEPS_FOR_AI_SETUP if not status.get(f"{s}_done")]
    if missing_steps:
        flash(f"Lengkapi dulu step: {', '.join(missing_steps)}.", "error")
        return redirect(url_for("client.review_page", business_id=business_id))

    # Validate RAW business facts BEFORE spending an AI-normalization call. This prevents the old
    # failure mode where a client could mark a wizard step done with an empty value, run AI setup,
    # then only discover the missing business fact at admin approval time.
    missing = repo.required_fields_missing(business_id)
    if missing:
        labels = _human_missing_labels(missing)
        fix_step = _step_for_missing_fields(missing)
        flash("Belum bisa Submit. Lengkapi dulu: " + ", ".join(labels) + ".", "error")
        return redirect(url_for("client.wizard_step", business_id=business_id, step=fix_step))

    ai_settings = repo.get_ai_settings(business_id)
    if not ai_settings or ai_settings.get("ai_status") != "DONE":
        ok, error = _run_ai_normalization(business_id, business, user)
        if not ok:
            flash(
                "AI setup otomatis gagal diproses saat ini. Data kamu AMAN dan tersimpan — coba "
                "klik Submit lagi dalam beberapa saat.",
                "error",
            )
            return redirect(url_for("client.review_page", business_id=business_id))

    repo.mark_onboarding_step_done(business_id, "reviewed_done")
    repo.set_business_status(business_id, "READY_FOR_REVIEW", user["id"], "client submitted for Kilas review")
    repo.write_audit(user["id"], business_id, "submitted_for_review", None)
    provisioning.record_business_submitted(business_id, user["id"])
    flash(
        "Data bisnis terkirim! Tim Kilas Works akan review setup AI Admin kamu — sekarang lanjut ke "
        "pembayaran ya.",
        "success",
    )
    # Business flow cleanup: Review -> Pembayaran -> Pending verification/activation -> Selesai.
    # AI Admin now has exactly ONE purchase path (this wizard), never the generic /services
    # instant-checkout — see ai_admin_checkout()'s own docstring below for the full rationale.
    return redirect(url_for("client.ai_admin_checkout", business_id=business_id))


@client_bp.route("/business/<int:business_id>/ai-admin/checkout")
@security.login_required
def ai_admin_checkout(business_id):
    """Business flow cleanup (single AI Admin purchase path) — the ONLY route that starts payment
    for an AI Admin business. Reached from the wizard/review flow (submit_for_review()'s own
    redirect, and a "Lanjut ke Pembayaran" link on review.html for anyone revisiting later) —
    NEVER from the generic /services catalog page, which no longer offers instant checkout for the
    AI_ADMIN category (see service_catalog.html + start_fixed_checkout()'s own guard). Before this
    fix, AI Admin could ALSO be bought as a plain FIXED_PRICE catalog item straight from
    /services — completely bypassing the business-info wizard — which is exactly the "two
    different AI Admin products" confusion this closes. This function does not introduce a new
    payment mechanism: it only creates (or reuses) the SAME kind of `projects` row every other
    fixed-price service already uses, then hands off to the SAME shared payments.checkout_page —
    payment verification, proof upload, and admin review are completely unchanged.

    Idempotent: revisiting this route (e.g. the customer navigates away mid-payment and comes back
    via "Lanjut ke Pembayaran" on the review page) reuses the existing AI Admin project for this
    business instead of creating a duplicate one — payment_service.checkout() is itself already
    idempotent per-project (reuses the existing invoice), so this only needs to avoid creating a
    second PROJECT row.
    """
    business = _business_or_404(business_id)
    user = security.current_user()
    catalog_key = {"AI_ADMIN_BASIC": "ai_admin_basic", "AI_ADMIN_PRO": "ai_admin_pro"}.get(business["package"])
    if not catalog_key:
        flash("Business ini belum memilih paket AI Admin.", "error")
        return redirect(url_for("client.dashboard"))

    existing = db.query_one(
        "SELECT id FROM projects WHERE business_id = ? AND catalog_key = ? ORDER BY created_at DESC LIMIT 1",
        (business_id, catalog_key),
    )
    if existing:
        project_id = existing["id"]
    else:
        item = catalog_service.get_catalog_item(catalog_key)
        if item is None:
            flash("Paket AI Admin ini sedang tidak tersedia — hubungi Kilas Works.", "error")
            return redirect(url_for("client.review_page", business_id=business_id))
        project_id = projects_repo.create_fixed_price_project(business_id, item, user["id"])

    return redirect(url_for("payments.checkout_page", project_id=project_id))


@client_bp.route("/business/<int:business_id>/ai-writing-help", methods=["POST"])
@security.login_required
def ai_writing_help(business_id):
    """Reusable "Bantu dengan AI" writing helper (UX pass, Section 2/3) — ONE endpoint used by
    every eligible text field. Returns JSON only (called via fetch() from the wizard's inline JS,
    never a full page load) — the suggestion is shown as a PREVIEW client-side; nothing is ever
    saved to the database from this route. The actual field only changes when the customer clicks
    "Gunakan hasil" and the NORMAL wizard-step form is submitted exactly as before — this route
    has no write path to business_profiles/business_faqs at all.

    field_type is checked against the SAME whitelist ai_onboarding.generate_writing_suggestion()
    itself enforces — checked here too (not just trusting the function) so a malformed/unexpected
    field_type gets a clean 400 before any AI call is even attempted."""
    business = _business_or_404(business_id)
    field_type = (request.form.get("field_type") or "").strip()
    action = (request.form.get("action") or "").strip()
    current_text = request.form.get("current_text") or ""

    if field_type not in ai_onboarding.WRITING_HELPER_FIELD_TYPES:
        return jsonify({"error": "unsupported_field"}), 400
    if action not in ai_onboarding.WRITING_HELPER_ACTIONS:
        return jsonify({"error": "unsupported_action"}), 400

    profile = repo.get_business_profile(business_id)
    services = [s["raw_input"] for s in repo.get_business_services(business_id)]
    faqs = [f["raw_input"] for f in repo.get_business_faqs(business_id)]

    result, error = ai_onboarding.generate_writing_suggestion(
        business, profile, services, faqs, field_type, current_text, action,
    )
    if error:
        print(f"AI writing helper gagal (business_id={business_id}, field={field_type}): {error}")
        return jsonify({"error": "ai_unavailable"}), 502
    return jsonify(result), 200


@client_bp.route("/business/<int:business_id>/ai-faq-suggestions", methods=["POST"])
@security.login_required
def ai_faq_suggestions(business_id):
    """Smart FAQ assistant, missing-topics mode (Section 4/H): analyzes existing business data and
    suggests useful FAQ questions the customer hasn't added yet — each with either a real,
    fact-grounded answer, or an explicit "belum tersedia" marker if the data doesn't support one
    (never fabricated). Returns a LIST of suggestions; the customer picks which ones to add
    client-side — this route never writes any FAQ row itself."""
    business = _business_or_404(business_id)
    profile = repo.get_business_profile(business_id)
    services = [s["raw_input"] for s in repo.get_business_services(business_id)]
    faqs = [f["raw_input"] for f in repo.get_business_faqs(business_id)]

    result, error = ai_onboarding.generate_faq_suggestions(business, profile, services, faqs)
    if error:
        print(f"AI FAQ suggestion gagal (business_id={business_id}): {error}")
        return jsonify({"error": "ai_unavailable"}), 502
    return jsonify(result), 200


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


# ---------------------------------------------------------------------------
# Tenant CS Inbox — owner-facing click-to-takeover/manual reply UI.
# ---------------------------------------------------------------------------

@client_bp.route("/business/<int:business_id>/inbox")
@security.login_required
def inbox_page(business_id):
    business = _business_or_404(business_id)
    if business.get("package") == "NONE":
        flash("CS Inbox tersedia untuk business yang memakai AI Admin.", "error")
        return redirect(url_for("client.dashboard"))

    conversations = inbox_service.list_conversations(business_id)
    selected_phone = inbox_service.normalize_customer_phone(request.args.get("customer"))
    selected = None
    thread = []
    window = None
    if selected_phone:
        if not inbox_service.customer_exists(business_id, selected_phone):
            abort(404)
        thread = inbox_service.get_thread(business_id, selected_phone)
        try:
            mode = wa_takeover_service.get_state(business_id, selected_phone)
        except Exception:
            # Fail safe in UI too: do not pretend AI is active if DB state could not be verified.
            mode = "STATE_UNAVAILABLE"
        selected = {
            "customer_phone": selected_phone,
            "customer_name": inbox_service.get_customer_name(business_id, selected_phone),
            "mode": mode,
        }
        window = inbox_service.freeform_window_status(business_id, selected_phone)

    return render_template(
        "inbox.html",
        business=business,
        conversations=conversations,
        selected=selected,
        thread=thread,
        window=window,
    )


@client_bp.route("/business/<int:business_id>/inbox/takeover", methods=["POST"])
@security.login_required
def inbox_takeover(business_id):
    business = _business_or_404(business_id)
    phone = inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not inbox_service.customer_exists(business_id, phone):
        abort(404)
    if business.get("status") != "ACTIVE":
        flash("AI Admin business ini belum ACTIVE.", "error")
        return redirect(url_for("client.inbox_page", business_id=business_id, customer=phone))
    user = security.current_user()
    wa_takeover_service.start_human_takeover(business_id, phone, user["id"])
    flash("CS mengambil alih chat ini. AI akan diam sampai dikembalikan ke AI.", "success")
    return redirect(url_for("client.inbox_page", business_id=business_id, customer=phone))


@client_bp.route("/business/<int:business_id>/inbox/return-ai", methods=["POST"])
@security.login_required
def inbox_return_ai(business_id):
    _business_or_404(business_id)
    phone = inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not inbox_service.customer_exists(business_id, phone):
        abort(404)
    user = security.current_user()
    wa_takeover_service.return_to_ai(business_id, phone, user["id"])
    flash("Chat dikembalikan ke AI Admin.", "success")
    return redirect(url_for("client.inbox_page", business_id=business_id, customer=phone))


@client_bp.route("/business/<int:business_id>/inbox/reply", methods=["POST"])
@security.login_required
def inbox_reply(business_id):
    _business_or_404(business_id)
    phone = inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    text = (request.form.get("message") or "").strip()
    if not phone or not inbox_service.customer_exists(business_id, phone):
        abort(404)
    if not text:
        flash("Pesan tidak boleh kosong.", "error")
        return redirect(url_for("client.inbox_page", business_id=business_id, customer=phone))

    ok, reason = inbox_service.send_manual_reply(business_id, phone, text)
    user = security.current_user()
    if ok:
        repo.write_audit(user["id"], business_id, "CS_MANUAL_REPLY_SENT", f"customer={phone}")
        if reason == "sent_history_write_failed":
            flash("Pesan terkirim, tapi history lokal gagal tersimpan. Cek log Client Hub.", "success")
        else:
            flash("Pesan CS terkirim.", "success")
    else:
        friendly = {
            "human_takeover_required": "Klik Ambil Alih dulu sebelum CS mengirim pesan manual.",
            "outside_24h_window": "Sudah di luar window WhatsApp 24 jam. Free-text tidak dikirim; perlu template message.",
            "no_customer_inbound": "Belum ada inbound customer yang valid untuk membuka window WhatsApp 24 jam.",
            "whatsapp_not_connected": "WhatsApp business ini belum berstatus CONNECTED.",
            "business_not_active": "AI Admin business ini belum ACTIVE.",
            "tenant_credentials_unavailable": "Credential WhatsApp tenant belum tersedia di server.",
            "default_whatsapp_credentials_unavailable": "Credential WhatsApp platform belum tersedia di server.",
            "takeover_state_unavailable": "Status Human Takeover tidak bisa diverifikasi. Demi keamanan pesan tidak dikirim.",
            "message_too_long": "Pesan terlalu panjang. Maksimal 4096 karakter.",
        }.get(reason, "Pesan belum berhasil dikirim. Coba lagi atau cek koneksi WhatsApp.")
        flash(friendly, "error")
    return redirect(url_for("client.inbox_page", business_id=business_id, customer=phone))


@client_bp.route("/business/<int:business_id>/inbox/send-template", methods=["POST"])
@security.login_required
def inbox_send_template(business_id):
    """Inbox unification, Section 4/5 — "Kirim Template & Lanjutkan": the approved-template
    re-engagement action shown once a conversation's 24h customer-service window has expired. See
    inbox_service.send_template_reply()'s own docstring for the full safety/config rationale."""
    _business_or_404(business_id)
    phone = inbox_service.normalize_customer_phone(request.form.get("customer_phone"))
    if not phone or not inbox_service.customer_exists(business_id, phone):
        abort(404)

    ok, reason = inbox_service.send_template_reply(business_id, phone)
    user = security.current_user()
    if ok:
        repo.write_audit(user["id"], business_id, "CS_TEMPLATE_REPLY_SENT", f"customer={phone}")
        flash("Template terkirim. Begitu customer membalas, window 24 jam aktif lagi dan kamu bisa balas bebas.", "success")
    else:
        friendly = {
            "human_takeover_required": "Klik Ambil Alih dulu sebelum CS mengirim template.",
            "reengagement_template_not_configured": "Template re-engagement belum dikonfigurasi di server (WHATSAPP_REENGAGEMENT_TEMPLATE_NAME).",
            "whatsapp_not_connected": "WhatsApp business ini belum berstatus CONNECTED.",
            "business_not_active": "AI Admin business ini belum ACTIVE.",
            "tenant_credentials_unavailable": "Credential WhatsApp tenant belum tersedia di server.",
            "default_whatsapp_credentials_unavailable": "Credential WhatsApp platform belum tersedia di server.",
            "takeover_state_unavailable": "Status Human Takeover tidak bisa diverifikasi. Demi keamanan template tidak dikirim.",
        }.get(reason, "Template belum berhasil dikirim. Coba lagi atau cek koneksi WhatsApp.")
        flash(friendly, "error")
    return redirect(url_for("client.inbox_page", business_id=business_id, customer=phone))
