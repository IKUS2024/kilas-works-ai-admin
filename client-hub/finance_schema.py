"""Apply only the approved additive Finance release, atomically and once per checksum."""
import hashlib
from pathlib import Path
import db
NAME = '0100_finance_approved_revisions'

def apply_release():
    if db.BACKEND != 'postgres':
        return []  # SQLite uses the normal idempotent development migration list.
    script = (Path(__file__).parent/'migrations'/(NAME+'_postgres.sql')).read_text()
    digest = hashlib.sha256(script.encode()).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(74110001)')
            cur.execute('CREATE TABLE IF NOT EXISTS finance_release_migrations(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM finance_release_migrations WHERE name=%s', (NAME,))
            row = cur.fetchone()
            if row and row[0] != digest:
                raise RuntimeError('finance_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO finance_release_migrations VALUES (%s,%s)', (NAME,digest))
        conn.commit()
        return [] if row else [NAME]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
