"""Data access layer. Every query in the app goes through here (never inline SQL in routes) so
tenant-scoping and audit logging happen in one place, consistently.
"""
import json
from datetime import datetime, timezone

import db
import feature_flags

BUSINESS_STATUSES = (
    "DRAFT", "ONBOARDING", "READY_FOR_AI_SETUP", "READY_FOR_REVIEW",
    "APPROVED", "ACTIVE", "NEEDS_REVISION", "SUSPENDED",
)

# Kept as an alias for backward compatibility (some existing tests/code reference
# repo.DEFAULT_FEATURES directly) — the actual matrix now lives in feature_flags.py, the single
# source of truth for Phase 3 (see that module's docstring for why it was pulled out of here).
DEFAULT_FEATURES = feature_flags.FEATURE_MATRIX


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------

def get_user_by_email(email):
    return db.query_one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))


def create_user(email, password_hash, role="CLIENT_OWNER", full_name=None):
    return db.insert_returning_id(
        "INSERT INTO users (email, password_hash, role, full_name) VALUES (?, ?, ?, ?)",
        (email.strip().lower(), password_hash, role, full_name),
    )


# ---------------------------------------------------------------------------
# Businesses (tenants)
# ---------------------------------------------------------------------------

def create_business(owner_user_id, business_name, package="AI_ADMIN_BASIC"):
    tenant_slug = f"tenant_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
    business_id = db.insert_returning_id(
        "INSERT INTO businesses (tenant_slug, business_name, package, status) VALUES (?, ?, ?, 'DRAFT')",
        (tenant_slug, business_name.strip(), package),
    )
    db.execute(
        "INSERT INTO business_memberships (business_id, user_id, role_in_business) VALUES (?, ?, 'OWNER')",
        (business_id, owner_user_id),
    )
    db.execute("INSERT INTO onboarding_status (business_id) VALUES (?)", (business_id,))
    feats = feature_flags.features_for_package(package)
    db.execute(
        """INSERT INTO tenant_features
           (business_id, faq, business_info, catalog, basic_lead_capture, owner_commands,
            advanced_history, image_understanding, voice_note, lead_qualification, appointment,
            payment_conversation)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (business_id, *[bool(feats[k]) for k in (
            "faq", "business_info", "catalog", "basic_lead_capture", "owner_commands",
            "advanced_history", "image_understanding", "voice_note", "lead_qualification",
            "appointment", "payment_conversation",
        )]),
    )
    db.execute("INSERT INTO ai_settings (business_id, ai_status) VALUES (?, 'PENDING')", (business_id,))
    write_audit(owner_user_id, business_id, "business_created", f"name={business_name!r} package={package}")
    return business_id


def upgrade_business_package(business_id, package, actor_user_id):
    """Ecosystem Sync Section 2: explicit, deliberate action for a customer who created a
    business WITHOUT AI Admin (package='NONE') and now wants to add it. Re-seeds tenant_features
    for the new package (NONE never had any real features on) and flips ai_settings back to
    PENDING so the business enters onboarding for the first time. Only meant to be called for a
    business currently on 'NONE' — callers (routes_client.py) enforce that."""
    if not feature_flags.is_valid_package(package) or package == "NONE":
        raise ValueError(f"invalid upgrade target package {package!r}")
    db.execute("UPDATE businesses SET package = ?, updated_at = ? WHERE id = ?",
               (package, _now(), business_id))
    feats = feature_flags.features_for_package(package)
    keys = ("faq", "business_info", "catalog", "basic_lead_capture", "owner_commands",
            "advanced_history", "image_understanding", "voice_note", "lead_qualification",
            "appointment", "payment_conversation")
    set_clause = ", ".join(f"{k} = ?" for k in keys)
    db.execute(f"UPDATE tenant_features SET {set_clause} WHERE business_id = ?",
               (*[bool(feats[k]) for k in keys], business_id))
    existing_ai_settings = db.query_one("SELECT business_id FROM ai_settings WHERE business_id = ?", (business_id,))
    if existing_ai_settings is None:
        db.execute("INSERT INTO ai_settings (business_id, ai_status) VALUES (?, 'PENDING')", (business_id,))
    write_audit(actor_user_id, business_id, "business_upgraded_to_ai_admin", f"package={package}")


def get_business(business_id):
    return db.query_one("SELECT * FROM businesses WHERE id = ?", (business_id,))


def list_businesses_for_user(user_id):
    return db.query_all(
        """SELECT b.* FROM businesses b
           JOIN business_memberships m ON m.business_id = b.id
           WHERE m.user_id = ? ORDER BY b.created_at DESC""",
        (user_id,),
    )


def list_all_businesses(status_filter=None):
    if status_filter:
        return db.query_all(
            "SELECT * FROM businesses WHERE status = ? ORDER BY created_at DESC", (status_filter,)
        )
    return db.query_all("SELECT * FROM businesses ORDER BY created_at DESC")


def set_business_status(business_id, new_status, actor_user_id=None, detail=None):
    assert new_status in BUSINESS_STATUSES, f"unknown status {new_status}"
    db.execute(
        "UPDATE businesses SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, _now(), business_id),
    )
    write_audit(actor_user_id, business_id, "status_changed", detail or f"new_status={new_status}")
    # Ecosystem Sync Section 10(A)/(F)/11: two important owner-notification trigger points live
    # here since every AI onboarding submission path and every approval path already funnels
    # through this one function. Wrapped so a notification-plumbing bug can never break the
    # actual status transition it's reporting on.
    try:
        import owner_notifications
        business = get_business(business_id)
        business_name = business["business_name"] if business else f"business #{business_id}"
        if new_status == "READY_FOR_REVIEW":
            owner_notifications.notify_ai_onboarding_ready(business_id, business_name)
        elif new_status == "APPROVED" and business and business.get("package") != "NONE":
            owner_notifications.notify_whatsapp_connection_ready(business_id, business_name)
    except Exception:
        pass


def set_business_package(business_id, package, actor_user_id=None):
    assert feature_flags.is_valid_package(package), f"unknown package {package}"
    db.execute("UPDATE businesses SET package = ?, updated_at = ? WHERE id = ?", (package, _now(), business_id))
    # Bugfix (production-foundation cycle): changing package must re-seed tenant_features —
    # previously this only updated the `package` column and left feature flags at whatever the
    # ORIGINAL package was, silently granting/denying the wrong features until a human noticed.
    set_tenant_features_for_package(business_id, package)
    write_audit(actor_user_id, business_id, "package_changed", f"package={package}")


# ---------------------------------------------------------------------------
# Onboarding steps — each save writes an append-only raw session row AND upserts the "current"
# profile/service/faq rows used for review + AI normalization input.
# ---------------------------------------------------------------------------

def save_onboarding_session(business_id, step, raw_payload, user_id=None):
    db.execute(
        "INSERT INTO onboarding_sessions (business_id, step, raw_payload_json, submitted_by_user_id) VALUES (?, ?, ?, ?)",
        (business_id, step, json.dumps(raw_payload, ensure_ascii=False), user_id),
    )


def upsert_business_profile(business_id, fields):
    existing = db.query_one("SELECT business_id FROM business_profiles WHERE business_id = ?", (business_id,))
    cols = [
        "category", "short_description", "country", "timezone", "address", "business_phone",
        "owner_name", "primary_language", "additional_languages", "tone", "customer_salutation",
        "operating_hours", "closed_days", "online_or_offline", "appointment_rules_raw",
        # Pro tenant parity cycle (Tasks 3/4/5, migration 0012) — this tenant's OWN appointment
        # toggle and OWN payment/bank details, never Kilas Works' own PAYMENT_CONFIG/BCA account.
        "appointment_enabled", "payment_bank_name", "payment_account_number",
        "payment_account_name", "payment_instructions",
    ]
    values = {c: fields.get(c) for c in cols}
    if isinstance(values.get("additional_languages"), (list, tuple)):
        values["additional_languages"] = json.dumps(values["additional_languages"])
    if isinstance(values.get("operating_hours"), (dict, list)):
        values["operating_hours"] = json.dumps(values["operating_hours"])
    if values.get("appointment_enabled") is None:
        values["appointment_enabled"] = True
    else:
        values["appointment_enabled"] = bool(values["appointment_enabled"]) and values["appointment_enabled"] not in ("false", "0", "off", "")

    if existing:
        set_clause = ", ".join(f"{c} = ?" for c in cols)
        db.execute(
            f"UPDATE business_profiles SET {set_clause}, updated_at = ? WHERE business_id = ?",
            (*[values[c] for c in cols], _now(), business_id),
        )
    else:
        col_list = ", ".join(cols)
        placeholders = ", ".join("?" for _ in cols)
        db.execute(
            f"INSERT INTO business_profiles (business_id, {col_list}) VALUES (?, {placeholders})",
            (business_id, *[values[c] for c in cols]),
        )


def get_business_profile(business_id):
    return db.query_one("SELECT * FROM business_profiles WHERE business_id = ?", (business_id,))


def replace_business_services(business_id, raw_service_rows):
    """Client re-submits the whole services list each time (simplest correct semantics for a
    wizard step) — old rows are cleared and re-inserted as RAW input, needs_review defaults to 1
    until AI normalization runs and clears it (or flags it for a specific row)."""
    db.execute("DELETE FROM business_services WHERE business_id = ?", (business_id,))
    for i, raw in enumerate(raw_service_rows):
        db.execute(
            "INSERT INTO business_services (business_id, raw_input, needs_review, sort_order) VALUES (?, ?, ?, ?)",
            (business_id, raw, True, i),
        )


def get_business_services(business_id):
    return db.query_all(
        "SELECT * FROM business_services WHERE business_id = ? ORDER BY sort_order", (business_id,)
    )


def update_normalized_service(service_id, service_name, description, price_from, price_to, currency, needs_review):
    db.execute(
        """UPDATE business_services SET service_name = ?, description = ?, price_from = ?,
           price_to = ?, currency = ?, needs_review = ? WHERE id = ?""",
        (service_name, description, price_from, price_to, currency, bool(needs_review), service_id),
    )


def replace_business_faqs(business_id, raw_faq_rows):
    db.execute("DELETE FROM business_faqs WHERE business_id = ?", (business_id,))
    for raw in raw_faq_rows:
        db.execute(
            "INSERT INTO business_faqs (business_id, raw_input, needs_review) VALUES (?, ?, ?)",
            (business_id, raw, True),
        )


def get_business_faqs(business_id):
    return db.query_all("SELECT * FROM business_faqs WHERE business_id = ? ORDER BY id", (business_id,))


def update_normalized_faq(faq_id, question, answer, category, needs_review):
    db.execute(
        "UPDATE business_faqs SET question = ?, answer = ?, category = ?, needs_review = ? WHERE id = ?",
        (question, answer, category, bool(needs_review), faq_id),
    )


def mark_onboarding_step_done(business_id, step_field):
    assert step_field in (
        "basics_done", "services_done", "operations_done", "faq_done", "style_done",
        "upload_done", "reviewed_done", "simulated_done",
    )
    db.execute(
        f"UPDATE onboarding_status SET {step_field} = ?, updated_at = ? WHERE business_id = ?",
        (True, _now(), business_id),
    )


def get_onboarding_status(business_id):
    return db.query_one("SELECT * FROM onboarding_status WHERE business_id = ?", (business_id,))


def onboarding_completion_percent(business_id):
    status = get_onboarding_status(business_id)
    if not status:
        return 0
    fields = ["basics_done", "services_done", "operations_done", "faq_done", "style_done", "reviewed_done"]
    done = sum(1 for f in fields if status.get(f))
    return round(done / len(fields) * 100)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def save_business_file(business_id, original_filename, mime_type, size_bytes, content_bytes, extracted_text, user_id):
    return db.insert_returning_id(
        """INSERT INTO business_files
           (business_id, original_filename, mime_type, size_bytes, content, extracted_text, uploaded_by_user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (business_id, original_filename, mime_type, size_bytes, content_bytes, extracted_text, user_id),
    )


def list_business_files(business_id):
    return db.query_all(
        """SELECT id, business_id, original_filename, mime_type, size_bytes, extracted_text, created_at
           FROM business_files WHERE business_id = ? ORDER BY created_at DESC""",
        (business_id,),
    )


def get_business_file_content(file_id, business_id):
    return db.query_one(
        "SELECT * FROM business_files WHERE id = ? AND business_id = ?", (file_id, business_id)
    )


# ---------------------------------------------------------------------------
# AI settings (normalization result)
# ---------------------------------------------------------------------------

def set_ai_status(business_id, status, error=None):
    db.execute(
        "UPDATE ai_settings SET ai_status = ?, last_error = ?, updated_at = ? WHERE business_id = ?",
        (status, error, _now(), business_id),
    )


def save_ai_normalized_config(business_id, summary, config_dict, missing_fields):
    db.execute(
        """UPDATE ai_settings SET ai_status = 'DONE', normalized_summary = ?,
           normalized_config_json = ?, missing_fields_json = ?, last_error = NULL, updated_at = ?
           WHERE business_id = ?""",
        (summary, json.dumps(config_dict, ensure_ascii=False), json.dumps(missing_fields, ensure_ascii=False),
         _now(), business_id),
    )


def get_ai_settings(business_id):
    row = db.query_one("SELECT * FROM ai_settings WHERE business_id = ?", (business_id,))
    if row and row.get("normalized_config_json"):
        row["normalized_config"] = json.loads(row["normalized_config_json"])
    if row and row.get("missing_fields_json"):
        row["missing_fields"] = json.loads(row["missing_fields_json"])
    return row


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def get_tenant_features(business_id):
    return db.query_one("SELECT * FROM tenant_features WHERE business_id = ?", (business_id,))


def set_tenant_features_for_package(business_id, package):
    feats = feature_flags.features_for_package(package)
    cols = list(feats.keys())
    set_clause = ", ".join(f"{c} = ?" for c in cols)
    db.execute(
        f"UPDATE tenant_features SET {set_clause} WHERE business_id = ?",
        (*[bool(feats[c]) for c in cols], business_id),
    )


# ---------------------------------------------------------------------------
# Simulation (isolated sandbox, never touches production conversation state)
# ---------------------------------------------------------------------------

def save_simulation_message(business_id, session_token, role, content):
    db.execute(
        "INSERT INTO simulation_messages (business_id, session_token, role, content) VALUES (?, ?, ?, ?)",
        (business_id, session_token, role, content),
    )


def get_simulation_history(business_id, session_token, limit=20):
    rows = db.query_all(
        """SELECT * FROM simulation_messages WHERE business_id = ? AND session_token = ?
           ORDER BY id DESC LIMIT ?""",
        (business_id, session_token, limit),
    )
    return list(reversed(rows))


def flag_simulation_message(message_id, business_id, note):
    db.execute(
        "UPDATE simulation_messages SET flagged_wrong = ?, flag_note = ? WHERE id = ? AND business_id = ?",
        (True, note, message_id, business_id),
    )


def list_flagged_simulation_messages(business_id):
    return db.query_all(
        "SELECT * FROM simulation_messages WHERE business_id = ? AND flagged_wrong = ? ORDER BY created_at DESC",
        (business_id, True),
    )


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

def approve_business(business_id, admin_user_id):
    existing = db.query_one("SELECT business_id FROM tenant_activation WHERE business_id = ?", (business_id,))
    if existing:
        db.execute(
            "UPDATE tenant_activation SET approved_by_user_id = ?, approved_at = ? WHERE business_id = ?",
            (admin_user_id, _now(), business_id),
        )
    else:
        db.execute(
            "INSERT INTO tenant_activation (business_id, approved_by_user_id, approved_at) VALUES (?, ?, ?)",
            (business_id, admin_user_id, _now()),
        )
    set_business_status(business_id, "APPROVED", admin_user_id, "approved by Kilas Admin")
    write_audit(admin_user_id, business_id, "approved", None)


def activate_business(business_id, admin_user_id):
    db.execute(
        "UPDATE tenant_activation SET activated_by_user_id = ?, activated_at = ?, deactivated_at = NULL WHERE business_id = ?",
        (admin_user_id, _now(), business_id),
    )
    set_business_status(business_id, "ACTIVE", admin_user_id, "activated by Kilas Admin")
    write_audit(admin_user_id, business_id, "activated", None)


def deactivate_business(business_id, admin_user_id):
    db.execute(
        "UPDATE tenant_activation SET deactivated_at = ? WHERE business_id = ?",
        (_now(), business_id),
    )
    set_business_status(business_id, "SUSPENDED", admin_user_id, "deactivated by Kilas Admin")
    write_audit(admin_user_id, business_id, "deactivated", None)


def get_activation(business_id):
    return db.query_one("SELECT * FROM tenant_activation WHERE business_id = ?", (business_id,))


def request_revision(business_id, admin_user_id, note):
    set_business_status(business_id, "NEEDS_REVISION", admin_user_id, note)
    write_audit(admin_user_id, business_id, "revision_requested", note)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def write_audit(actor_user_id, business_id, action, detail, project_id=None):
    """project_id (Business Hub V2, Final Operations Polish, Section 14) is optional and additive
    — every pre-existing call site keeps working unchanged with project_id defaulting to NULL.
    Passing it lets get_project_audit_log() below pull a clean per-project history without parsing
    free-text `detail` strings."""
    db.execute(
        "INSERT INTO audit_log (actor_user_id, business_id, action, detail, project_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (actor_user_id, business_id, action, detail, project_id),
    )


def get_audit_log(business_id, limit=50):
    return db.query_all(
        "SELECT * FROM audit_log WHERE business_id = ? ORDER BY created_at DESC LIMIT ?",
        (business_id, limit),
    )


def get_project_audit_log(project_id, limit=100):
    """Section 14: 'admin can see clear history for quote created/changed/approved/rejected,
    payment proof uploaded/verified/rejected, project status changed' — reuses the existing
    audit_log architecture (no new event-viewer system), just filtered to one project."""
    return db.query_all(
        "SELECT * FROM audit_log WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    )


def write_audit_no_business(actor_user_id, action, detail):
    """Same as write_audit() but for events with no associated business — password reset requests
    happen before we necessarily even know which business a user belongs to, and a user can belong
    to zero or several. business_id is nullable in audit_log for exactly this case."""
    db.execute(
        "INSERT INTO audit_log (actor_user_id, business_id, action, detail) VALUES (?, ?, ?, ?)",
        (actor_user_id, None, action, detail),
    )


# ---------------------------------------------------------------------------
# Password reset (Business Hub V2, Phase A)
# ---------------------------------------------------------------------------

def get_user_by_id(user_id):
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def update_user_password(user_id, new_password_hash):
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_password_hash, user_id))


