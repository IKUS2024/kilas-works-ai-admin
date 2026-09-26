"""Explicit additive Customer Insight schema installer. Never runs on normal boot."""
from pathlib import Path
import db
from public_chat.store import transaction


def apply_schema():
    sql=(Path(__file__).resolve().parents[1]/"migrations"/f"0063_customer_insights_{db.BACKEND}.sql").read_text()
    with transaction() as tx:
        for statement in sql.split(";"):
            if statement.strip():
                tx.execute(statement)


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply",action="store_true",required=True)
    p.parse_args()
    apply_schema()
    print("Customer Insight additive schema applied.")
