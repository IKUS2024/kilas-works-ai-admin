"""Provisioning layer (Phase 4) — the safe boundary between Client Hub's onboarding UI and the
tenant configuration a future multi-tenant AI Admin runtime would consume.

This module deliberately does NOT send WhatsApp messages, does NOT touch the production bot, and
does NOT talk to Meta's API. It only assembles/validates/stores a tenant's configuration and moves
its activation state forward, all through existing `repo.py` calls (still the only place SQL is
written) plus its own audit-event constants layered on top of repo.py's existing audit calls.

Every function here is:
  - IDEMPOTENT: calling it again with no relevant state change is a safe no-op (see each
    function's docstring for exactly what "no change" means for it).
  - AUDITABLE: every state-changing call writes one of the canonical event names below, in
    addition to whatever repo.py's own lower-level functions already log (kept for backward
    compatibility with the V1 test suite, which asserts some of those older action strings).
  - REVERSIBLE where the domain allows it: deactivate_tenant() is the reverse of activate_tenant();
    there is deliberately no "un-provision" (the config snapshot is just superseded by the next
    provision_tenant() call, never deleted — same "don't destroy history" principle as
    onboarding_sessions in repo.py).
"""
import repo
import feature_flags

# Canonical provisioning event names (Phase 4's exact list). These are ADDITIONAL audit_log rows
# layered on top of repo.py's existing lower-level action strings (e.g. "approved", "activated") —
# both are written so nothing that already depended on the old strings breaks, while giving the
# future bot-integration/analytics layer one consistent vocabulary to filter on.
EVENT_BUSINESS_SUBMITTED = "BUSINESS_SUBMITTED"
EVENT_BUSINESS_APPROVED = "BUSINESS_APPROVED"
EVENT_TENANT_PROVISIONED = "TENANT_PROVISIONED"
EVENT_WHATSAPP_CONNECTED = "WHATSAPP_CONNECTED"
EVENT_TENANT_ACTIVATED = "TENANT_ACTIVATED"
EVENT_TENANT_DEACTIVATED = "TENANT_DEACTIVATED"


class ProvisioningError(Exception):
    """Raised for an invalid state transition or a failed validation. Routes catch this and show
    the message via flash() — never a raw traceback."""


def _require_admin(actor):
    """Defense-in-depth: routes are already guarded by @security.admin_required, but every
    provisioning function re-checks the actor's role itself, so calling this module directly
    (e.g. from a script, or a future internal API) can never skip the check by accident."""
    if not actor or actor.get("role") != "KILAS_ADMIN":
        raise PermissionError("Only KILAS_ADMIN may perform this provisioning action.")


def record_business_submitted(business_id, actor_user_id):
    """Called right after repo.set_business_status(..., 'READY_FOR_REVIEW', ...) when a client
    submits onboarding. Purely an additional audit event — no state change of its own."""
    repo.write_audit(actor_user_id, business_id, EVENT_BUSINESS_SUBMITTED, None)


def validate_tenant_config(business_id):
    """Returns (ok: bool, errors: list[str]). Does not raise — callers decide what to do with a
    failed validation (provision_tenant() raises ProvisioningError; the admin UI can instead show
    the error list inline)."""
    errors = []
    business = repo.get_business(business_id)
    if not business:
        return False, ["business_not_found"]

    missing = repo.required_fields_missing(business_id)
    if missing:
        errors.append(f"missing_required_fields:{','.join(missing)}")

    ai_settings = repo.get_ai_settings(business_id)
    if not ai_settings or ai_settings.get("ai_status") != "DONE":
        errors.append("ai_setup_not_done")

    if not feature_flags.is_valid_package(business["package"]):
        errors.append("invalid_package")

    features = repo.get_tenant_features(business_id)
    if not features:
        errors.append("tenant_features_missing")

    return (len(errors) == 0), errors


