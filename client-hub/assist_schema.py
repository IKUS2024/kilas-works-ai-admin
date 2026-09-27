"""Explicit additive Assist release migration; never replay historical Finance migrations."""
import hashlib
from pathlib import Path
import db

MIGRATIONS = (
    '0066_assist_demo',
    '0067_assist_usage_provider',
    '0068_assist_connections',
    '0069_assist_media_analysis',
)


def apply_release():
    if db.BACKEND != 'postgres':
        raise RuntimeError('assist_release_requires_postgres')
    # Independent transaction: safe for parallel web worker boots and all-or-nothing DDL.
    conn=db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    applied=[]
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(74103669)')
            cur.execute('''CREATE TABLE IF NOT EXISTS kw_assist_schema_releases (
                name TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
            for name in MIGRATIONS:
                script=(Path(__file__).parent/'migrations'/(name+'_postgres.sql')).read_text()
                checksum=hashlib.sha256(script.encode()).hexdigest()
                cur.execute('SELECT checksum FROM kw_assist_schema_releases WHERE name=%s',(name,))
                prior=cur.fetchone()
                if prior:
                    if prior[0] != checksum:
                        raise RuntimeError('assist_release_checksum_mismatch')
                    continue
                cur.execute(script)
                cur.execute('INSERT INTO kw_assist_schema_releases(name,checksum) VALUES (%s,%s)',(name,checksum))
                applied.append(name)
        conn.commit()
        return applied
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
