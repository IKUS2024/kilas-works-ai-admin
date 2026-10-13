"""Additive Learning-only schema, independent of Translator releases."""
import hashlib
import json
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
        apply_transport_release()
        report_readiness()
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
    apply_transport_release()
    report_readiness()


def report_readiness():
    # Learning-only configuration reads after schema setup; no provider dispatch.
    from . import learning
    try:
        report=learning.readiness()
    except Exception:
        report={'report_available':False}
    try:
        print('KILAS_LEARNING_READINESS '+json.dumps(report,sort_keys=True),flush=True)
    except OSError:
        pass  # A diagnostic output failure must not interrupt the working service.


def apply_transport_release():
    """Independent nullable readiness marker; old rows, PCM and cost unchanged."""
    backend='postgres' if db.BACKEND=='postgres' else 'sqlite'
    script=(Path(__file__).parents[1]/'migrations'/('0096_kilas_learning_transport_'+backend+'.sql')).read_text(encoding='utf-8')
    digest=hashlib.sha256(script.encode()).hexdigest()
    conn=db.psycopg2.connect(db.DATABASE_URL,**db._postgres_connect_kwargs()) if backend=='postgres' else db.sqlite3.connect(db.SQLITE_PATH)
    try:
        if backend=='sqlite':
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS kilas_learning_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            row=conn.execute("SELECT checksum FROM kilas_learning_releases WHERE name='0096'").fetchone()
            if row and row[0]!=digest:raise RuntimeError('learning_transport_checksum_mismatch')
            if not row:
                columns={v[1] for v in conn.execute('PRAGMA table_info(kilas_learning_inputs)')}
                if 'provider_ready_at' not in columns:conn.execute(script)
                conn.execute("INSERT INTO kilas_learning_releases VALUES ('0096',?)",(digest,))
        else:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout = '10s'");cur.execute('SELECT pg_advisory_xact_lock(74109301)')
                cur.execute("SELECT checksum FROM kilas_learning_releases WHERE name='0096'");row=cur.fetchone()
                if row and row[0]!=digest:raise RuntimeError('learning_transport_checksum_mismatch')
                if not row:
                    cur.execute(script);cur.execute("INSERT INTO kilas_learning_releases VALUES ('0096',%s)",(digest,))
        conn.commit()
    except Exception:
        conn.rollback();raise
    finally:conn.close()
