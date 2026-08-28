"""Canonical Kilas Works pricing — Business Hub V2, Phase B (Section 5 of the master spec).

THIS is the single source of truth for the service_catalog table (see catalog_service.py's
seed_catalog_if_needed()). Nothing else in client-hub should hardcode a price — routes/templates
always read from service_catalog, which is seeded from here.

RELATIONSHIP TO THE PRODUCTION BOT'S PRICING_CONFIG (../app.py): the WhatsApp bot has its own
PRICING_CONFIG dict, already production-tested and explicitly NOT touched by any Client Hub cycle
(same "one platform, one codebase" principle the master spec asks for is aspirational for the
FUTURE bot integration — see BOT_INTEGRATION_GUIDE.md — but today these are two separate running
processes). The figures below are a deliberate, careful mirror of ../app.py's PRICING_CONFIG,
copied by hand from the master spec's Section 5 (which itself restates the bot's existing final
pricing). If Kilas Works prices ever change, BOTH this file and ../app.py's PRICING_CONFIG need
updating until Patch 2 of BOT_INTEGRATION_GUIDE.md is actually applied — that duplication is a
known, documented limitation (see the Phase B section of the final report), not an oversight.

pricing_mode:
    FIXED_PRICE     — exact price known up front, checkout can be immediate.
    STARTING_FROM    — a floor price shown publicly, but the concrete final price still depends on
                        scope (e.g. "Extra Page" is per-page, ".id + hosting" is a fixed annual
                        figure but positioned as a starting point in some bundles) — treated the
                        same as FIXED_PRICE for checkout purposes UNLESS explicitly marked
                        otherwise per item below (none currently are — reserved for future items).
    CUSTOM_QUOTE     — no public price; always goes through the quotation flow (Phase C).
"""

