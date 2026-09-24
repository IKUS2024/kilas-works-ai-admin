"""Explicit additive Phase 3 customer schema installer.

Never called on normal application boot. Apply only migration 0056 against an explicitly
authorized target after Phase 2 schema 0055 exists.
"""
from pathlib import Path
import db
from public_chat.store import transaction


def apply_schema():
    sql = (Path(__file__).resolve().parents[1] / "migrations" /
           f"0056_kilas_core_customers_{db.BACKEND}.sql").read_text()
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
    print("Kilas Core Customers additive schema applied; legacy migrations were not run.")
