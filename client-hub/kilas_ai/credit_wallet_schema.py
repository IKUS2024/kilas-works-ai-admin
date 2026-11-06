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
        fingerprint TEXT NOT NULL, maximum_milli BIGINT NOT NULL CHECK(maximum_milli>0),
        actual_milli BIGINT CHECK(actual_milli>=0 AND actual_milli<=maximum_milli),
        status TEXT NOT NULL CHECK(status IN ('RESERVED','CAPTURED','RELEASED')),
        created_at TEXT NOT NULL, finished_at TEXT, PRIMARY KEY(user_id,operation_key))''',
        f'''CREATE TABLE IF NOT EXISTS kilas_credit_orders (
        id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id),
        request_key TEXT NOT NULL, amount_idr BIGINT NOT NULL CHECK(amount_idr=99000),
        credit_milli BIGINT NOT NULL CHECK(credit_milli=2000000),
        status TEXT NOT NULL CHECK(status IN ('PAYMENT_PENDING','UNDER_REVIEW','VERIFIED','REJECTED')),
        proof_name TEXT, proof_mime TEXT, proof_content {binary}, proof_digest TEXT,
        transfer_reference TEXT,
        reviewed_by BIGINT REFERENCES users(id), reviewed_at TEXT, admin_note TEXT,
        created_at TEXT NOT NULL, UNIQUE(user_id,request_key))''',
        "CREATE UNIQUE INDEX IF NOT EXISTS kilas_credit_transfer_once ON kilas_credit_orders(transfer_reference) WHERE status='VERIFIED'",
        "CREATE TABLE IF NOT EXISTS kilas_credit_reviews (id TEXT PRIMARY KEY,order_id TEXT NOT NULL REFERENCES kilas_credit_orders(id),reviewer BIGINT NOT NULL REFERENCES users(id),decision TEXT NOT NULL,transfer_reference TEXT,proof_digest TEXT NOT NULL,created_at TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS kilas_credit_admissions (
        user_id BIGINT NOT NULL REFERENCES users(id),operation_key TEXT NOT NULL,
        feature TEXT NOT NULL,maximum_units BIGINT NOT NULL CHECK(maximum_units>0),fingerprint TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('FREE','PAID','SPLIT','OWNER')),rate_milli BIGINT NOT NULL,
        rate_units BIGINT NOT NULL CHECK(rate_units>0),maximum_charge BIGINT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('RESERVED','CAPTURED','RELEASED')),
        actual_units BIGINT,free_reserved BIGINT NOT NULL DEFAULT 0,free_actual BIGINT NOT NULL DEFAULT 0,
        priced_max BIGINT NOT NULL DEFAULT 0,priced_actual BIGINT NOT NULL DEFAULT 0,allocation TEXT NOT NULL DEFAULT 'units',
        created_at TEXT NOT NULL,finished_at TEXT,PRIMARY KEY(user_id,operation_key))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_consents (
        token TEXT PRIMARY KEY,user_id BIGINT NOT NULL REFERENCES users(id),operation_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL,quote_hash TEXT NOT NULL,feature TEXT NOT NULL,maximum_units BIGINT NOT NULL,
        free_units BIGINT NOT NULL,maximum_charge BIGINT NOT NULL,terms_json TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','DECLINED','CONSUMED')),
        expires_at TEXT NOT NULL,created_at TEXT NOT NULL,decided_at TEXT,UNIQUE(user_id,operation_key,quote_hash))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_reconciliations (
        user_id BIGINT NOT NULL REFERENCES users(id),operation_key TEXT NOT NULL,reviewer BIGINT NOT NULL REFERENCES users(id),
        outcome TEXT NOT NULL,actual_units BIGINT NOT NULL,priced_actual BIGINT NOT NULL,evidence TEXT NOT NULL,
        created_at TEXT NOT NULL,PRIMARY KEY(user_id,operation_key))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_audio_links (
        user_id BIGINT NOT NULL REFERENCES users(id),job_id BIGINT NOT NULL,operation_key TEXT NOT NULL,
        feature TEXT NOT NULL,source_ms BIGINT NOT NULL,maximum_output_ms BIGINT NOT NULL,dispatched INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(user_id,job_id))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_translation_links (
        user_id BIGINT NOT NULL REFERENCES users(id),operation_key TEXT NOT NULL,root_key TEXT NOT NULL,
        source_ms BIGINT NOT NULL DEFAULT 0,output_ms BIGINT NOT NULL DEFAULT 0,maximum_ms BIGINT NOT NULL,output_ratio_milli BIGINT NOT NULL,
        source_digest TEXT,dispatched INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(user_id,operation_key))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_interpreter_sessions (
        user_id BIGINT NOT NULL REFERENCES users(id),session_id TEXT NOT NULL UNIQUE,model TEXT NOT NULL,
        settings_digest TEXT NOT NULL,billing_mode TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL,PRIMARY KEY(user_id,session_id))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_interpreter_turns (
        user_id BIGINT NOT NULL,session_id TEXT NOT NULL,turn_index BIGINT NOT NULL,operation_key TEXT NOT NULL,
        maximum_ms BIGINT NOT NULL,output_ratio_milli BIGINT NOT NULL,
        source_ms BIGINT NOT NULL DEFAULT 0,output_ms BIGINT NOT NULL DEFAULT 0,source_digest TEXT,
        dispatched INTEGER NOT NULL DEFAULT 0,confirmed INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'ACTIVE',
        PRIMARY KEY(user_id,session_id,turn_index),UNIQUE(user_id,operation_key),
        FOREIGN KEY(user_id,session_id) REFERENCES kilas_credit_interpreter_sessions(user_id,session_id))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_work_waits (
        token TEXT PRIMARY KEY REFERENCES kilas_credit_consents(token),user_id BIGINT NOT NULL REFERENCES users(id),
        job_id BIGINT NOT NULL,step_id BIGINT NOT NULL,operation_key TEXT NOT NULL,fingerprint TEXT NOT NULL,
        job_revision BIGINT NOT NULL,job_digest TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'WAITING',created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_work_operations (
        user_id BIGINT NOT NULL REFERENCES users(id),operation_key TEXT NOT NULL,job_id BIGINT NOT NULL,step_id BIGINT NOT NULL,
        fingerprint TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ADMITTED',dispatched_at TEXT,
        PRIMARY KEY(user_id,operation_key))""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_activation (
        version TEXT PRIMARY KEY,cutoff TEXT NOT NULL,release_sha TEXT NOT NULL,tariff_digest TEXT NOT NULL,
        meter_version TEXT NOT NULL,snapshot_digest TEXT NOT NULL,created_at TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS kilas_credit_quota_baselines (
        version TEXT NOT NULL REFERENCES kilas_credit_activation(version),user_id BIGINT NOT NULL REFERENCES users(id),
        feature TEXT NOT NULL,period_start TEXT NOT NULL,period_end TEXT NOT NULL,units BIGINT NOT NULL,
        provenance TEXT NOT NULL,PRIMARY KEY(version,user_id,feature,period_start))""",
    ]
    for sql in statements:
        usage._query(conn, sql)


def apply_release():
    """Explicit additive release; no backfill/conversion or automatic startup call."""
    import hashlib
    from pathlib import Path
    checksum=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    conn=usage._connect()
    try:
        if db.BACKEND=='postgres':
            usage._query(conn,"SET LOCAL lock_timeout='10s'")
            usage._query(conn,'SELECT pg_advisory_xact_lock(74120601)')
        usage._query(conn,'CREATE TABLE IF NOT EXISTS kilas_credit_schema_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
        old=usage._query(conn,"SELECT checksum FROM kilas_credit_schema_releases WHERE name='customer-credit-v1'",one=True)
        if old:
            if old[0]!=checksum:raise RuntimeError('credit_schema_checksum_mismatch')
        else:
            apply(conn)
            usage._query(conn,"INSERT INTO kilas_credit_schema_releases(name,checksum) VALUES ('customer-credit-v1',?)",(checksum,))
        conn.commit()
        return not bool(old)
    except Exception:
        conn.rollback();raise
    finally:conn.close()
