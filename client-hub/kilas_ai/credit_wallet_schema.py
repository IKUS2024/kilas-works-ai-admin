"""Explicit, additive wallet schema candidate; NOT wired into app startup.

Production application requires the separately reviewed migration checkpoint.
Legacy cost credits, Audio seconds and Finance tables are never rewritten.
"""
from . import usage
import db


def apply(conn):
    binary = 'BYTEA' if db.BACKEND == 'postgres' else 'BLOB'
    statements = [
        '''CREATE TABLE IF NOT EXISTS kilas_credit_accounts (
        user_id BIGINT PRIMARY KEY REFERENCES users(id),
        balance_milli BIGINT NOT NULL DEFAULT 0 CHECK(balance_milli>=0),
        reserved_milli BIGINT NOT NULL DEFAULT 0 CHECK(reserved_milli>=0 AND reserved_milli<=balance_milli))''',
        '''CREATE TABLE IF NOT EXISTS kilas_credit_events (
        user_id BIGINT NOT NULL REFERENCES users(id), event_key TEXT NOT NULL,
        kind TEXT NOT NULL, balance_delta BIGINT NOT NULL, reserved_delta BIGINT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(user_id,event_key))''',
        '''CREATE TABLE IF NOT EXISTS kilas_credit_holds (
        user_id BIGINT NOT NULL REFERENCES users(id), operation_key TEXT NOT NULL,
        maximum_milli BIGINT NOT NULL CHECK(maximum_milli>0),
        actual_milli BIGINT CHECK(actual_milli>=0 AND actual_milli<=maximum_milli),
        status TEXT NOT NULL CHECK(status IN ('RESERVED','CAPTURED','RELEASED')),
        created_at TEXT NOT NULL, finished_at TEXT, PRIMARY KEY(user_id,operation_key))''',
        f'''CREATE TABLE IF NOT EXISTS kilas_credit_orders (
        id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
        request_key TEXT NOT NULL, amount_idr BIGINT NOT NULL CHECK(amount_idr=99000),
        credit_milli BIGINT NOT NULL CHECK(credit_milli=2000000),
        status TEXT NOT NULL CHECK(status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
        proof_name TEXT, proof_mime TEXT, proof_content {binary},
        reviewed_by BIGINT REFERENCES users(id), reviewed_at TEXT, admin_note TEXT,
        created_at TEXT NOT NULL, UNIQUE(user_id,request_key))''',
    ]
    for sql in statements:
        usage._query(conn, sql)
