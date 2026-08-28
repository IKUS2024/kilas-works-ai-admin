"""External final-audit regression: Client Hub SQL must be executable on PostgreSQL.

This test intentionally imports only db.py, so it can run without Flask.
"""
import os
import sys
from pathlib import Path

CLIENT_HUB = Path(__file__).resolve().parents[1]
if str(CLIENT_HUB) not in sys.path:
    sys.path.insert(0, str(CLIENT_HUB))

os.environ.pop("DATABASE_URL", None)
import db  # noqa: E402


def test_postgres_adapter_translates_placeholders_and_sqlite_now_expression():
    old_backend = db.BACKEND
    try:
        db.BACKEND = "postgres"
        sql = "UPDATE payments SET status = ?, updated_at = datetime('now') WHERE id = ?"
        adapted = db._adapt_placeholders(sql)
        assert adapted == "UPDATE payments SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    finally:
        db.BACKEND = old_backend


def test_sqlite_adapter_preserves_sqlite_expression_exactly():
    old_backend = db.BACKEND
    try:
        db.BACKEND = "sqlite"
        sql = "UPDATE payments SET status = ?, updated_at = datetime('now') WHERE id = ?"
        assert db._adapt_placeholders(sql) == sql
    finally:
        db.BACKEND = old_backend