CATALOG_ITEMS = [
    # --- AI ADMIN ---
    {"key": "ai_admin_basic", "category": "AI_ADMIN", "name": "AI Admin Basic",
     "pricing_mode": "FIXED_PRICE", "price_amount": 499_000, "price_unit": "per bulan"},
    {"key": "ai_admin_pro", "category": "AI_ADMIN", "name": "AI Admin Pro",
     "pricing_mode": "FIXED_PRICE", "price_amount": 999_000, "price_unit": "per bulan"},

    # --- CONTENT ---
    {"key": "content_basic", "category": "CONTENT", "name": "Content Basic",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_500_000, "price_unit": "per bulan"},
    {"key": "content_growth", "category": "CONTENT", "name": "Content Growth",
     "pricing_mode": "FIXED_PRICE", "price_amount": 2_750_000, "price_unit": "per bulan"},
    {"key": "content_pro", "category": "CONTENT", "name": "Content Pro",
     "pricing_mode": "FIXED_PRICE", "price_amount": 4_250_000, "price_unit": "per bulan"},

    # --- BUNDLES (Content + AI Admin) ---
    {"key": "bundle_growth_ai_basic", "category": "BUNDLE", "name": "Growth + AI Basic",
     "pricing_mode": "FIXED_PRICE", "price_amount": 2_990_000, "price_unit": "per bulan"},
    {"key": "bundle_growth_ai_pro", "category": "BUNDLE", "name": "Growth + AI Pro",
     "pricing_mode": "FIXED_PRICE", "price_amount": 3_490_000, "price_unit": "per bulan"},
    {"key": "bundle_pro_ai_pro", "category": "BUNDLE", "name": "Pro + AI Pro",
     "pricing_mode": "FIXED_PRICE", "price_amount": 4_990_000, "price_unit": "per bulan"},

    # --- META ADS ---
    {"key": "ads_management", "category": "ADS", "name": "Meta Ads Management",
     "pricing_mode": "FIXED_PRICE", "price_amount": 799_000, "price_unit": "per bulan"},
    {"key": "ads_setup_only", "category": "ADS", "name": "Meta Ads Setup Only",
     "pricing_mode": "FIXED_PRICE", "price_amount": 399_000, "price_unit": "one time"},

    # --- AI + ADS ---
    {"key": "bundle_ai_basic_ads", "category": "BUNDLE", "name": "AI Basic + Ads",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_190_000, "price_unit": "per bulan"},
    {"key": "bundle_ai_pro_ads", "category": "BUNDLE", "name": "AI Pro + Ads",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_690_000, "price_unit": "per bulan"},

    # --- CONTENT + AI + ADS ---
    {"key": "bundle_growth_ai_pro_ads", "category": "BUNDLE", "name": "Growth + AI Pro + Ads",
     "pricing_mode": "FIXED_PRICE", "price_amount": 4_290_000, "price_unit": "per bulan"},
    {"key": "bundle_pro_ai_pro_ads", "category": "BUNDLE", "name": "Pro + AI Pro + Ads",
     "pricing_mode": "FIXED_PRICE", "price_amount": 5_790_000, "price_unit": "per bulan"},

    # --- WEBSITE ---
    {"key": "website_landing_page", "category": "WEBSITE", "name": "Landing Page",
     "pricing_mode": "FIXED_PRICE", "price_amount": 799_000, "price_unit": "one time"},
    {"key": "website_company_profile", "category": "WEBSITE", "name": "Company Profile Website",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_500_000, "price_unit": "one time"},
    {"key": "website_extra_page", "category": "WEBSITE", "name": "Extra Page",
     "pricing_mode": "FIXED_PRICE", "price_amount": 200_000, "price_unit": "per halaman"},
    {"key": "website_maintenance", "category": "WEBSITE", "name": "Maintenance",
     "pricing_mode": "FIXED_PRICE", "price_amount": 199_000, "price_unit": "per bulan"},
    {"key": "website_domain_com_hosting", "category": "WEBSITE", "name": ".com + Hosting",
     "pricing_mode": "FIXED_PRICE", "price_amount": 999_000, "price_unit": "per tahun"},
    {"key": "website_domain_id_hosting", "category": "WEBSITE", "name": ".id + Hosting",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_099_000, "price_unit": "per tahun"},

    # --- ADS + LANDING PAGE ---
    {"key": "bundle_ads_landing_page", "category": "BUNDLE", "name": "Ads + Landing Page",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_490_000, "price_unit": "bulan pertama (ad spend terpisah)"},

    # --- EVENT ---
    {"key": "event_standard", "category": "EVENT", "name": "Event Standard",
     "pricing_mode": "FIXED_PRICE", "price_amount": 1_200_000, "price_unit": "per event"},
    {"key": "event_lengkap", "category": "EVENT", "name": "Event Lengkap",
     "pricing_mode": "FIXED_PRICE", "price_amount": 2_800_000, "price_unit": "per event"},
    {"key": "event_premium", "category": "EVENT", "name": "Event Premium",
     "pricing_mode": "FIXED_PRICE", "price_amount": 4_400_000, "price_unit": "per event"},

    # --- CUSTOM QUOTE SERVICES (no public price; always via quotation flow) ---
    {"key": "custom_content", "category": "CONTENT", "name": "Custom Content Project",
     "pricing_mode": "CUSTOM_QUOTE", "price_amount": None, "price_unit": None},
    {"key": "custom_video", "category": "VIDEO", "name": "Custom Video Project",
     "pricing_mode": "CUSTOM_QUOTE", "price_amount": None, "price_unit": None},
    {"key": "custom_photo", "category": "PHOTO", "name": "Custom Photo Project",
     "pricing_mode": "CUSTOM_QUOTE", "price_amount": None, "price_unit": None},
    {"key": "custom_website_app", "category": "APPLICATION", "name": "Custom Website / Application",
     "pricing_mode": "CUSTOM_QUOTE", "price_amount": None, "price_unit": None},
    {"key": "talent_management", "category": "TALENT", "name": "Talent Management",
     "pricing_mode": "CUSTOM_QUOTE", "price_amount": None, "price_unit": None},
]

VALID_PRICING_MODES = ("FIXED_PRICE", "STARTING_FROM", "CUSTOM_QUOTE")
