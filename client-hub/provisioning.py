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
import os

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
EVENT_WHATSAPP_VALIDATED = "WHATSAPP_VALIDATED"
EVENT_WHATSAPP_VALIDATION_FAILED = "WHATSAPP_VALIDATION_FAILED"


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
            # Pro tenant parity cycle (Task 3) — appointment booking requires BOTH the package
            # capability (features.appointment, Pro-only per feature_flags.FEATURE_MATRIX) AND
            # this tenant's own opt-in toggle (business_profiles.appointment_enabled, migration
            # 0012) — a Pro tenant can still choose not to have the bot book appointments for it.
            "meeting_enabled": bool(features.get("appointment")) and bool(profile.get("appointment_enabled", True)),
            "meeting_types": [],
            "business_hours_raw": profile.get("operating_hours"),
            "closed_days": profile.get("closed_days"),
            "appointment_rules": profile.get("appointment_rules_raw"),
        },

        # Pro tenant parity cycle (Task 4) — THIS tenant's OWN bank/payment details, for THAT
        # business's own customers to pay THAT business directly. Completely separate from, and
        # never a substitute for, Kilas Works' own PAYMENT_CONFIG/BCA account (../app.py), which
        # is used only for Kilas Works' own subscription billing and is untouched by this cycle.
        # Gated at read-time by feature_flags' payment_conversation (Pro-only); a Basic tenant's
        # profile can still hold these fields (e.g. entered before a downgrade) but the bot must
        # never surface them unless payment_conversation is actually enabled for this tenant.
        "payment_config": {
            "bank_name": profile.get("payment_bank_name"),
            "account_number": profile.get("payment_account_number"),
            "account_name": profile.get("payment_account_name"),
            "instructions": profile.get("payment_instructions"),
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
    # Task 8 — credentials_reference is OPTIONAL here too, same reasoning as
    # validate_and_connect_whatsapp() above: empty means "shares Kilas Works' own default token".
    if not phone_number_id:
        raise ProvisioningError("missing_whatsapp_config: phone_number_id is required")

    repo.upsert_whatsapp_config(business_id, phone_number_id, waba_id, credentials_reference,
                                 connection_status="PENDING_VALIDATION")
    repo.write_audit(actor["id"], business_id, EVENT_WHATSAPP_CONNECTED,
                      f"phone_number_id={phone_number_id}")


def validate_and_connect_whatsapp(business_id, actor, phone_number_id, waba_id, credentials_reference):
    """Multi-tenant runtime safety cycle (Task A) — this is the function the admin route should
    call instead of trusting connect_whatsapp_credentials() alone to flip a tenant "connected".
    connect_whatsapp_credentials() only ever RECORDS what an admin typed in (status
    PENDING_VALIDATION, per its own docstring) — it has never itself confirmed the Phone Number ID
    is real, reachable, or not already claimed by a different tenant. This function adds that real
    check before anything is treated as CONNECTED:

      1. Uniqueness: repo.find_business_id_by_phone_number_id() — this exact Phone Number ID must
         not already belong to a DIFFERENT tenant. Pure DB check, no network needed.
      2. Live reachability (best-effort): a simple GET against Meta's Graph API for this Phone
         Number ID, using the server-side credential the credentials_reference pointer names (the
         actual secret is READ from this process's own environment here — NEVER logged, NEVER put
         in the audit description, NEVER returned to the caller). Any failure at all — the env var
         isn't set on this process, a network/DNS/timeout error, a non-2xx Graph API response, or
         any other exception — is treated identically: validation FAILS SAFE. There is no code path
         in this function that reaches CONNECTED without a live 2xx Graph API response.

    Returns {"status": "CONNECTED" or "VALIDATION_FAILED", "reason": <safe, credential-free string>}.
    Never raises for a validation failure (that is an expected outcome, not an error) — only
    ProvisioningError for actor/business-state problems (not admin, business not found, missing
    required fields), matching every other function in this module.
    """
    _require_admin(actor)
    business = repo.get_business(business_id)
    if not business:
        raise ProvisioningError("business_not_found")
    # Task 8 — credentials_reference is now OPTIONAL: leaving it empty means this tenant shares
    # Kilas Works' own default server-side WHATSAPP_ACCESS_TOKEN (the common case — this tenant's
    # phone number lives under the same Meta Business Portfolio/WABA Kilas Works already manages),
    # so onboarding does NOT require adding a brand-new Render env var per client. Only a genuinely
    # separate Meta app/token needs a distinct credentials_reference recorded. phone_number_id is
    # always required — see app.py's _get_tenant_whatsapp_channel_safe for the full design note.
    if not phone_number_id:
        raise ProvisioningError("missing_whatsapp_config: phone_number_id is required")

    duplicate_owner = repo.find_business_id_by_phone_number_id(phone_number_id, exclude_business_id=business_id)
    if duplicate_owner is not None:
        repo.upsert_whatsapp_config(business_id, phone_number_id, waba_id, credentials_reference,
                                     connection_status="VALIDATION_FAILED")
        repo.write_audit(actor["id"], business_id, EVENT_WHATSAPP_VALIDATION_FAILED,
                          f"phone_number_id={phone_number_id} reason=duplicate_phone_number_id "
                          f"already_assigned_to_business_id={duplicate_owner}")
        return {"status": "VALIDATION_FAILED",
                "reason": "duplicate_phone_number_id: already connected to a different business"}

    # Record the attempt as PENDING_VALIDATION first (same shape as connect_whatsapp_credentials),
    # so a tenant that never reaches a final CONNECTED/VALIDATION_FAILED verdict below (e.g. this
    # function raising for an unrelated reason) is still visibly "in progress", never silently
    # left on stale prior data.
    repo.upsert_whatsapp_config(business_id, phone_number_id, waba_id, credentials_reference,
                                 connection_status="PENDING_VALIDATION")
    repo.write_audit(actor["id"], business_id, EVENT_WHATSAPP_CONNECTED,
                      f"phone_number_id={phone_number_id}")

    reachable, reason = _check_whatsapp_phone_number_reachable(phone_number_id, credentials_reference)
    if not reachable:
        repo.mark_whatsapp_validation_failed(business_id)
        repo.write_audit(actor["id"], business_id, EVENT_WHATSAPP_VALIDATION_FAILED,
                          f"phone_number_id={phone_number_id} reason={reason}")
        return {"status": "VALIDATION_FAILED", "reason": reason}

    repo.mark_whatsapp_validated(business_id)
    repo.write_audit(actor["id"], business_id, EVENT_WHATSAPP_VALIDATED,
                      f"phone_number_id={phone_number_id}")
    return {"status": "CONNECTED", "reason": "validated"}


def _check_whatsapp_phone_number_reachable(phone_number_id, credentials_reference):
    """Best-effort live check against Meta's Graph API that this Phone Number ID is real and
    reachable using the server-side credential `credentials_reference` points at. Deliberately
    fails safe on every error path — a network error, a missing/invalid credential, a timeout, or
    a non-2xx response are all treated the same way (return False), never raised, and the actual
    access-token VALUE is never included in the returned reason string (only the pointer NAME,
    which is not a secret).

    Known limitation (see final report): this sandboxed environment has no internet-reachable Meta
    Graph API credentials, so the success path (a real 2xx response) cannot be exercised
    end-to-end here — the failure paths (missing env var, network error) are exactly what actually
    execute in this environment, which is the intended fail-safe behavior.

    Task 8 — an empty/None credentials_reference means this tenant shares Kilas Works' own default
    WHATSAPP_ACCESS_TOKEN (see app.py's _get_tenant_whatsapp_channel_safe docstring for the full
    design decision); only a non-empty reference is resolved as a distinct per-tenant env var."""
    if credentials_reference:
        access_token = os.environ.get(credentials_reference, "")
        if not access_token:
            return False, f"credentials_reference '{credentials_reference}' has no value set in this environment"
    else:
        access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        if not access_token:
            return False, "shared default WHATSAPP_ACCESS_TOKEN has no value set in this environment"
    try:
        import requests
        url = f"https://graph.facebook.com/v21.0/{phone_number_id}"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "id"},
            timeout=8,
        )
        if resp.status_code == 200:
            return True, "ok"
        return False, f"graph_api_status_{resp.status_code}"
    except Exception as e:
        return False, f"graph_api_error: {type(e).__name__}"


