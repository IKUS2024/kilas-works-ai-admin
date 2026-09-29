"""Disposable PostgreSQL rehearsal for the additive Work release only."""
import os
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get("KILAS_WORK_POSTGRES_QA") != "1" or urlsplit(os.environ.get("DATABASE_URL", "")).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("Explicit disposable loopback PostgreSQL required")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from kilas_work import schema  # noqa: E402


def main():
    isolated = "kilas_work_qa_" + uuid.uuid4().hex
    control = db.psycopg2.connect(db.DATABASE_URL)
    control.autocommit = True
    with control.cursor() as cursor:
        cursor.execute("CREATE SCHEMA " + isolated)
    original = db._postgres_connect_kwargs

    def options():
        value = original()
        return dict(value, options=value["options"] + " -c search_path=" + isolated)

    try:
        with patch.object(db, "_postgres_connect_kwargs", side_effect=options):
            baseline = [item for item in db.MIGRATIONS if not item[0].startswith("0074_")]
            with patch.object(db, "MIGRATIONS", baseline):
                db.init_schema()
            before = {row["table_name"] for row in db.query_all(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
            assert schema.apply_release() == ["0074_kilas_work_v1"]
            assert schema.apply_release() == []
            after = {row["table_name"] for row in db.query_all(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
            assert before.issubset(after)
            expected = {"kilas_work_accounts", "kilas_work_subscriptions", "kilas_work_orders",
                        "kilas_work_credits", "kilas_work_threads", "kilas_work_messages",
                        "kilas_work_files", "kilas_work_jobs", "kilas_work_usage",
                        "kilas_work_topup_debits", "kilas_work_schema_releases"}
            assert after - before == expected, after - before
    finally:
        with control.cursor() as cursor:
            cursor.execute("DROP SCHEMA " + isolated + " CASCADE")
        control.close()
    print("Kilas Work schema applied once; all baseline tables preserved")


if __name__ == "__main__":
    main()
