"""Checksum-guarded, additive content release. Startup calls only for enabled features."""
import hashlib
from pathlib import Path
import db

NAME = 'kilas_content_projects_and_chat_v1'


def apply_release():
    suffix = 'postgres' if db.BACKEND == 'postgres' else 'sqlite'
    body = '\n'.join((Path(__file__).parent / (name + '_' + suffix + '.sql')).read_text()
                     for name in ('content_schema', 'chat_content_schema'))
    digest = hashlib.sha256(body.encode()).hexdigest()
    conn = db.psycopg2.connect(db.DATABASE_URL, **db._postgres_connect_kwargs()) if db.BACKEND == 'postgres' else db.get_connection()
    try:
        cursor = conn.cursor()
        if db.BACKEND == 'postgres':
            cursor.execute("SET LOCAL lock_timeout = '10s'")
            cursor.execute('SELECT pg_advisory_xact_lock(74108801)')
        else:
            cursor.execute('BEGIN IMMEDIATE')
        cursor.execute('CREATE TABLE IF NOT EXISTS kilas_content_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
        cursor.execute('SELECT checksum FROM kilas_content_releases WHERE name=' + ('%s' if db.BACKEND == 'postgres' else '?'), (NAME,))
        old = cursor.fetchone()
        if old and old[0] != digest:
            raise RuntimeError('content_schema_checksum_mismatch')
        if not old:
            if db.BACKEND == 'postgres':
                cursor.execute(body)
            else:
                for statement in body.split(';'):
                    if statement.strip():
                        cursor.execute(statement)
            params = '%s,%s' if db.BACKEND == 'postgres' else '?,?'
            cursor.execute('INSERT INTO kilas_content_releases(name,checksum) VALUES (' + params + ')', (NAME, digest))
        conn.commit()
        return [] if old else [NAME]
    except Exception:
        conn.rollback()
        raise
    finally:
        if db.BACKEND == 'postgres':
            conn.close()


def apply_disposable_sqlite(disposable_root):
    root = Path(disposable_root).resolve()
    path = Path(db.SQLITE_PATH).resolve()
    if db.BACKEND != 'sqlite' or not root.is_relative_to('/tmp') or not path.is_relative_to(root):
        raise RuntimeError('content_prototype_requires_disposable_sqlite')
    conn = db.get_connection()
    conn.executescript((Path(__file__).parent / 'content_schema_sqlite.sql').read_text())
    conn.executescript((Path(__file__).parent / 'chat_content_schema_sqlite.sql').read_text())
    conn.commit()
