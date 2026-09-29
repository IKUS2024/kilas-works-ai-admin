"""Disposable PostgreSQL rehearsal of the additive Automation schema."""
import os
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get("KILAS_AI_POSTGRES_QA") != "1" or urlsplit(os.environ.get("DATABASE_URL", "")).hostname not in ("localhost", "127.0.0.1"):
    raise SystemExit("Explicit disposable loopback PostgreSQL required")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from kilas_ai import automation_schema  # noqa: E402


def main():
    isolated = "kilas_automation_qa_" + uuid.uuid4().hex
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
            baseline = [item for item in db.MIGRATIONS if not item[0].startswith("0075_")]
            with patch.object(db, "MIGRATIONS", baseline):
                db.init_schema()
            before = {row["table_name"] for row in db.query_all(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
            assert automation_schema.apply_release() == [automation_schema.NAME]
            assert automation_schema.apply_release() == []
            after = {row["table_name"] for row in db.query_all(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
            assert before.issubset(after)
            assert after - before == {"kilas_automation_settings", "kilas_automations",
                                      "kilas_automation_runs", "kilas_automation_schema_releases"}
    finally:
        with control.cursor() as cursor:
            cursor.execute("DROP SCHEMA " + isolated + " CASCADE")
        control.close()
    print("Automation migration applied once without changing baseline tables")


if __name__ == "__main__":
    main()
