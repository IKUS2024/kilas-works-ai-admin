"""Service catalog — Business Hub V2, Phase B.

Single source of truth for pricing shown anywhere in the app: pricing_config.py defines the
canonical figures, this module seeds them into service_catalog (idempotently — safe to call on
every boot, like db.init_schema()) and provides the only read/write functions any route should use.
Never hardcode a price in a template or route — always go through here.
"""
import json

import db
import pricing_config


def seed_catalog_if_needed():
    """Idempotent: inserts any catalog_key from pricing_config.py that doesn't exist yet. Does NOT
    overwrite an existing row's price/name — if Kilas Works wants to change a price, that happens
    via the admin catalog-edit screen (routes_admin.py), not by re-seeding. This function only
    ever adds rows that are missing, so pricing_config.py additions (e.g. a brand new service)
    show up automatically on next boot without clobbering any admin edits already made to existing
    ones."""
    for item in pricing_config.CATALOG_ITEMS:
        existing = db.query_one("SELECT id FROM service_catalog WHERE catalog_key = ?", (item["key"],))
        if existing is None:
            db.execute(
                "INSERT INTO service_catalog (catalog_key, category, name, pricing_mode, "
                "price_amount, price_unit) VALUES (?, ?, ?, ?, ?, ?)",
                (item["key"], item["category"], item["name"], item["pricing_mode"],
                 item["price_amount"], item["price_unit"]),
            )


def list_active_catalog():
    return db.query_all(
        "SELECT * FROM service_catalog WHERE is_active = ? ORDER BY category, sort_order, name",
        (True,),
    )


def list_all_catalog():
    return db.query_all("SELECT * FROM service_catalog ORDER BY category, sort_order, name")


def get_catalog_item(catalog_key):
    return db.query_one("SELECT * FROM service_catalog WHERE catalog_key = ?", (catalog_key,))


def get_catalog_item_by_id(catalog_id):
    return db.query_one("SELECT * FROM service_catalog WHERE id = ?", (catalog_id,))


class InvalidCatalogState(Exception):
    pass


def update_catalog_item(catalog_id, price_amount=None, price_unit=None, is_active=None,
                         description=None, name=None, cta_text=None, sort_order=None,
                         pricing_mode=None):
    """Admin-only edit path (Section 20 / Final Operations Polish Section 6: 'admin actions' must
    not require code/DB changes for routine operations). Only touches fields explicitly passed —
    None means "leave unchanged".

    PRICE CHANGE SAFETY (Final Operations Polish, Section 7): this function only ever touches the
    service_catalog row itself. It NEVER reaches into projects/quotations/invoices to update a
    historical final_price — those are already copied onto the project at creation time
    (projects_repo.create_fixed_price_project copies catalog_item['price_amount'] into
    projects.final_price once, at checkout time) and are never re-read from the catalog afterwards.
    Changing a price here only affects future `create_fixed_price_project()` calls, which read the
    catalog fresh each time — existing orders/invoices/approved quotations are structurally
    unreachable from this function and keep their original amount forever.

    Raises InvalidCatalogState (Section 6: 'Do not allow invalid pricing state') if the requested
    change would leave the item as FIXED_PRICE/STARTING_FROM with no price, or as CUSTOM_QUOTE with
    a price still set (which would look like a real, checkout-able number to a customer)."""
    row = get_catalog_item_by_id(catalog_id)
    if row is None:
        return None
    new_price_amount = row["price_amount"] if price_amount is None else price_amount
    new_price_unit = row["price_unit"] if price_unit is None else price_unit
    new_is_active = row["is_active"] if is_active is None else is_active
    new_description = row["description"] if description is None else description
    new_name = row["name"] if name is None else name
    new_cta_text = row["cta_text"] if cta_text is None else cta_text
    new_sort_order = row["sort_order"] if sort_order is None else sort_order
    new_pricing_mode = row["pricing_mode"] if pricing_mode is None else pricing_mode

    if new_pricing_mode not in pricing_config.VALID_PRICING_MODES:
        raise InvalidCatalogState(f"invalid_pricing_mode: {new_pricing_mode!r}")
    if new_pricing_mode in ("FIXED_PRICE", "STARTING_FROM") and not new_price_amount:
        raise InvalidCatalogState("fixed_price_requires_amount: harga wajib diisi untuk mode harga tetap")
    if new_pricing_mode == "CUSTOM_QUOTE":
        # Never let a CUSTOM_QUOTE item carry a leftover number — that would read as a real,
        # checkout-able price to a customer even though the flow always goes through quotation.
        new_price_amount = None
        new_price_unit = None

    db.execute(
        "UPDATE service_catalog SET name = ?, price_amount = ?, price_unit = ?, is_active = ?, "
        "description = ?, cta_text = ?, sort_order = ?, pricing_mode = ?, "
        "updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE service_catalog SET name = ?, price_amount = ?, price_unit = ?, is_active = ?, "
        "description = ?, cta_text = ?, sort_order = ?, pricing_mode = ?, "
        "updated_at = now() WHERE id = ?",
        (new_name, new_price_amount, new_price_unit, bool(new_is_active), new_description,
         new_cta_text, new_sort_order, new_pricing_mode, catalog_id),
    )
    try:
        import catalog_cache
        catalog_cache.bump_version()
    except Exception:
        pass
    return get_catalog_item_by_id(catalog_id)


def format_price(price_amount, price_unit):
    if price_amount is None:
        return "Custom Quote"
    formatted = f"Rp{price_amount:,}".replace(",", ".")
    return f"{formatted} {price_unit}" if price_unit else formatted
