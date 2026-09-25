"""Explicit additive installer; never called during application boot or public requests.

Use only against a separately authorized target DB:
  python -m public_chat.schema --apply
This reads only migration 0055, never db.init_schema / the legacy migration registry.
"""
from pathlib import Path
import db
from .store import transaction


def apply_schema():
    sql = (Path(__file__).resolve().parents[1] / "migrations" /
           f"0055_public_web_chat_{db.BACKEND}.sql").read_text()
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
    print("Public WEB additive schema applied; legacy migrations were not run.")
