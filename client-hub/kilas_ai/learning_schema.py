"""Additive Learning-only schema, independent of Translator releases."""
import hashlib
from pathlib import Path
import db


def apply_release():
    backend = 'postgres' if db.BACKEND == 'postgres' else 'sqlite'
    script = (Path(__file__).parents[1] / 'migrations' / ('0093_kilas_learning_' + backend + '.sql')).read_text(encoding='utf-8')
    digest = hashlib.sha256(script.encode()).hexdigest()
    if backend == 'sqlite':
        conn = db.sqlite3.connect(db.SQLITE_PATH)
        try:
            conn.executescript(script)
        finally:
            conn.close()
        return
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute('SELECT pg_advisory_xact_lock(74109301)')
            cur.execute('CREATE TABLE IF NOT EXISTS kilas_learning_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            cur.execute("SELECT checksum FROM kilas_learning_releases WHERE name='0093'")
            row = cur.fetchone()
            if row and row[0] != digest:
                raise RuntimeError('learning_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute("INSERT INTO kilas_learning_releases VALUES ('0093',%s)", (digest,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
