"""Disposable local PostgreSQL rehearsal of the explicit additive Kilas AI release."""
import os
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get("KILAS_AI_POSTGRES_QA") != "1" or urlsplit(os.environ.get("DATABASE_URL", "")).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("Explicit disposable loopback PostgreSQL required")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from kilas_ai import schema  # noqa: E402


def main():
    isolated = "kilas_ai_qa_" + uuid.uuid4().hex
    control = db.psycopg2.connect(db.DATABASE_URL)
    control.autocommit = True
    with control.cursor() as cursor:
        cursor.execute("CREATE SCHEMA " + isolated)
    original_options = db._postgres_connect_kwargs

    def options():
        value = original_options()
        return dict(value, options=value["options"] + " -c search_path=" + isolated)

    try:
        with patch.object(db, "_postgres_connect_kwargs", side_effect=options):
            baseline = [item for item in db.MIGRATIONS if not item[0].startswith(("0071_", "0072_", "0073_"))]
            with patch.object(db, "MIGRATIONS", baseline):
                db.init_schema()
            before = {row["table_name"] for row in db.query_all(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
            assert not any(name.startswith("kilas_ai_") for name in before)
            assert schema.apply_release() == ["0071_kilas_ai_v1", "0072_kilas_ai_usage_status", "0073_kilas_ai_topups"]
            assert schema.apply_release() == []
            after = {row["table_name"] for row in db.query_all(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
            assert before.issubset(after)
            assert after - before == {"kilas_ai_threads", "kilas_ai_messages", "kilas_ai_attachments",
                                      "kilas_ai_usage", "kilas_ai_subscriptions", "kilas_ai_invoices",
                                      "kilas_ai_payments", "kilas_ai_topup_orders", "kilas_ai_topup_credits",
                                      "kilas_ai_topup_debits", "kilas_ai_schema_releases"}
            fields = {row["column_name"] for row in db.query_all(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='kilas_ai_usage'")}
            assert {"status", "quota_source"}.issubset(fields)
    finally:
        with control.cursor() as cursor:
            cursor.execute("DROP SCHEMA " + isolated + " CASCADE")
        control.close()
    print("Kilas AI explicit PostgreSQL schema applied once and preserved all baseline tables")


if __name__ == "__main__":
    main()
