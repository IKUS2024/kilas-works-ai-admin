"""Explicit additive customer relationship-stage schema installer.

Never called on normal application boot. Apply migration 0062 only after Phase 3
customer schema 0056 exists. Existing customer records are preserved as CUSTOMER;
new inbound contacts are created as LEAD by the application after this migration.
"""
from pathlib import Path
import db
from public_chat.store import transaction


def apply_schema():
    sql = (Path(__file__).resolve().parents[1] / "migrations" /
           f"0062_kilas_customer_stages_{db.BACKEND}.sql").read_text()
    with transaction() as tx:
        for statement in sql.split(";"):
            if statement.strip():
                tx.execute(statement)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    parser.parse_args()
    apply_schema()
    print("Kilas customer stages additive schema applied; legacy migrations were not run.")
