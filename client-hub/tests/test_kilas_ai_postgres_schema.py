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
from kilas_ai import schema, store  # noqa: E402


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
            # Foundation-only rehearsal excludes later AI migrations too: their foreign
            # keys require the deliberately absent Agent/Automation schema.
            baseline = [item for item in db.MIGRATIONS if not item[0].startswith(("0071_", "0072_", "0073_", "0075_", "0076_", "0077_", "0078_", "0079_", "0080_", "0081_"))]
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

            # Exercise the real psycopg2 driver: literal image/% in a parameterized
            # query previously raised IndexError before any provider could run.
            owner = db.insert_returning_id(
                "INSERT INTO users(email,password_hash,role) VALUES (?,?,?)",
                ("image-owner@example.test", "synthetic-hash", "CLIENT_OWNER"))
            other = db.insert_returning_id(
                "INSERT INTO users(email,password_hash,role) VALUES (?,?,?)",
                ("image-other@example.test", "synthetic-hash", "CLIENT_OWNER"))
            thread_id = store.create_thread(owner, "FAST")
            assert store.recent_image(owner, thread_id) is None
            assert store.latest_user_image(owner, thread_id) is None
            message_id, created = store.append_user_once(
                owner, thread_id, "Synthetic image", "FAST", "pg-image-query-operation")
            assert created
            raw = b"synthetic image query fixture"
            store.save_attachments(owner, thread_id, message_id, [{
                "filename": "synthetic.png", "mime_type": "image/png",
                "byte_size": len(raw), "content": raw, "extracted_text": ""}])
            for lookup in (store.recent_image, store.latest_user_image):
                row = lookup(owner, thread_id)
                assert row["filename"] == "synthetic.png" and row["mime_type"] == "image/png"
                assert bytes(row["content"]) == raw
                assert lookup(other, thread_id) is None
            # Preserve the existing four-message image-context window.
            for index in range(4):
                store.append_user_once(owner, thread_id, "Later message", "FAST", "pg-later-" + str(index))
            assert store.recent_image(owner, thread_id) is None
            assert store.latest_user_image(owner, thread_id)["filename"] == "synthetic.png"
    finally:
        with control.cursor() as cursor:
            cursor.execute("DROP SCHEMA " + isolated + " CASCADE")
        control.close()
    print("Kilas AI PostgreSQL schema and owned image-context queries passed with real psycopg2")


if __name__ == "__main__":
    main()
