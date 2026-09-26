"""Explicit additive customer schema installer.

Never called on normal application boot. Applies the Phase 3 base schema (0056) and the
current additive relationship-stage (0062) and Customer Insight (0063) extensions against an
explicitly authorized target. All migrations are idempotent; no existing customer rows are deleted.
"""
from pathlib import Path
import db
from public_chat.store import transaction


def _apply(filename):
    sql = (Path(__file__).resolve().parents[1] / "migrations" / filename).read_text()
    with transaction() as tx:
        for statement in sql.split(";"):
            if statement.strip():
                tx.execute(statement)


def apply_schema():
    _apply(f"0056_kilas_core_customers_{db.BACKEND}.sql")
    _apply(f"0062_kilas_customer_stages_{db.BACKEND}.sql")
    _apply(f"0063_customer_insights_{db.BACKEND}.sql")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    apply_schema()
    print("Kilas Core Customers + stages + insights additive schema applied; legacy migrations were not run.")