def build_tenant_config(business_id):
    """Assembles the Phase 2 tenant configuration model from raw+normalized data already in the
    DB. This is a pure function of what's stored — it never calls Claude itself (that already
    happened earlier, in ai_onboarding.normalize_business_data(), during onboarding) and never
    invents a value that isn't already present, consistent with section 8/32 of the original
    onboarding request ("AI must not invent facts")."""
    business = repo.get_business(business_id)
    if not business:
        raise ProvisioningError("business_not_found")

    profile = repo.get_business_profile(business_id) or {}
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)
    ai_settings = repo.get_ai_settings(business_id) or {}
    features = repo.get_tenant_features(business_id) or {}
    whatsapp = repo.get_whatsapp_config(business_id) or {}
    normalized = ai_settings.get("normalized_config") or {}

    return {
        "tenant_id": business_id,
        "business_name": business["business_name"],
        "business_type": profile.get("category"),
        "owner_user_id": None,  # filled in by callers that have the membership row; see note below
        "status": business["status"],

        "ai": {
            "language": {
                "primary": profile.get("primary_language") or "id",
                "additional": profile.get("additional_languages") or [],
            },
            "tone": profile.get("tone") or "friendly",
            "system_instructions": normalized.get("description") or profile.get("short_description"),
            "business_description": profile.get("short_description"),
            "customer_salutation": profile.get("customer_salutation") or "Kak",
        },

        "business_info": {
            "address": profile.get("address"),
            "business_hours": {
                "raw": profile.get("operating_hours"),
                "closed_days": profile.get("closed_days"),
            },
            "contact_info": {
                "business_phone": profile.get("business_phone"),
                "owner_name": profile.get("owner_name"),
            },
        },

        "knowledge": {
            "faq": [
                {"question": f["question"] or f["raw_input"], "answer": f["answer"],
                 "needs_review": bool(f["needs_review"])}
                for f in faqs
            ],
            "products": [],  # V1 has no separate "products" vs "services" distinction — see services
            "services": [
                {
                    "raw_input": s["raw_input"], "service_name": s["service_name"],
                    "price_from": s["price_from"], "price_to": s["price_to"],
                    "currency": s["currency"], "needs_review": bool(s["needs_review"]),
                }
                for s in services
            ],
            "pricing_notes": "Never invent a price not present above — mark unknown instead.",
            "catalog_references": [],  # file ids are looked up separately via repo.list_business_files
        },

        "lead_behavior": {
            "qualification_questions": normalized.get("missing_fields") or [],
            "lead_fields": ["name", "phone", "interest"],
            "handoff_rules": "Escalate to trusted owner phone on explicit purchase intent or when asked for the owner.",
        },

        "appointment_behavior": {
            "meeting_enabled": bool(features.get("appointment")),
            "meeting_types": [],
            "appointment_rules": profile.get("appointment_rules_raw"),
        },

        "feature_plan": {
            "package": business["package"],
            "features": {k: bool(features.get(k, False)) for k in feature_flags.ALL_FEATURE_KEYS},
        },

        "whatsapp": {
            "connection_status": whatsapp.get("connection_status", "NOT_CONNECTED"),
            "phone_number_id": whatsapp.get("phone_number_id"),
            "waba_id": whatsapp.get("waba_id"),
            # Deliberately the reference name only — never the token itself. The bot runtime is
            # expected to resolve this reference (e.g. an env var lookup) at send-time, server-side.
            "credentials_reference": whatsapp.get("credentials_reference"),
        },
    }


def provision_tenant(business_id, actor):
    """Phase 4's `provision_tenant(business_id)`. Requires the business to already be APPROVED (or
    further along, e.g. ACTIVE — re-provisioning an active tenant, say after an admin edits its
    FAQ, is allowed and expected). Builds the tenant config, validates it, and stores it as a new
    version — unless the assembled config is byte-identical to what's already stored, in which
    case this is a no-op (idempotent — see repo.save_tenant_config's `changed` return value).

    Returns {"config_version": int, "changed": bool, "config": dict}.
    Raises ProvisioningError if the business isn't in a provisionable state or fails validation.
    """
    _require_admin(actor)

    business = repo.get_business(business_id)
    if not business:
        raise ProvisioningError("business_not_found")
    if business["status"] not in ("APPROVED", "ACTIVE"):
        raise ProvisioningError(
            f"invalid_state_transition: cannot provision a business in status {business['status']!r} "
            "— it must be APPROVED (or already ACTIVE, for re-provisioning) first."
        )

    ok, errors = validate_tenant_config(business_id)
    if not ok:
        raise ProvisioningError(f"validation_failed: {'; '.join(errors)}")

    config = build_tenant_config(business_id)
    version, changed = repo.save_tenant_config(business_id, config)

    if changed:
        repo.write_audit(actor["id"], business_id, EVENT_TENANT_PROVISIONED, f"config_version={version}")

    return {"config_version": version, "changed": changed, "config": config}


