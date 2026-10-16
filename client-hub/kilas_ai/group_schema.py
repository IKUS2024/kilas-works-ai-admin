"""Checksum-guarded additive group schema; reverting code preserves all history."""
import hashlib
from pathlib import Path
import db
NAME = '0099_kilas_group_chat'

def apply_release():
    if db.BACKEND != 'postgres': return []
    script = (Path(__file__).resolve().parent.parent/'migrations'/(NAME+'_postgres.sql')).read_text()
    digest = hashlib.sha256(script.encode()).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(74109901)')
            cur.execute('CREATE TABLE IF NOT EXISTS kilas_group_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM kilas_group_releases WHERE name=%s', (NAME,))
            row = cur.fetchone()
            if row and row[0] != digest: raise RuntimeError('group_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO kilas_group_releases VALUES (%s,%s)', (NAME,digest))
        conn.commit()
        return [] if row else [NAME]
    except Exception:
        conn.rollback()
        raise
    finally: conn.close()
