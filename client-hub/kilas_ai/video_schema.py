"""Only the explicitly authorized additive Video release, never historical migrations."""
import hashlib
from pathlib import Path
import db

NAME='0082_kilas_video'


def apply_release():
    if db.BACKEND!='postgres':return []  # SQLite installs through db.MIGRATIONS.
    script=(Path(__file__).resolve().parent.parent/'migrations'/(NAME+'_postgres.sql')).read_text(encoding='utf-8')
    digest=hashlib.sha256(script.encode()).hexdigest()
    conn=db.psycopg2.connect(db.DATABASE_URL,**db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute('SET LOCAL lock_timeout = \'10s\'')
            cur.execute('SELECT pg_advisory_xact_lock(74108201)')
            cur.execute('CREATE TABLE IF NOT EXISTS kilas_video_releases (name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM kilas_video_releases WHERE name=%s',(NAME,))
            row=cur.fetchone()
            if row and row[0]!=digest:raise RuntimeError('video_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO kilas_video_releases VALUES (%s,%s)',(NAME,digest))
        conn.commit()
        return [] if row else [NAME]
    except Exception:
        conn.rollback();raise
    finally:conn.close()
