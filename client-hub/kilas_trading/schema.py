"""Only Trader additive migration; atomic, checksum guarded, no historical migrations."""
import hashlib
import sqlite3
from pathlib import Path
import db

NAME = '0087_kilas_trading'


def apply_release():
    suffix = 'postgres' if db.BACKEND == 'postgres' else 'sqlite'
    script = (Path(__file__).resolve().parents[1] / 'migrations' / (NAME + '_' + suffix + '.sql')).read_text()
    digest = hashlib.sha256(script.encode()).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs()) if db.BACKEND == 'postgres' else sqlite3.connect(db.SQLITE_PATH, timeout=5)
    try:
        if db.BACKEND == 'postgres':
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='10s'")
                cur.execute('SELECT pg_advisory_xact_lock(74108701)')
                cur.execute('CREATE TABLE IF NOT EXISTS kilas_trading_releases(name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
                cur.execute('SELECT checksum FROM kilas_trading_releases WHERE name=%s', (NAME,))
                row = cur.fetchone()
                if row and row[0] != digest:
                    raise RuntimeError('trading_schema_checksum_mismatch')
                if not row:
                    cur.execute(script)
                    cur.execute('INSERT INTO kilas_trading_releases VALUES (%s,%s)', (NAME, digest))
        else:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS kilas_trading_releases(name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
            row = conn.execute('SELECT checksum FROM kilas_trading_releases WHERE name=?', (NAME,)).fetchone()
            if row and row[0] != digest:
                raise RuntimeError('trading_schema_checksum_mismatch')
            if not row:
                for statement in script.split(';'):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute('INSERT INTO kilas_trading_releases VALUES (?,?)', (NAME, digest))
        conn.commit()
        return [] if row else [NAME]
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
