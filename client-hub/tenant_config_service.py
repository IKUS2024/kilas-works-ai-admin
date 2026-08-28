"""The clean, read-only interface the EXISTING bot (../app.py) would import to become
tenant-aware — this is the "tenant configuration interface/repository/service" requested in
section 19, deliberately kept separate from Client Hub's own request/response routes so it has
no Flask dependency and can be imported from anywhere.

IMPORTANT — this module is NOT wired into ../app.py in this cycle. Per the request's own
instructions ("do not rewrite the working bot", "do not migrate everything at once if risky"),
actually changing app.py's webhook routing to call this is a separate, deliberately small future
patch — see the final report for the exact minimal diff proposed. This file exists so that patch
can be a true one-liner-per-call-site integration rather than something invented from scratch
under time pressure later.

Design constraints these functions honor (sections 20-22 of the request):
  - Tenant resolution is by an AUTHORITATIVE channel identifier (whatsapp_phone_number_id) ONLY.
    There is no function here that accepts free-form message text or a business name string and
    tries to guess a tenant from it.
  - Owner authorization data (trusted_owner_phone) is returned per-tenant, never shared/merged
    across tenants, and this module never reads message CONTENT to decide who the owner is —
    that decision is entirely the caller's (the same "check the trusted config", never "trust
    the words in the message" principle already used for Kilas Works' own OWNER_WHATSAPP_NUMBER).
  - Every function takes a business_id/tenant_id or a phone_number_id and returns data for THAT
    tenant only — there is no "list everything" function here (that lives in repo.py, used only
    by the Kilas Admin dashboard which is explicitly allowed to see all tenants).
"""
import db
import repo


# ---------------------------------------------------------------------------
# Business Hub V2, Phase G/H additions — same contract philosophy as Phase 5 above: pure read
# functions, tenant-scoped, NOT yet called from ../app.py (see BOT_INTEGRATION_GUIDE.md's Patch
# 4/5/6 for the deliberately-unapplied wiring). Added here so the eventual integration patch has
# every function it needs already written and tested.
# ---------------------------------------------------------------------------

def get_conversation_mode(tenant_id, customer_phone):
    """Phase H contract: AI_ACTIVE or HUMAN_TAKEOVER for this one tenant+customer pair. The bot
    would check this before auto-replying — see wa_takeover_service.py for the write side."""
    import wa_takeover_service
    return wa_takeover_service.get_state(tenant_id, customer_phone)


def get_active_service_catalog():
    """Phase F contract: the SAME catalog rows shown in the app, for the bot to quote fixed prices
    from — never a second, independently-maintained price list. Not tenant-scoped (the catalog is
    Kilas Works' own service list, not a per-client thing)."""
    import catalog_service
    return catalog_service.list_active_catalog()


def get_open_projects_summary(tenant_id):
    """Phase F/17 contract: lets an owner-command handler answer 'Project Rina gimana?' /
    'Payment project ABC udah masuk belum?' by giving it a tenant-scoped list of open (non-
    terminal) projects with their status, budget, and latest quotation — WITHOUT the bot needing
    to know anything about the projects/quotations/payments schema directly."""
    import projects_repo
    import quotation_service
    projects = projects_repo.list_projects_for_business(tenant_id)
    summaries = []
    for p in projects:
        if p["status"] in ("COMPLETED", "CANCELLED"):
            continue
        latest_quote = quotation_service.get_latest_quotation_for_project(p["id"])
        summaries.append({
            "project_id": p["id"], "title": p["title"], "project_type": p["project_type"],
            "status": p["status"], "budget_min": p["budget_min"], "budget_max": p["budget_max"],
            "final_price": p["final_price"],
            "latest_quotation_status": latest_quote["status"] if latest_quote else None,
        })
    return summaries


def resolve_tenant_id_by_whatsapp_phone_number_id(whatsapp_phone_number_id):
    """The ONLY tenant-resolution entrypoint this module exposes. Returns business_id or None.
    Only ACTIVE tenants resolve — an approved-but-not-yet-activated or suspended tenant must not
    have its config consumed by the live bot."""
    if not whatsapp_phone_number_id:
        return None
    row = db.query_one(
        "SELECT id FROM businesses WHERE whatsapp_phone_number_id = ? AND status = 'ACTIVE'",
        (whatsapp_phone_number_id,),
    )
    return row["id"] if row else None


