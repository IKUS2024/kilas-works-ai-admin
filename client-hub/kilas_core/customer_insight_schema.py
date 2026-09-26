"""Explicit additive Customer Insight schema installer (0063).

Never called on ordinary boot. Production enables the dedicated one-shot env gate for
one deploy, then turns it off again.
"""
from pathlib import Path
import db
from public_chat.store import transaction


def apply_schema():
    sql = (Path(__file__).resolve().parents[1] / "migrations" /
           f"0063_customer_insights_{db.BACKEND}.sql").read_text()
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
    print("Customer Insight additive schema 0063 applied.")
