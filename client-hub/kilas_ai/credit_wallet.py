"""Inactive wallet foundation. No tariff, HTTP endpoint or automatic schema apply.

All values are integer milli-credits. Every account mutation serializes on its
server-resolved user row. Reservations never expire automatically: an interrupted
provider call must be reconciled before release, rather than silently permitting
another potentially paid request. This module makes no provider calls.
"""
import hashlib
import re
import secrets
from contextlib import contextmanager
import db
import file_utils
from . import usage

PACK_IDR = 99000
PACK_MILLI = 2000000


class WalletError(ValueError):
    pass


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,160}', value):
        raise WalletError('invalid_operation_key')
    return value


def _amount(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 10**12:
        raise WalletError('invalid_credit_amount')
    return value


@contextmanager
def _locked(user):
    if type(user) is not int or user <= 0:
        raise WalletError('invalid_account')
    conn = usage._connect()
    try:
        suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        if not usage._query(conn, 'SELECT id FROM users WHERE id=?' + suffix, (user,), one=True):
            raise WalletError('account_not_found')
        usage._query(conn, 'INSERT INTO kilas_credit_accounts(user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING', (user,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _totals(conn, user):
    row = usage._query(conn, 'SELECT balance_milli,reserved_milli FROM kilas_credit_accounts WHERE user_id=?', (user,), one=True)
    total,held=row if row else (0,0)
    return {'balance_milli':total,'reserved_milli':held,'available_milli':total-held}


def _event(conn, user, key, kind, balance_delta, reserved_delta):
    usage._query(conn, 'INSERT INTO kilas_credit_events(user_id,event_key,kind,balance_delta,reserved_delta,created_at) VALUES (?,?,?,?,?,?)',
                 (user, key, kind, balance_delta, reserved_delta, usage._now().isoformat()))
    usage._query(conn, 'UPDATE kilas_credit_accounts SET balance_milli=balance_milli+?,reserved_milli=reserved_milli+? WHERE user_id=?',
                 (balance_delta, reserved_delta, user))


def balance(user):
    # GET/read paths do not initialize or mutate accounts.
    if type(user) is not int or user <= 0:
        raise WalletError('invalid_account')
    row = db.query_one('SELECT balance_milli,reserved_milli FROM kilas_credit_accounts WHERE user_id=?', (user,))
    total, held = (row['balance_milli'], row['reserved_milli']) if row else (0, 0)
    return {'balance_milli': total, 'reserved_milli': held, 'available_milli': total-held}


def reserve(user, key, maximum_milli, *, fingerprint):
    with _locked(user) as conn:
        return reserve_in(conn, user, key, maximum_milli, fingerprint=fingerprint)


def reserve_in(conn, user, key, maximum_milli, *, fingerprint):
    key = _key(key)
    maximum_milli = _amount(maximum_milli)
    if not isinstance(fingerprint,str) or not re.fullmatch('[a-f0-9]{64}',fingerprint):
        raise WalletError('invalid_fingerprint')
    old = usage._query(conn, 'SELECT maximum_milli,status,fingerprint FROM kilas_credit_holds WHERE user_id=? AND operation_key=?', (user, key), one=True)
    if old:
        if old[0] != maximum_milli or old[2] != fingerprint:
            raise WalletError('idempotency_conflict')
        if old[1] == 'RELEASED':
            raise WalletError('operation_closed')
        return old[1]
    if _totals(conn, user)['available_milli'] < maximum_milli:
        raise WalletError('insufficient_credit')
    usage._query(conn, "INSERT INTO kilas_credit_holds(user_id,operation_key,fingerprint,maximum_milli,status,created_at) VALUES (?,?,?,?,'RESERVED',?)",
                 (user, key, fingerprint, maximum_milli, usage._now().isoformat()))
    _event(conn, user, 'reserve:'+key, 'RESERVE', 0, maximum_milli)
    return 'RESERVED'


def settle(user, key, actual_milli):
    with _locked(user) as conn:
        return settle_in(conn, user, key, actual_milli)


def settle_in(conn, user, key, actual_milli):
    key = _key(key)
    actual_milli = _amount(actual_milli, zero=True)
    old = usage._query(conn, 'SELECT maximum_milli,actual_milli,status FROM kilas_credit_holds WHERE user_id=? AND operation_key=?', (user, key), one=True)
    if not old:
        raise WalletError('reservation_not_found')
    if old[2] == 'CAPTURED' and old[1] == actual_milli:
        return 'CAPTURED'
    if old[2] != 'RESERVED':
        raise WalletError('operation_closed')
    if actual_milli > old[0]:
        raise WalletError('reservation_exceeded')
    _event(conn, user, 'capture:'+key, 'CAPTURE', -actual_milli, -old[0])
    usage._query(conn, "UPDATE kilas_credit_holds SET status='CAPTURED',actual_milli=?,finished_at=? WHERE user_id=? AND operation_key=?",
                 (actual_milli, usage._now().isoformat(), user, key))
    return 'CAPTURED'


def release(user, key):
    with _locked(user) as conn:
        return release_in(conn, user, key)


def release_in(conn, user, key):
    """Call only after a definitive cancellation/failure, never an unknown timeout."""
    key = _key(key)
    old = usage._query(conn, 'SELECT maximum_milli,status FROM kilas_credit_holds WHERE user_id=? AND operation_key=?', (user, key), one=True)
    if not old:
        raise WalletError('reservation_not_found')
    if old[1] == 'RELEASED':
        return 'RELEASED'
    if old[1] != 'RESERVED':
        raise WalletError('operation_closed')
    _event(conn, user, 'release:'+key, 'RELEASE', 0, -old[0])
    usage._query(conn, "UPDATE kilas_credit_holds SET status='RELEASED',finished_at=? WHERE user_id=? AND operation_key=?", (usage._now().isoformat(), user, key))
    return 'RELEASED'


def create_purchase(user, request_key):
    request_key = _key(request_key)
    with _locked(user) as conn:
        old = usage._query(conn, 'SELECT id FROM kilas_credit_orders WHERE user_id=? AND request_key=?', (user, request_key), one=True)
        if old:
            return old[0]
        ident = 'KCR-'+secrets.token_hex(16).upper()
        usage._query(conn, "INSERT INTO kilas_credit_orders(id,user_id,request_key,amount_idr,credit_milli,status,created_at) VALUES (?,?,?,?,?,'PAYMENT_PENDING',?)",
                     (ident, user, request_key, PACK_IDR, PACK_MILLI, usage._now().isoformat()))
        return ident


def order(user, ident):
    return db.query_one('SELECT id,user_id,amount_idr,credit_milli,status,admin_note,created_at FROM kilas_credit_orders WHERE user_id=? AND id=?', (user, ident))


def submit_proof(user, ident, upload):
    if not upload or not upload.filename:
        raise WalletError('proof_required')
    raw = upload.stream.read(5*1024*1024+1)
    if not raw or len(raw) > 5*1024*1024:
        raise WalletError('proof_size_invalid')
    try:
        name, mime = file_utils.validate_project_attachment_upload(upload.filename, raw)
    except file_utils.UploadRejected:
        raise WalletError('proof_invalid') from None
    if upload.mimetype not in (mime, 'application/octet-stream'):
        raise WalletError('proof_type_invalid')
    with _locked(user) as conn:
        row = usage._query(conn, 'SELECT status FROM kilas_credit_orders WHERE user_id=? AND id=?', (user, ident), one=True)
        if not row or row[0] not in ('PAYMENT_PENDING', 'REJECTED'):
            raise WalletError('order_not_pending')
        usage._query(conn, "UPDATE kilas_credit_orders SET status='UNDER_REVIEW',proof_name=?,proof_mime=?,proof_content=?,proof_digest=?,transfer_reference=NULL,reviewed_by=NULL,reviewed_at=NULL,admin_note=NULL WHERE user_id=? AND id=?",
                     (name, mime, raw, hashlib.sha256(raw).hexdigest(), user, ident))


def _review(ident, reviewer, decision, note='', *, transfer_reference=None):
    if decision == 'VERIFIED':
        if not isinstance(transfer_reference,str) or not re.fullmatch('[A-Za-z0-9:/_-]{4,100}',transfer_reference.strip()):
            raise WalletError('verified_transfer_reference_required')
        transfer_reference=transfer_reference.strip().upper()
    else:
        transfer_reference=None
    if decision not in ('VERIFIED', 'REJECTED') or type(reviewer) is not int:
        raise WalletError('invalid_review')
    seed = db.query_one('SELECT user_id FROM kilas_credit_orders WHERE id=?', (ident,))
    if not seed:
        raise WalletError('order_not_found')
    user = seed['user_id']
    with _locked(user) as conn:
        role = usage._query(conn, 'SELECT role FROM users WHERE id=?', (reviewer,), one=True)
        if not role or role[0] != 'KILAS_ADMIN' or reviewer == user:
            raise WalletError('review_forbidden')
        row = usage._query(conn, 'SELECT status,amount_idr,credit_milli,proof_content,transfer_reference,proof_digest FROM kilas_credit_orders WHERE user_id=? AND id=?', (user, ident), one=True)
        if row[1:3] != (PACK_IDR, PACK_MILLI):
            raise WalletError('order_pack_mismatch')
        if row[0] == decision:
            if row[4] != transfer_reference:raise WalletError('review_idempotency_conflict')
            return decision
        if row[0] != 'UNDER_REVIEW' or not row[3]:
            raise WalletError('order_not_reviewable')
        if decision == 'VERIFIED':
            # Unique partial index also fences races between different users/orders.
            usage._query(conn, 'UPDATE kilas_credit_orders SET transfer_reference=? WHERE id=?', (transfer_reference,ident))
            _event(conn, user, 'purchase:'+ident, 'PURCHASE', PACK_MILLI, 0)
        usage._query(conn, 'UPDATE kilas_credit_orders SET status=?,reviewed_by=?,reviewed_at=?,admin_note=?,transfer_reference=? WHERE user_id=? AND id=?',
                     (decision, reviewer, usage._now().isoformat(), str(note or '')[:1000], transfer_reference, user, ident))
        usage._query(conn,'INSERT INTO kilas_credit_reviews(id,order_id,reviewer,decision,transfer_reference,proof_digest,created_at) VALUES (?,?,?,?,?,?,?)', (secrets.token_hex(16),ident,reviewer,decision,transfer_reference,row[5],usage._now().isoformat()))
        return decision


def review(ident, reviewer, decision, note='', *, transfer_reference=None):
    try:
        return _review(ident,reviewer,decision,note,transfer_reference=transfer_reference)
    except Exception as error:
        if getattr(error,'pgcode',None)=='23505' or ('UNIQUE constraint failed: kilas_credit_orders.transfer_reference' in str(error)):
            raise WalletError('transfer_reference_already_verified') from None
        raise
