"""Absolute Final Production Patch — catalog cache invalidation.

A single-row version counter (`catalog_cache`, migration 0011). Bumped by catalog_service.py
(price/active-state edits) and talent_service.py (create/update/archive/reactivate) any time
something that could change the PUBLIC catalog PDF's content changes. live_catalog_pdf.py compares
this version against the version baked into its cached file and regenerates only when they differ
— so a normal request never pays PDF-generation cost, but an admin edit is reflected on the very
next request for the catalog, with no manual script to re-run.

Deliberately tiny and dependency-free (only db.py) so both catalog_service.py and talent_service.py
can import it without a circular import.
"""
import db


def get_version():
    row = db.query_one("SELECT version FROM catalog_cache WHERE id = 1")
    return row["version"] if row else 0


def bump_version():
    """Never raises — a cache-invalidation bug must never break the admin edit it's reacting to."""
    try:
        if db.BACKEND == "sqlite":
            db.execute(
                "UPDATE catalog_cache SET version = version + 1, updated_at = ? WHERE id = 1",
                (_now_sqlite(),),
            )
        else:
            db.execute("UPDATE catalog_cache SET version = version + 1, updated_at = now() WHERE id = 1")
    except Exception as e:
        print(f"catalog_cache.bump_version gagal (non-fatal, katalog live tetap fallback ke regenerate): {e}")


def _now_sqlite():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(sep=" ", timespec="seconds")