def create_password_reset_token(user_id, token_hash, expires_at, requested_ip=None):
    return db.insert_returning_id(
        "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at, requested_ip) "
        "VALUES (?, ?, ?, ?)",
        (user_id, token_hash, expires_at, requested_ip),
    )


def get_valid_reset_token(token_hash, now_iso):
    """Returns the token row only if it exists, is unused, and has not expired — all three
    checked in SQL so an expired-but-still-present row never looks valid to a caller who forgets
    to re-check in Python. Returns None otherwise (indistinguishable from "token never existed" by
    design — no information leak about which case applied)."""
    return db.query_one(
        "SELECT * FROM password_reset_tokens WHERE token_hash = ? AND used_at IS NULL "
        "AND expires_at > ?",
        (token_hash, now_iso),
    )


def mark_reset_token_used(token_id, now_iso):
    db.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
        (now_iso, token_id),
    )


def invalidate_all_reset_tokens_for_user(user_id, now_iso):
    """Called right after a successful reset — any OTHER still-valid reset link for this user
    (e.g. requested twice in a row) is burned too, so an old email lying around in an inbox can't
    be used after the password has already been changed via a newer one."""
    db.execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL",
        (now_iso, user_id),
    )


def required_fields_missing(business_id):
    """Minimum validation gate before READY_FOR_REVIEW (section 10). Returns a list of missing
    field names, empty list means the business may proceed."""
    missing = []
    business = get_business(business_id)
    profile = get_business_profile(business_id)
    services = get_business_services(business_id)

    if not business or not business["business_name"].strip():
        missing.append("business_name")
    if not profile:
        missing.append("owner_name")
        missing.append("category")
        missing.append("primary_language")
        missing.append("customer_salutation")
    else:
        if not profile.get("owner_name"):
            missing.append("owner_name")
        if not profile.get("category"):
            missing.append("category")
        if not profile.get("primary_language"):
            missing.append("primary_language")
        if not profile.get("customer_salutation"):
            missing.append("customer_salutation")
    if not services:
        missing.append("core_product_or_service")
    return missing


