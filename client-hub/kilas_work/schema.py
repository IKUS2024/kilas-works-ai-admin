"""Opt-in, checksum-guarded Kilas Work schema release for PostgreSQL."""
import hashlib
from pathlib import Path

import db

NAME = "0074_kilas_work_v1"


def apply_release():
    if db.BACKEND != "postgres":
        raise RuntimeError("kilas_work_release_requires_postgres")
    script = (Path(__file__).resolve().parent.parent / "migrations" / (NAME + "_postgres.sql")).read_text(encoding="utf-8")
    checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(74107401)")
            cur.execute("""CREATE TABLE IF NOT EXISTS kilas_work_schema_releases (
                name TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            cur.execute("SELECT checksum FROM kilas_work_schema_releases WHERE name=%s", (NAME,))
            row = cur.fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError("kilas_work_release_checksum_mismatch")
                conn.commit()
                return []
            cur.execute(script)
            cur.execute("INSERT INTO kilas_work_schema_releases(name,checksum) VALUES (%s,%s)", (NAME, checksum))
        conn.commit()
        return [NAME]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