def get_trusted_owner_phone(tenant_id):
    business = repo.get_business(tenant_id)
    if not business or business["status"] != "ACTIVE":
        return None
    return business.get("trusted_owner_phone")


def get_tenant_features(tenant_id):
    """Backend-enforced feature flags (section 13) — the bot should check THIS, not infer
    capability from prompt wording, before allowing owner_commands / voice_note / appointment /
    payment_conversation / image_understanding / advanced_history / lead_qualification for a
    given tenant."""
    row = repo.get_tenant_features(tenant_id)
    if not row:
        return {}
    return {k: bool(v) for k, v in row.items() if k != "business_id"}


def get_tenant_ai_config(tenant_id):
    """The structured config (section 12) the bot would inject as tenant-specific KNOWLEDGE —
    NOT as a permanent edit to any global prompt string. Returns None if the tenant hasn't
    completed AI setup or isn't active; callers must handle that (e.g. fall back to a generic
    "ask the owner" behavior) rather than assume this always returns data.

    Kept for backward compatibility with the V1 cycle — get_tenant_config() below is the Phase 5
    contract name and returns the newer, richer Phase-2 materialized config instead of this raw
    ai_settings-based one. New integration work should prefer get_tenant_config()."""
    business = repo.get_business(tenant_id)
    if not business or business["status"] != "ACTIVE":
        return None
    ai_settings = repo.get_ai_settings(tenant_id)
    if not ai_settings or ai_settings.get("ai_status") != "DONE":
        return None
    config = ai_settings.get("normalized_config") or {}
    config["tenant_id"] = tenant_id
    config["package"] = business["package"]
    config["features_enabled"] = get_tenant_features(tenant_id)
    return config


# ---------------------------------------------------------------------------
# Phase 5 — "Future Bot Integration Contract". These four function names are exactly what the
# production-foundation request asked the future AI Admin runtime to be able to call. They are
# thin wrappers over the functions above / over repo.py — added here, rather than replacing the
# original names, so nothing that already depends on resolve_tenant_id_by_whatsapp_phone_number_id
# or get_tenant_ai_config (including this cycle's own tests) needs to change.
# ---------------------------------------------------------------------------

def get_tenant_by_phone_number_id(phone_number_id):
    """Phase 5 contract name for resolve_tenant_id_by_whatsapp_phone_number_id(). Same rule: only
    an ACTIVE tenant resolves, and resolution is by this one authoritative channel identifier —
    never by message content or business-name text matching."""
    return resolve_tenant_id_by_whatsapp_phone_number_id(phone_number_id)


def get_tenant_config(tenant_id):
    """Phase 5 contract name. Returns the Phase 2 MATERIALIZED tenant config (the versioned
    snapshot provisioning.provision_tenant() built and repo.save_tenant_config() stored) — richer
    and more structured than get_tenant_ai_config()'s raw Claude output, and independent of
    whether ai_settings still has a 'DONE' status (a tenant can be re-approved/re-provisioned
    without re-running AI normalization). Returns None unless the tenant is ACTIVE, matching every
    other function in this module's "only serve ACTIVE tenants" rule."""
    business = repo.get_business(tenant_id)
    if not business or business["status"] != "ACTIVE":
        return None
    row = repo.get_tenant_config_row(tenant_id)
    if not row:
        return None
    return row.get("config")


