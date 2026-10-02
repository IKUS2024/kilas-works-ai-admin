"""Explicit, checksum-protected additive release; never runs on ordinary PG boot."""
import hashlib
from pathlib import Path
import db

NAME = '0078_kilas_autonomous_agent'


def apply_release():
    if db.BACKEND != 'postgres':
        raise RuntimeError('autonomous_release_requires_postgres')
    script = (Path(__file__).resolve().parent.parent / 'migrations' / (NAME + '_postgres.sql')).read_text(encoding='utf-8-sig')
    digest = hashlib.sha256(script.encode()).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(74107801)')
            cur.execute('CREATE TABLE IF NOT EXISTS kilas_autonomous_schema_releases (name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM kilas_autonomous_schema_releases WHERE name=%s', (NAME,))
            row = cur.fetchone()
            if row and row[0] != digest:
                raise RuntimeError('autonomous_release_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO kilas_autonomous_schema_releases VALUES (%s,%s)', (NAME, digest))
        conn.commit()
        return [] if row else [NAME]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
