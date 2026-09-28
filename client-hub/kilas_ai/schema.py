"""Explicit, checksum-guarded production migration for Kilas AI only."""
import hashlib
from pathlib import Path

import db

NAME = "0071_kilas_ai_v1"


def apply_release():
    if db.BACKEND != "postgres":
        raise RuntimeError("kilas_ai_release_requires_postgres")
    script = (Path(__file__).resolve().parent.parent / "migrations" / (NAME + "_postgres.sql")).read_text(encoding="utf-8")
    checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(74107101)")
            cur.execute("""CREATE TABLE IF NOT EXISTS kilas_ai_schema_releases (
                name TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            cur.execute("SELECT checksum FROM kilas_ai_schema_releases WHERE name=%s", (NAME,))
            row = cur.fetchone()
            if row:
                if row[0] != checksum:
                    raise RuntimeError("kilas_ai_release_checksum_mismatch")
                conn.commit()
                return False
            cur.execute(script)
            cur.execute("INSERT INTO kilas_ai_schema_releases(name,checksum) VALUES (%s,%s)", (NAME, checksum))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("Kilas AI additive schema applied" if apply_release() else "Kilas AI additive schema already current")