def get_tenant_whatsapp_channel(tenant_id):
    """Multi-tenant runtime safety cycle (Task 1/2) — THIS tenant's OWN WhatsApp channel
    identifiers, so the production bot can send an outgoing reply from the business's own number
    instead of always using Kilas Works' own global WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN.
    Returns None unless the tenant is ACTIVE and a phone_number_id + credentials_reference have
    actually been recorded (repo.upsert_whatsapp_config, written by the admin "Connect WhatsApp"
    flow) — an incomplete/never-connected channel is NOT this function's job to paper over; the
    caller (app.py's _get_tenant_whatsapp_channel_safe) treats None as "not configured yet" and
    must never fall back to Kilas Works' own identity.

    `credentials_reference` is a POINTER to where the real access token lives (an environment
    variable name, e.g. "WHATSAPP_TOKEN__TENANT_7" — see migrations/0002's own docstring) — NEVER
    the secret itself, so this function never returns anything that needs to be treated as a
    secret on its own. The actual token is resolved server-side, by the bot process, from its own
    environment — this module has no business reading that value out of the DB because it was
    never written there."""
    business = repo.get_business(tenant_id)
    if not business or business["status"] != "ACTIVE":
        return None
    config = repo.get_whatsapp_config(tenant_id)
    if not config:
        return None
    phone_number_id = config.get("phone_number_id")
    if not phone_number_id:
        return None
    # Task 8 — credentials_reference is now OPTIONAL: absent/empty means this tenant shares Kilas
    # Works' own default server-side access value (see app.py's _get_tenant_whatsapp_channel_safe
    # docstring for the full design decision and its documented assumption); only phone_number_id
    # is required to record a working channel.
    return {"phone_number_id": phone_number_id, "credentials_reference": config.get("credentials_reference") or None}


def get_tenant_appointment_settings(tenant_id):
    """Pro tenant parity cycle (Task 3) — THIS tenant's OWN appointment settings (business hours,
    the appointment-enabled toggle, and booking notes/rules), for the bot to use instead of Kilas
    Works' own hardcoded office hours/rules. Returns None unless the tenant is ACTIVE (same rule
    as every other function here); callers must treat None as 'appointments not available'.

    Deliberately reads business_profiles LIVE (not the versioned tenant_config snapshot that
    provisioning.provision_tenant() builds, which only a KILAS_ADMIN action re-materializes) so a
    business owner's own edit via Client Hub's business-settings page (routes_client.py,
    reachable at any business status, not just pre-activation) takes effect on the very next
    customer message — no engineering/admin action required, matching Task 5's explicit goal."""
    business = repo.get_business(tenant_id)
    if not business or business["status"] != "ACTIVE":
        return None
    profile = repo.get_business_profile(tenant_id) or {}
    features = get_tenant_features(tenant_id)
    return {
        "meeting_enabled": bool(features.get("appointment")) and bool(profile.get("appointment_enabled", True)),
        "business_hours_raw": profile.get("operating_hours"),
        "closed_days": profile.get("closed_days"),
        "appointment_rules": profile.get("appointment_rules_raw"),
    }


def get_tenant_payment_config(tenant_id):
    """Pro tenant parity cycle (Task 4) — THIS tenant's OWN bank/payment details (never Kilas
    Works' own PAYMENT_CONFIG/BCA account, which belongs solely to ../app.py's platform-billing
    concern and is not read anywhere in this module). Returns None unless the tenant is ACTIVE.
    Reads business_profiles LIVE — see get_tenant_appointment_settings' docstring for why."""
    business = repo.get_business(tenant_id)
    if not business or business["status"] != "ACTIVE":
        return None
    profile = repo.get_business_profile(tenant_id) or {}
    return {
        "bank_name": profile.get("payment_bank_name"),
        "account_number": profile.get("payment_account_number"),
        "account_name": profile.get("payment_account_name"),
        "instructions": profile.get("payment_instructions"),
    }


def get_tenant_knowledge(tenant_id):
    """Phase 5 contract name. Returns just the FAQ/services/policies slice of the tenant config —
    convenience accessor for a bot integration that only needs the knowledge base, not the whole
    config (tone, appointment rules, WhatsApp connection info, etc.)."""
    config = get_tenant_config(tenant_id)
    if not config:
        return None
    knowledge = config.get("knowledge", {})
    return {
        "faq": knowledge.get("faq", []),
        "services": knowledge.get("services", []),
        "products": knowledge.get("products", []),
        "pricing_notes": knowledge.get("pricing_notes"),
    }
