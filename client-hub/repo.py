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
    ]
    values = {c: fields.get(c) for c in cols}
    if isinstance(values.get("additional_languages"), (list, tuple)):
        values["additional_languages"] = json.dumps(values["additional_languages"])
    if isinstance(values.get("operating_hours"), (dict, list)):
        values["operating_hours"] = json.dumps(values["operating_hours"])

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

def write_audit(actor_user_id, business_id, action, detail):
    db.execute(
        "INSERT INTO audit_log (actor_user_id, business_id, action, detail) VALUES (?, ?, ?, ?)",
        (actor_user_id, business_id, action, detail),
    )


def get_audit_log(business_id, limit=50):
    return db.query_all(
        "SELECT * FROM audit_log WHERE business_id = ? ORDER BY created_at DESC LIMIT ?",
        (business_id, limit),
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

WHATSAPP_CONNECTION_STATUSES = ("NOT_CONNECTED", "PENDING_VALIDATION", "CONNECTED")


def get_whatsapp_config(business_id):
    return db.query_one("SELECT * FROM tenant_whatsapp_config WHERE business_id = ?", (business_id,))


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


# ---------------------------------------------------------------------------
# Materialized production tenant config (Phase 2). This is the assembled, versioned snapshot that
# tenant_config_service.py hands to the (future) bot integration — distinct from
# ai_settings.normalized_config_json, which is Claude's raw normalization OUTPUT. provisioning.py
# is what builds this dict (from profile + services + faqs + features + ai_settings) and calls
# save_tenant_config() to persist it.
# ---------------------------------------------------------------------------

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