# ---------------------------------------------------------------------------
# WhatsApp connection config (Phase 2 — production tenant model). Deliberately never stores the
# actual WhatsApp access token: `credentials_reference` is a POINTER (e.g. an env var name or a
# secret-manager key), not the secret itself. See provisioning.py / the final report for the full
# secret-reference design rationale.
# ---------------------------------------------------------------------------

WHATSAPP_CONNECTION_STATUSES = ("NOT_CONNECTED", "PENDING_VALIDATION", "CONNECTED", "VALIDATION_FAILED")


def get_whatsapp_config(business_id):
    return db.query_one("SELECT * FROM tenant_whatsapp_config WHERE business_id = ?", (business_id,))


def find_business_id_by_phone_number_id(phone_number_id, exclude_business_id=None):
    """Multi-tenant runtime safety cycle (Task A) — uniqueness check for the admin "Connect
    WhatsApp" flow: is this Phone Number ID already assigned to a DIFFERENT tenant? Checks both
    the Phase 2 canonical table (tenant_whatsapp_config) and the V1 column it is dual-written
    alongside (businesses.whatsapp_phone_number_id), since either could hold a prior assignment.
    Returns the OTHER business_id already using it, or None if it's free (or only used by
    exclude_business_id itself, e.g. re-saving the same tenant's own value)."""
    if not phone_number_id:
        return None
    exclude = exclude_business_id if exclude_business_id is not None else -1
    row = db.query_one(
        "SELECT business_id FROM tenant_whatsapp_config WHERE phone_number_id = ? AND business_id != ?",
        (phone_number_id, exclude),
    )
    if row:
        return row["business_id"]
    row = db.query_one(
        "SELECT id FROM businesses WHERE whatsapp_phone_number_id = ? AND id != ?",
        (phone_number_id, exclude),
    )
    return row["id"] if row else None


