"""Required, additive and checksum-guarded authentication metadata."""
import hashlib
from pathlib import Path
import db

NAME = '0097_customer_auth_sessions'


def apply():
    script=(Path(__file__).resolve().parent/'migrations'/(NAME+'_'+db.BACKEND+'.sql')).read_text()
    digest=hashlib.sha256(script.encode()).hexdigest()
    if db.BACKEND=='sqlite':
        conn=db.get_connection()
        conn.execute('CREATE TABLE IF NOT EXISTS customer_auth_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
        row=conn.execute('SELECT checksum FROM customer_auth_releases WHERE name=?',(NAME,)).fetchone()
        if row and row[0]!=digest:raise RuntimeError('customer_auth_schema_checksum_mismatch')
        conn.executescript(script)
        conn.execute('INSERT INTO customer_auth_releases(name,checksum) VALUES (?,?) ON CONFLICT(name) DO NOTHING',(NAME,digest))
        conn.commit()
        return not bool(row)
    conn=db.psycopg2.connect(db.DATABASE_URL,**db._postgres_connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(74109721)')
            cur.execute('CREATE TABLE IF NOT EXISTS customer_auth_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
            cur.execute('SELECT checksum FROM customer_auth_releases WHERE name=%s',(NAME,))
            row=cur.fetchone()
            if row and row[0]!=digest:raise RuntimeError('customer_auth_schema_checksum_mismatch')
            if not row:
                cur.execute(script)
                cur.execute('INSERT INTO customer_auth_releases(name,checksum) VALUES (%s,%s)',(NAME,digest))
        conn.commit()
        return not bool(row)
    except Exception:
        conn.rollback();raise
    finally:conn.close()
