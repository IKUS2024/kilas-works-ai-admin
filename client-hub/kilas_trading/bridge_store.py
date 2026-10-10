"""Isolated, explicitly installed bridge state. No paper or account-data writes."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3
import db
from .store import query

NAME = 'kilas_trading_bridge_v1'

@contextmanager
def transaction():
    conn = (db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs())
            if db.BACKEND == 'postgres' else sqlite3.connect(db.SQLITE_PATH, timeout=5))
    try:
        if db.BACKEND == 'postgres':
            query(conn, "SET LOCAL lock_timeout='5s'")
            query(conn, 'SELECT pg_advisory_xact_lock(74108702)')
        else:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def apply_release():
    """Manual migration only; never run by app startup or pairing."""
    suffix = 'postgres' if db.BACKEND == 'postgres' else 'sqlite'
    script = (Path(__file__).resolve().parents[1] / 'migrations' / f'{NAME}_{suffix}.sql').read_text()
    digest = hashlib.sha256(script.encode()).hexdigest()
    with transaction() as conn:
        query(conn, 'CREATE TABLE IF NOT EXISTS kilas_trading_bridge_releases(name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
        row = query(conn, 'SELECT checksum FROM kilas_trading_bridge_releases WHERE name=?', (NAME,), one=True)
        if row and row['checksum'] != digest:
            raise RuntimeError('bridge_schema_checksum_mismatch')
        if not row:
            for statement in script.split(';'):
                if statement.strip(): query(conn, statement)
            query(conn, 'INSERT INTO kilas_trading_bridge_releases VALUES (?,?)', (NAME, digest))
    return [] if row else [NAME]

if __name__ == '__main__':
    import os
    if os.environ.get('KILAS_TRADING_BRIDGE_SCHEMA_APPLY') != 'true':
        raise SystemExit('Explicit bridge schema release flag required.')
    print(apply_release())
