"""One approved owner/session: cross-worker, non-refundable worst-case reservations.

Grant is a cost allowance, never an authentication credential. Audio, transcript,
facts and reply text stay outside this store. All failures are fail-closed.
"""
import hashlib
import os
import re
from datetime import datetime, timezone
import db
from . import usage
from .autonomous_store import transaction

OWNER_EMAIL = 'irvankarnavi@gmail.com'
GRANT = 'owner-live-qa-20261010-v1'
CAP = 100000  # integer micro-USD, USD 0.10 TOTAL, not per operation
TTL_MS = 120000
PRICE_VERSION = 'openai-official-20261010-standard'
PRICE_START_MS = int(datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp() * 1000)
PRICE_END_MS = int(datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp() * 1000)
STT_MODEL = 'gpt-4o-mini-transcribe'
TEXT_MODEL = 'gpt-6-luna'
# Official STT full 16k context @ $1.25/M + full 2k output @ $5/M.
# Deliberately reserve the FULL model bounds even for a <=10s WAV.
STT_RESERVE = 30000
# Text byte-BPE upper bound <=16,384 UTF-8 request bytes + protocol margin,
# reserved as 20,000 input tokens @ $0.125/M (includes cache-write premium)
# plus 512 completion/reasoning tokens @ $0.50/M; no tools, default tier.
TEXT_MAX_BYTES = 16384
TEXT_RESERVE = 2756
LIMITS = {'STT':12, 'TRANSLATE':12, 'REPLY':3}


class BudgetError(ValueError):
    pass


def enabled():
    return os.environ.get('KILAS_LIVE_ASSIST_QA_ENABLED', '').lower() in ('true','1','yes','on')


def _now(conn):
    sql = "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint" if db.BACKEND == 'postgres' else "SELECT CAST(strftime('%s','now') AS INTEGER)*1000"
    return int(usage._query(conn, sql, one=True)[0])


def _owner(conn, owner):
    row = usage._query(conn, 'SELECT email,role FROM users WHERE id=?', (owner,), one=True)
    return bool(row and str(row[0]).strip().casefold() == OWNER_EMAIL and row[1] == 'CLIENT_OWNER')


def allowed(owner):
    if not enabled() or owner is None:
        return False
    try:
        with transaction() as conn:
            return _owner(conn, owner)
    except Exception:
        return False


def ready(owner, *, for_start=False):
    if not enabled() or owner is None:
        return False
    try:
        with transaction() as conn:
            now = _now(conn)
            if not _owner(conn, owner) or not PRICE_START_MS <= now < PRICE_END_MS:
                return False
            if for_start:
                return not usage._query(conn, 'SELECT id FROM kilas_live_qa_grants WHERE id=?', (GRANT,), one=True)
            return True
    except Exception:
        return False


def _digest(token):
    if not isinstance(token, str) or not 24 <= len(token) <= 80:
        raise BudgetError('qa_invalid_session')
    return hashlib.sha256(token.encode()).hexdigest()


def claim(owner, token):
    if not enabled():
        raise BudgetError('qa_disabled')
    try:
        with transaction() as conn:
            now = _now(conn)
            if not _owner(conn, owner) or not PRICE_START_MS <= now < PRICE_END_MS:
                raise BudgetError('qa_not_authorized')
            # Fixed grant PK serializes starts from different workers. Its persisted
            # existence consumes this one session forever, including after restart.
            row = usage._query(conn, 'INSERT INTO kilas_live_qa_grants(id,user_id,session_digest,started_ms,deadline_ms,status) VALUES (?,?,?,?,?,\'ACTIVE\') ON CONFLICT(id) DO NOTHING RETURNING id',
                               (GRANT, owner, _digest(token), now, min(now+TTL_MS,PRICE_END_MS)), one=True)
            if not row:
                raise BudgetError('qa_session_already_used')
    except BudgetError:
        raise
    except Exception:
        raise BudgetError('qa_store_unavailable') from None


def _locked(conn, owner, token):
    suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
    row = usage._query(conn, 'SELECT user_id,session_digest,deadline_ms,status,reserved_microusd FROM kilas_live_qa_grants WHERE id=?'+suffix, (GRANT,), one=True)
    if not row or row[0] != owner or row[1] != _digest(token) or not _owner(conn, owner):
        raise BudgetError('qa_not_authorized')
    return row


