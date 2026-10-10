"""Isolated QA metadata only; no customer quota, pricing, invoice or audio tables."""
import hashlib
from pathlib import Path
import db
from . import usage
from .autonomous_store import transaction

NAME = 'kilas_live_owner_qa_v1'


def apply():
    body = Path(__file__).with_suffix('.sql').read_text()
    digest = hashlib.sha256(body.encode()).hexdigest()
    with transaction() as conn:
        if db.BACKEND == 'postgres':
            usage._query(conn, "SET LOCAL lock_timeout = '5s'")
            usage._query(conn, 'SELECT pg_advisory_xact_lock(74108803)')
        usage._query(conn, 'CREATE TABLE IF NOT EXISTS kilas_live_qa_releases(name TEXT PRIMARY KEY, checksum TEXT NOT NULL)')
        old = usage._query(conn, 'SELECT checksum FROM kilas_live_qa_releases WHERE name=?', (NAME,), one=True)
        if old:
            if old[0] != digest:
                raise RuntimeError('live_qa_schema_checksum_mismatch')
            return
        for statement in body.split(';'):
            if statement.strip():
                usage._query(conn, statement)
        usage._query(conn, 'INSERT INTO kilas_live_qa_releases(name,checksum) VALUES (?,?)', (NAME, digest))
