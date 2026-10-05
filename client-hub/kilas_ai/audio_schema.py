"""Checksum-idempotent, explicitly scoped additive Audio release only."""
import hashlib
from pathlib import Path
import db

NAME = '0083_kilas_audio'


def apply_release(name=NAME):
    if name not in (NAME, '0084_kilas_personal_voice', '0085_kilas_voice_preview', '0086_kilas_voice_library'):raise ValueError('invalid_audio_release')
    if db.BACKEND!='postgres':return []
    script=(Path(__file__).resolve().parent.parent/'migrations'/(name+'_postgres.sql')).read_text(encoding='utf-8')
    digest=hashlib.sha256(script.encode()).hexdigest()
    conn=db.psycopg2.connect(db.DATABASE_URL,**db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute('SELECT pg_advisory_xact_lock(74108301)')
            cur.execute('CREATE TABLE IF NOT EXISTS kilas_audio_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM kilas_audio_releases WHERE name=%s',(name,))
            row=cur.fetchone()
            if row and row[0]!=digest:raise RuntimeError('audio_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO kilas_audio_releases VALUES (%s,%s)',(name,digest))
        conn.commit();return [] if row else [name]
    except Exception:
        conn.rollback();raise
    finally:conn.close()
