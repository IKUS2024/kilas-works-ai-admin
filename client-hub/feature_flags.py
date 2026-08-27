"""Centralized Basic/Pro feature matrix (Phase 3 — Plan Feature Flags).

This is the single source of truth for what each package unlocks. It exists as its own module
(rather than living inline in repo.py, where it started in V1) specifically so that:
  - it can be imported by repo.py (to seed tenant_features when a business is created/repackaged),
  - by provisioning.py (to validate a tenant config before activation),
  - and by tenant_config_service.py (the interface the future bot integration will call) —
without any of those three needing to depend on each other for this.

DESIGN RULE (explicit in the request): features are controlled by CONFIGURATION here, never by
copying application code per client, and never enforced only through prompt wording — every
feature name below corresponds to a boolean column in the `tenant_features` table (see
migrations/0001_init_sqlite.sql), and the (future) bot integration is expected to check
`tenant_config_service.get_tenant_features(tenant_id)` before allowing a Pro-only behavior for a
given tenant, not infer capability from what the system prompt happens to say.

Pricing is NOT decided here and NOT duplicated here — see PACKAGE_PRICING_DISPLAY_ONLY below, which
mirrors (does not replace) the existing production bot's PRICING_CONFIG figures purely for display
in the Client Hub UI. Changing Kilas Works' actual commercial pricing must still happen in the
production bot's PRICING_CONFIG; nothing in this file is a pricing source of truth.
"""

PACKAGES = ("AI_ADMIN_BASIC", "AI_ADMIN_PRO")

# Every feature flag that exists in the tenant_features table. Keep this list and the table's
# columns in sync — feature_flags.py, repo.py, and the migration file are the only three places
# that need to agree on this set.
ALL_FEATURE_KEYS = (
    "faq", "business_info", "catalog", "basic_lead_capture",
    "owner_commands", "advanced_history", "image_understanding", "voice_note",
    "lead_qualification", "appointment", "payment_conversation",
)

FEATURE_MATRIX = {
    "AI_ADMIN_BASIC": {
        "faq": True,
        "business_info": True,
        "catalog": True,
        "basic_lead_capture": True,
        "owner_commands": False,
        "advanced_history": False,
        "image_understanding": False,
        "voice_note": False,
        "lead_qualification": False,
        "appointment": False,
        "payment_conversation": False,
    },
    "AI_ADMIN_PRO": {
        # Pro = everything Basic has, plus every advanced capability. Written out explicitly
        # (not "**basic, **overrides") so this dict can be read top-to-bottom as the literal
        # matrix a human would compare against a pricing page.
        "faq": True,
        "business_info": True,
        "catalog": True,
        "basic_lead_capture": True,
        "owner_commands": True,
        "advanced_history": True,
        "image_understanding": True,
        "voice_note": True,
        "lead_qualification": True,
        "appointment": True,
        "payment_conversation": True,
    },
}

# Display-only mirror of the production bot's current PRICING_CONFIG figures (Rp499.000 /
# Rp999.000 per month), so the Client Hub UI can show a plan's price without inventing one. This
# is NOT the pricing source of truth — if Kilas Works' commercial pricing ever changes, the
# production bot's PRICING_CONFIG is what actually governs billing; this constant must be updated
# to match it by hand, it is not read from that file (the two apps do not share a database).
PACKAGE_PRICING_DISPLAY_ONLY = {
    "AI_ADMIN_BASIC": {"amount_idr": 499000, "label": "Rp499.000/bulan"},
    "AI_ADMIN_PRO": {"amount_idr": 999000, "label": "Rp999.000/bulan"},
}


def features_for_package(package):
    if package not in FEATURE_MATRIX:
        raise ValueError(f"unknown package {package!r} — must be one of {PACKAGES}")
    return dict(FEATURE_MATRIX[package])


def is_valid_package(package):
    return package in FEATURE_MATRIX
