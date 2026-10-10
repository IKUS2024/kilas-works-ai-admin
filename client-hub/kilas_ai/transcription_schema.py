"""Independent additive migration; existing content release checksums are untouched."""
import hashlib
from pathlib import Path
import db
from . import usage
from .autonomous_store import transaction

NAME = 'kilas_chat_transcription_v1'


def apply():
    suffix = 'postgres' if db.BACKEND == 'postgres' else 'sqlite'
    body = Path(__file__).with_name('transcription_schema_' + suffix + '.sql').read_text()
    digest = hashlib.sha256(body.encode()).hexdigest()
    with transaction() as conn:
        if db.BACKEND == 'postgres':
            usage._query(conn, "SET LOCAL lock_timeout = '10s'")
            usage._query(conn, 'SELECT pg_advisory_xact_lock(74108802)')
        old = usage._query(conn, 'SELECT checksum FROM kilas_content_releases WHERE name=?', (NAME,), one=True)
        if old and old[0] != digest:
            raise RuntimeError('transcription_schema_checksum_mismatch')
        if old:
            return
        usage._query(conn, body)
        usage._query(conn, 'INSERT INTO kilas_content_releases(name,checksum) VALUES (?,?)', (NAME, digest))