def activate_tenant(business_id, actor):
    """Phase 4's `activate_tenant(business_id)`. Idempotent: calling this on an already-ACTIVE
    tenant returns {"changed": False} rather than erroring or writing a duplicate audit row.

    Requires, in order: business APPROVED, WhatsApp connected (businesses.whatsapp_connected==1 —
    the existing V1 gate), a tenant_configs row already provisioned, a VERIFIED AI Admin payment,
    and (Fix 3, production-safety patch) — for an AI Admin package — a successfully created/
    ensured subscription row. Only after ALL of those succeed does businesses.status flip to
    ACTIVE. Raises ProvisioningError naming exactly which precondition failed (never a bare
    assert) so the admin UI can show a useful message; a subscription-setup failure aborts
    activation the same way any other precondition failure does — see the subscription-creation
    block below for the full fail-closed rationale.
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

    # Business Hub V2, Phase C (Section 22): "Never activate an unpaid tenant." Bug fix: requires an
    # explicit VERIFIED payment tied to an AI Admin project — "no invoice/payment row at all" is
    # NEVER treated as "already covered" (see payment_service.has_verified_ai_admin_payment()'s
    # docstring). Already-ACTIVE tenants are unaffected — this function returns before reaching this
    # gate whenever business["status"] == "ACTIVE" already (see the early-return above).
    import payment_service
    if not payment_service.has_verified_ai_admin_payment(business_id):
        raise ProvisioningError(
            "payment_not_verified: this tenant has no VERIFIED payment for an AI Admin plan yet"
        )

    # Fix 3 (production-safety patch) — the subscription row must be created/ensured
    # SUCCESSFULLY *before* the business is ever flipped to ACTIVE. This function used to call
    # repo.activate_business() FIRST and only attempt subscription creation afterward, inside a
    # swallowed try/except — a subscription-creation failure there would silently leave
    # businesses.status=ACTIVE with NO subscription row at all: a fully "live" AI Admin tenant
    # with zero billing-lifecycle enforcement. That gap is closed here: subscription setup now
    # happens FIRST, and if it fails, the ProvisioningError PROPAGATES (never swallowed) —
    # activation ABORTS entirely, business.status stays exactly what it was (still APPROVED,
    # never touched), and nothing else this function doesn't otherwise touch (the verified
    # payment row, onboarding data, WhatsApp config, AI settings, business profile, any
    # creative-service projects) is affected in any way, since none of those are written by this
    # function regardless of where in it an error occurs.
    #
    # A business whose package is "NONE" (no AI Admin at all — creative-services-only) has no
    # subscription concept and is correctly skipped here (plan_key stays None) — activation
    # proceeds exactly as before for that case.
    import subscription_service
    plan_key = subscription_service.plan_key_for_package(business.get("package"))
    if plan_key:
        try:
            subscription_service.create_subscription(business_id, plan_key, actor_user_id=actor["id"])
        except Exception as e:
            # Deliberately generic in the raised message (never echoes exception internals that
            # could contain a DB connection string or similar) — the real error is only ever
            # Micro-patch: log only safe operational context (business_id + a generic failure
            # code) — never the raw exception value/message, which could contain a DB connection
            # string, credential, or other internal detail depending on what failed underneath.
            print(
                f"provisioning.activate_tenant: SUBSCRIPTION_SETUP_FAILED "
                f"(business_id={business_id}) — AKTIVASI DIBATALKAN, business TETAP "
                f"{business['status']!r} (bukan ACTIVE), tidak ada data yang dihapus/diubah."
            )
            raise ProvisioningError(
                "subscription_setup_failed: gagal menyiapkan subscription AI Admin untuk tenant ini — "
                "aktivasi DIBATALKAN. Data pembayaran/onboarding/WhatsApp/AI setup tetap aman dan "
                "tidak berubah. Coba lagi; kalau terus gagal, cek log server."
            )

    # If repo.activate_business() ITSELF fails below (e.g. a DB error on this specific write),
    # the exception propagates unhandled (never caught here) — business.status remains whatever
    # it was before this call (still APPROVED, since the early-return for already-ACTIVE happened
    # above and this line is only reached once). A subscription row may already exist at that
    # point (created just above) — that is harmless and NOT "an accidentally usable paid tenant":
    # every tenant-resolution path in this codebase (resolve_tenant_id_by_whatsapp_phone_number_id
    # and every other tenant_config_service.py function) requires businesses.status == 'ACTIVE'
    # FIRST, so an orphaned subscription row on a non-ACTIVE business grants zero runtime access
    # on its own. No special rollback of that row is needed or performed.
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
