"""Backend entitlement registry for Kilas Brain.

AI_ADMIN is the sole current paid plan and includes the existing Pro feature set.
Legacy Basic/Pro identifiers retain their historical entitlements and subscription compatibility;
NONE grants no AI features. New public purchases never select the legacy identifiers.
Commercial defaults live in pricing_config; current invoice prices come from service_catalog.
"""

PACKAGES = ("AI_ADMIN", "AI_ADMIN_BASIC", "AI_ADMIN_PRO", "NONE")

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
    # Ecosystem Sync (Section 2 / priority gap): a business that has NOT purchased AI Admin yet.
    # Registration must never force an AI Admin selection — a customer can create a business,
    # land on the dashboard, and buy any OTHER Kilas Works service (Content/Photo/Video/Website/
    # Ads/Event/Talent) without ever touching AI Admin. This sentinel package carries every
    # feature flag False (there is no AI behavior to gate) and is never billed. A business on this
    # package can later "upgrade" (see repo.upgrade_business_package) to a real AI Admin package,
    # at which point it goes through the normal onboarding wizard for the first time.
    "NONE": {
        "faq": False,
        "business_info": False,
        "catalog": False,
        "basic_lead_capture": False,
        "owner_commands": False,
        "advanced_history": False,
        "image_understanding": False,
        "voice_note": False,
        "lead_qualification": False,
        "appointment": False,
        "payment_conversation": False,
    },
}

# Legacy matrices are read compatibility, never a new-sales selection.
FEATURE_MATRIX["AI_ADMIN"] = dict(FEATURE_MATRIX["AI_ADMIN_PRO"])

# Current display default uses the canonical source; legacy amounts describe historical tiers.
from pricing_config import BRAIN_PLAN

PACKAGE_PRICING_DISPLAY_ONLY = {
    "AI_ADMIN": {"amount_idr": BRAIN_PLAN["harga"], "label": "Rp" + format(BRAIN_PLAN["harga"], ",").replace(",", ".") + "/bulan"},
    "AI_ADMIN_BASIC": {"amount_idr": 499000, "label": "Rp499.000/bulan"},
    "AI_ADMIN_PRO": {"amount_idr": 999000, "label": "Rp999.000/bulan"},
}


def features_for_package(package):
    if package not in FEATURE_MATRIX:
        raise ValueError(f"unknown package {package!r} — must be one of {PACKAGES}")
    return dict(FEATURE_MATRIX[package])


def is_valid_package(package):
    return package in FEATURE_MATRIX