def upsert_whatsapp_config(business_id, phone_number_id, waba_id, credentials_reference,
                            connection_status="PENDING_VALIDATION"):
    assert connection_status in WHATSAPP_CONNECTION_STATUSES
    existing = get_whatsapp_config(business_id)
    now = _now()
    if existing:
        db.execute(
            """UPDATE tenant_whatsapp_config
               SET phone_number_id = ?, waba_id = ?, credentials_reference = ?,
                   connection_status = ?, connected_at = ?
               WHERE business_id = ?""",
            (phone_number_id, waba_id, credentials_reference, connection_status, now, business_id),
        )
    else:
        db.execute(
            """INSERT INTO tenant_whatsapp_config
               (business_id, phone_number_id, waba_id, credentials_reference, connection_status, connected_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (business_id, phone_number_id, waba_id, credentials_reference, connection_status, now),
        )


def mark_whatsapp_validated(business_id):
    db.execute(
        "UPDATE tenant_whatsapp_config SET connection_status = 'CONNECTED', validated_at = ? WHERE business_id = ?",
        (_now(), business_id),
    )


def mark_whatsapp_validation_failed(business_id):
    """Multi-tenant runtime safety cycle (Task A) — the counterpart to mark_whatsapp_validated()
    for when the real connectivity check (uniqueness and/or a live Meta Graph API read) fails.
    Deliberately NEVER sets connection_status to CONNECTED — a failed validation must always stay
    a status that provisioning.activate_tenant()'s gate treats as "not connected yet"."""
    db.execute(
        "UPDATE tenant_whatsapp_config SET connection_status = 'VALIDATION_FAILED' WHERE business_id = ?",
        (business_id,),
    )


# ---------------------------------------------------------------------------
# Materialized production tenant config (Phase 2). This is the assembled, versioned snapshot that
# tenant_config_service.py hands to the (future) bot integration — distinct from
# ai_settings.normalized_config_json, which is Claude's raw normalization OUTPUT. provisioning.py
# is what builds this dict (from profile + services + faqs + features + ai_settings) and calls
# save_tenant_config() to persist it.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Global admin search (Final Operations Polish, Section 9) — admin-only (callers must already be
# behind @security.admin_required; this function itself does not check role, same trust boundary
# as every other function in this module). Deliberately simple: a handful of LIKE queries across
# the tables an admin actually needs to jump to, no full-text search engine, no new dependency.
# ---------------------------------------------------------------------------

def admin_search(query, limit=10):
    q = f"%{(query or '').strip()}%"
    if not q.strip("%"):
        return {"users": [], "businesses": [], "projects": [], "quotations": [], "invoices": [],
                "talents": []}

    users = db.query_all(
        "SELECT id, email, full_name, role FROM users WHERE email LIKE ? OR full_name LIKE ? "
        "ORDER BY id DESC LIMIT ?",
        (q, q, limit),
    )
    businesses = db.query_all(
        "SELECT b.* FROM businesses b LEFT JOIN business_profiles p ON p.business_id = b.id "
        "WHERE b.business_name LIKE ? OR p.business_phone LIKE ? OR p.owner_name LIKE ? "
        "ORDER BY b.created_at DESC LIMIT ?",
        (q, q, q, limit),
    )
    projects = db.query_all(
        "SELECT * FROM projects WHERE title LIKE ? OR project_type LIKE ? "
        "ORDER BY created_at DESC LIMIT ?",
        (q, q, limit),
    )
    quotations = db.query_all(
        "SELECT * FROM quotations WHERE quotation_number LIKE ? ORDER BY created_at DESC LIMIT ?",
        (q, limit),
    )
    invoices = db.query_all(
        "SELECT * FROM invoices WHERE invoice_number LIKE ? ORDER BY created_at DESC LIMIT ?",
        (q, limit),
    )
    talents = db.query_all(
        "SELECT * FROM talents WHERE name LIKE ? OR social_handle LIKE ? ORDER BY name LIMIT ?",
        (q, q, limit),
    )
    return {
        "users": users, "businesses": businesses, "projects": projects,
        "quotations": quotations, "invoices": invoices, "talents": talents,
    }


def get_tenant_config_row(business_id):
    row = db.query_one("SELECT * FROM tenant_configs WHERE business_id = ?", (business_id,))
    if row and row.get("config_json"):
        row["config"] = json.loads(row["config_json"])
    return row


def save_tenant_config(business_id, config_dict):
    """Upserts the tenant_configs row and returns (config_version, changed: bool). `changed` is
    False when the new config is byte-identical to what's already stored — used by
    provisioning.provision_tenant() to make re-provisioning idempotent (no version bump, no new
    audit entry, when nothing actually changed)."""
    config_json = json.dumps(config_dict, ensure_ascii=False, sort_keys=True)
    existing = db.query_one("SELECT config_json, config_version FROM tenant_configs WHERE business_id = ?", (business_id,))
    now = _now()
    if existing is None:
        db.execute(
            "INSERT INTO tenant_configs (business_id, config_version, config_json, provisioned_at, updated_at) "
            "VALUES (?, 1, ?, ?, ?)",
            (business_id, config_json, now, now),
        )
        return 1, True

    if existing["config_json"] == config_json:
        return existing["config_version"], False

    new_version = existing["config_version"] + 1
    db.execute(
        "UPDATE tenant_configs SET config_version = ?, config_json = ?, updated_at = ? WHERE business_id = ?",
        (new_version, config_json, now, business_id),
    )
    return new_version, True
