"""Checksum-guarded additive Chat preferences; no other product tables altered."""
import hashlib
from pathlib import Path
import db


def apply_release(name='0102_kilas_chat_models'):
    if name not in ('0102_kilas_chat_models','0103_kilas_image_models','0105_kilas_workspace_streams'):raise ValueError('invalid_chat_schema')
    if db.BACKEND != 'postgres': return
    script=(Path(__file__).resolve().parent.parent/'migrations'/(name+'_postgres.sql')).read_text()
    digest=hashlib.sha256(script.encode()).hexdigest()
    conn=db.psycopg2.connect(db.DATABASE_URL,**db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='10s'")
            cur.execute('SELECT pg_advisory_xact_lock(74110201)')
            cur.execute('CREATE TABLE IF NOT EXISTS kilas_ai_chat_model_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM kilas_ai_chat_model_releases WHERE name=%s',(name,))
            row=cur.fetchone()
            if row and row[0]!=digest:raise RuntimeError('chat_model_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO kilas_ai_chat_model_releases VALUES (%s,%s)',(name,digest))
        conn.commit()
    except Exception:
        conn.rollback();raise
    finally:conn.close()