def connect_whatsapp_credentials(business_id, actor, phone_number_id, waba_id, credentials_reference):
    """Phase 2/4: records WhatsApp connection info. Still 100% manual — this function does not
    call Meta's API and does not itself flip the tenant to CONNECTED; it records the values an
    admin typed in as PENDING_VALIDATION. A separate, explicit validation step (not implemented in
    this phase — see final report) would call Meta's API to confirm the phone_number_id/waba_id
    are real and reachable before flipping to CONNECTED via repo.mark_whatsapp_validated(). For
    now, the existing V1 behavior (businesses.whatsapp_connected=1 immediately) is preserved
    alongside this new table for backward compatibility — see repo.upsert_whatsapp_config's
    caller in routes_admin.py.
    """
    _require_admin(actor)
    business = repo.get_business(business_id)
    if not business:
        raise ProvisioningError("business_not_found")
    if not phone_number_id or not credentials_reference:
        raise ProvisioningError("missing_whatsapp_config: phone_number_id and credentials_reference are required")

    repo.upsert_whatsapp_config(business_id, phone_number_id, waba_id, credentials_reference,
                                 connection_status="PENDING_VALIDATION")
    repo.write_audit(actor["id"], business_id, EVENT_WHATSAPP_CONNECTED,
                      f"phone_number_id={phone_number_id}")


def activate_tenant(business_id, actor):
    """Phase 4's `activate_tenant(business_id)`. Idempotent: calling this on an already-ACTIVE
    tenant returns {"changed": False} rather than erroring or writing a duplicate audit row.

    Requires, in order: business APPROVED, WhatsApp connected (businesses.whatsapp_connected==1 —
    the existing V1 gate), and a tenant_configs row already provisioned. Raises ProvisioningError
    naming exactly which precondition failed (never a bare assert) so the admin UI can show a
    useful message.
    """
    _require_admin(actor)
    business = repo.get_business(business_id)
    if not business:
        raise ProvisioningError("business_not_found")

    if business["status"] == "ACTIVE":
        return {"changed": False, "status": "ACTIVE"}

    if business["status"] != "APPROVED":
        raise ProvisioningError(
            f"invalid_state_transition: business must be APPROVED before activation (current status: {business['status']!r})"
        )
    if not business["whatsapp_connected"]:
        raise ProvisioningError("missing_whatsapp_config: connect WhatsApp before activating")

    config_row = repo.get_tenant_config_row(business_id)
    if not config_row:
        raise ProvisioningError("not_provisioned: call provision_tenant() before activating")

    repo.activate_business(business_id, actor["id"])
    repo.write_audit(actor["id"], business_id, EVENT_TENANT_ACTIVATED, f"config_version={config_row['config_version']}")
    return {"changed": True, "status": "ACTIVE"}


def deactivate_tenant(business_id, actor):
    """Phase 4's `deactivate_tenant(business_id)`. Idempotent: no-op if already SUSPENDED."""
    _require_admin(actor)
    business = repo.get_business(business_id)
    if not business:
        raise ProvisioningError("business_not_found")

    if business["status"] == "SUSPENDED":
        return {"changed": False, "status": "SUSPENDED"}

    repo.deactivate_business(business_id, actor["id"])
    repo.write_audit(actor["id"], business_id, EVENT_TENANT_DEACTIVATED, None)
    return {"changed": True, "status": "SUSPENDED"}


def approve_and_provision(business_id, actor):
    """Convenience wrapper used by routes_admin.approve(): runs the existing repo.approve_business
    (unchanged V1 behavior — business.status becomes APPROVED) immediately followed by
    provision_tenant() (Phase 4's "SYSTEM creates tenant configuration" step), so an admin's single
    "Approve" click both approves AND provisions in one action, exactly as the requested flow
    describes (CLIENT submits -> ADMIN reviews -> approves -> SYSTEM creates tenant configuration).
    Kept as a separate function (rather than folding into repo.approve_business) so approval and
    provisioning remain independently callable/testable, per Phase 4's own idempotency/testability
    requirements.
    """
    _require_admin(actor)
    repo.approve_business(business_id, actor["id"])
    repo.write_audit(actor["id"], business_id, EVENT_BUSINESS_APPROVED, None)
    return provision_tenant(business_id, actor)