def assert_active(owner, token):
    """Fence late provider results and stopped sessions across workers."""
    if not enabled():
        raise BudgetError('qa_disabled')
    try:
        with transaction() as conn:
            row = _locked(conn, owner, token)
            now = _now(conn)
            if row[3] != 'ACTIVE' or now >= row[2] or not PRICE_START_MS <= now < PRICE_END_MS:
                raise BudgetError('qa_expired')
    except BudgetError:
        raise
    except Exception:
        raise BudgetError('qa_store_unavailable') from None


def dispatch(owner, token, kind, key, model):
    """Commit reservation and irreversible DISPATCHED marker before network I/O.

    A duplicate/uncertain dispatch never yields a second authorization. Nothing
    refunds the full reservation, including transport errors, stop or expiry.
    """
    if not enabled() or kind not in LIMITS:
        raise BudgetError('qa_disabled')
    if not isinstance(key, str) or not 1 <= len(key) <= 80:
        raise BudgetError('qa_invalid_operation')
    if kind in ('STT','TRANSLATE') and (not key.isascii() or not key.isdigit() or not 1 <= int(key) <= 12 or str(int(key)) != key):
        raise BudgetError('qa_invalid_operation')
    if kind == 'REPLY' and not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):
        raise BudgetError('qa_invalid_operation')
    expected = STT_MODEL if kind == 'STT' else TEXT_MODEL
    if model != expected:
        raise BudgetError('qa_unknown_pricing')
    cost = STT_RESERVE if kind == 'STT' else TEXT_RESERVE
    try:
        with transaction() as conn:
            row = _locked(conn, owner, token)
            now = _now(conn)
            if row[3] != 'ACTIVE' or now >= row[2] or not PRICE_START_MS <= now < PRICE_END_MS:
                raise BudgetError('qa_expired')
            if usage._query(conn, 'SELECT status FROM kilas_live_qa_operations WHERE grant_id=? AND kind=? AND operation_key=?', (GRANT,kind,key), one=True):
                raise BudgetError('qa_no_replay')
            count = usage._query(conn, 'SELECT COUNT(*) FROM kilas_live_qa_operations WHERE grant_id=? AND kind=?', (GRANT,kind), one=True)[0]
            if count >= LIMITS[kind]:
                raise BudgetError('qa_operation_limit')
            if kind == 'TRANSLATE' and not usage._query(conn, "SELECT status FROM kilas_live_qa_operations WHERE grant_id=? AND kind='STT' AND operation_key=? AND status='COMPLETED'", (GRANT,key), one=True):
                raise BudgetError('qa_source_required')
            if kind == 'REPLY' and not usage._query(conn, "SELECT status FROM kilas_live_qa_operations WHERE grant_id=? AND kind='TRANSLATE' AND status='COMPLETED' LIMIT 1", (GRANT,), one=True):
                raise BudgetError('qa_source_required')
            if row[4]+cost > CAP:
                raise BudgetError('qa_budget_exhausted')
            usage._query(conn, 'UPDATE kilas_live_qa_grants SET reserved_microusd=reserved_microusd+? WHERE id=?', (cost,GRANT))
            usage._query(conn, "INSERT INTO kilas_live_qa_operations(grant_id,kind,operation_key,reserved_microusd,started_ms,status) VALUES (?,?,?,?,?,'DISPATCHED')", (GRANT,kind,key,cost,now))
    except BudgetError:
        raise
    except Exception:
        raise BudgetError('qa_store_unavailable') from None


def finish(owner, token, kind, key, success):
    try:
        with transaction() as conn:
            _locked(conn, owner, token)
            usage._query(conn, "UPDATE kilas_live_qa_operations SET status=? WHERE grant_id=? AND kind=? AND operation_key=? AND status='DISPATCHED'", ('COMPLETED' if success else 'UNCERTAIN',GRANT,kind,key))
    except Exception:
        # DISPATCHED and full reservation remain durably charged to QA allowance.
        pass


def close(owner, token):
    try:
        with transaction() as conn:
            _locked(conn, owner, token)
            usage._query(conn, "UPDATE kilas_live_qa_grants SET status='CLOSED' WHERE id=?", (GRANT,))
    except BudgetError:
        raise
    except Exception:
        raise BudgetError('qa_store_unavailable') from None
