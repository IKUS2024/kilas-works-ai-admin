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
