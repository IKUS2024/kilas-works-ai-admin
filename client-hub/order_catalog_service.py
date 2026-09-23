"""Kilas Order curated marketplace catalog.

Customer-facing reads deliberately project only public fields. Supplier platform, seller,
source URL, source price, shipping estimate, fee estimate, and service fee stay internal.
"""
import db

PUBLIC_COLUMNS = (
    "product_code,name,short_description,category,customer_price_idr,"
    "availability_status,source_checked_at,sort_order"
)


def _row(row):
    return dict(row) if row else None


def list_public_products(limit=24):
    try:
        limit=max(1,min(int(limit),60))
    except (TypeError,ValueError):
        limit=24
    rows=db.query_all(
        f"SELECT {PUBLIC_COLUMNS} FROM kilas_order_catalog "
        "WHERE is_active=TRUE ORDER BY sort_order ASC,id ASC LIMIT ?",
        (limit,),
    )
    return [_row(row) for row in rows]


def get_public_product(product_code):
    code=str(product_code or "").strip().upper()
    if not code:
        return None
    return _row(db.query_one(
        f"SELECT {PUBLIC_COLUMNS} FROM kilas_order_catalog "
        "WHERE product_code=? AND is_active=1 LIMIT 1",
        (code,),
    ))


def get_internal_product(product_code):
    """Owner/backend-only full row. Never pass this object into a customer template."""
    code=str(product_code or "").strip().upper()
    if not code:
        return None
    return _row(db.query_one(
        "SELECT * FROM kilas_order_catalog WHERE product_code=? LIMIT 1",
        (code,),
    ))


def list_internal_products(limit=100):
    try:
        limit=max(1,min(int(limit),200))
    except (TypeError,ValueError):
        limit=100
    return [_row(row) for row in db.query_all(
        "SELECT * FROM kilas_order_catalog ORDER BY is_active DESC,sort_order ASC,id ASC LIMIT ?",
        (limit,),
    )]


def customer_price_text(product):
    value=int((product or {}).get("customer_price_idr") or 0)
    return "Rp{:,.0f}".format(value).replace(",", ".")
