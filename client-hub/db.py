"""Database connection layer for Kilas Works Client Hub — dual backend (SQLite / PostgreSQL).

HONESTY NOTE (read this before deploying): this sandbox has no network access to install
SQLAlchemy or psycopg2 (`pip install` is blocked with `403 Host not in allowlist: pypi.org`,
confirmed repeatedly), and no live Postgres instance to connect to. So the PostgreSQL code path
below has been written carefully and reviewed, but **could not be executed or tested in this
sandbox**. The SQLite path is fully tested (see tests/). Before relying on the PostgreSQL path in
production, run the Client Hub test suite once against a real Postgres instance (set
DATABASE_URL and re-run `python3 tests/test_client_hub_v1.py` and
`python3 tests/test_production_foundation.py`) and watch for anything this note didn't anticipate.

WHY NOT SQLAlchemy: same reason as above — it cannot be installed here. Instead this module is a
thin, deliberately small hand-written abstraction: one connection-getter, one query-execution
path, and one placeholder-style translator (SQLite's "?" vs psycopg2's "%s"). Every other file in
this app (repo.py, provisioning.py, tenant_config_model.py, feature_flags.py) only ever calls
db.execute()/db.query_one()/db.query_all()/db.insert_returning_id() — never raw SQL through a
driver object directly — so swapping this module later for a real SQLAlchemy engine, if the team
wants query-builder ergonomics down the line, would not require touching any other file.

BACKEND SELECTION: controlled entirely by the DATABASE_URL environment variable.
  - DATABASE_URL unset  -> SQLite (local dev/tests). File path from CLIENT_HUB_DB_PATH, or a local
    file next to this module by default.
  - DATABASE_URL set    -> PostgreSQL, via psycopg2. If psycopg2 is not installed when
    DATABASE_URL is set, the app raises a clear RuntimeError at startup rather than silently
    falling back to SQLite (silently ignoring a production DB config would be far worse than
    failing loudly) — see requirements.txt, which lists psycopg2-binary as required "if deploying
    with Postgres."

Render/Supabase Postgres URLs are typically postgres:// or postgresql://; both are accepted as-is
by psycopg2.
"""
import os
import re
import sqlite3
import threading

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
BACKEND = "postgres" if DATABASE_URL else "sqlite"

_DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_hub_dev.db")
SQLITE_PATH = os.environ.get("CLIENT_HUB_DB_PATH", _DEFAULT_SQLITE_PATH)

_MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

_local = threading.local()

# Render cold-start hotfix (bounded timeouts): a Render Free Postgres instance can take several
# seconds to wake from idle, and without any bound a stalled/half-open TCP handshake or a slow
# query could hang the whole gunicorn boot indefinitely. These are all overridable via env var but
# ship with production-sane defaults so a normal deploy doesn't need to set anything.
#   - DB_CONNECT_TIMEOUT_SECONDS: how long to wait for the initial TCP+auth handshake.
#   - DB_STATEMENT_TIMEOUT_MS: server-side cap on any single statement (belt-and-suspenders; the
#     app itself should never run a slow query, but this stops one from hanging a worker forever).
#   - DB_LOCK_TIMEOUT_MS: how long to wait to acquire a row/table lock before giving up, rather
#     than queuing behind another session indefinitely.
#   - DB_IDLE_IN_TRANSACTION_TIMEOUT_MS: safety net that force-closes a connection Postgres
#     considers "idle in transaction" past this long — see the idle-in-transaction fix in
#     query_one()/query_all() below; this is a backstop in case any future code path forgets to
#     commit after a read.
# None of these apply to SQLite, which has no server-side timeout concept and is single-process.
DB_CONNECT_TIMEOUT_SECONDS = int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "10"))
DB_STATEMENT_TIMEOUT_MS = int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "15000"))
DB_LOCK_TIMEOUT_MS = int(os.environ.get("DB_LOCK_TIMEOUT_MS", "5000"))
DB_IDLE_IN_TRANSACTION_TIMEOUT_MS = int(os.environ.get("DB_IDLE_IN_TRANSACTION_TIMEOUT_MS", "30000"))

if BACKEND == "postgres":
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as e:  # pragma: no cover - exercised only when DATABASE_URL is set
        raise RuntimeError(
            "DATABASE_URL is set (PostgreSQL backend selected) but psycopg2 is not installed. "
            "Run `pip install psycopg2-binary` (already listed in requirements.txt for this "
            "case) and restart. Refusing to silently fall back to SQLite for a configured "
            "production database."
        ) from e


def _adapt_placeholders(query):
    """Adapt the shared SQL text to the selected backend.

    The codebase intentionally writes parameter placeholders in SQLite's ``?`` style. PostgreSQL
    needs psycopg2's ``%s`` placeholders. A number of service-layer UPDATE statements also use
    SQLite's ``datetime('now')`` expression. PostgreSQL does not implement that function, so on
    the Postgres path we normalize it to the portable SQL ``CURRENT_TIMESTAMP`` expression.
    Keeping this compatibility conversion in one place avoids backend-specific SQL leaking into
    every repository/service module and fixes both legacy and new 0013 update paths consistently.
    Values still travel only through bound parameters; this function never interpolates values.
    """
    if BACKEND == "sqlite":
        return query
    query = query.replace("?", "%s")
    query = re.sub(r"datetime\s*\(\s*['\"]now['\"]\s*\)", "CURRENT_TIMESTAMP", query, flags=re.IGNORECASE)
    return query


def _postgres_connect_kwargs():
    """Pure — builds the kwargs psycopg2.connect() is called with. Deliberately has no dependency
    on psycopg2 itself being importable, so it can be unit-tested even in an environment (like this
    sandbox) where psycopg2 is not installed."""
    return {
        "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
        "options": (
            f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} "
            f"-c lock_timeout={DB_LOCK_TIMEOUT_MS} "
            f"-c idle_in_transaction_session_timeout={DB_IDLE_IN_TRANSACTION_TIMEOUT_MS}"
        ),
    }


def get_connection():
    """One connection per thread. For SQLite: foreign keys are explicitly turned on (off by
    default in sqlite3). For Postgres: autocommit is left OFF, each execute() commits explicitly
    (same transactional shape as the SQLite path, so callers behave identically either way).

    Postgres connection failures are caught and re-raised as a sanitized RuntimeError — never the
    raw psycopg2 exception, whose message can include the host, port, dbname and user (not the
    password, but still more than should ever reach logs). Callers/log handlers that only print
    str(exc) are therefore safe by construction; DATABASE_URL itself is never included either."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        # psycopg2 can leave a cached connection object behind after a DB restart. If the driver
        # already knows it is closed, discard it here instead of handing the dead object to every
        # subsequent request on this worker thread. Half-open sockets are handled by the one-time
        # SELECT retry in query_one()/query_all() below.
        if BACKEND == "postgres" and getattr(conn, "closed", 0):
            _discard_cached_connection()
            conn = None
        else:
            return conn

    if BACKEND == "sqlite":
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    else:
        try:
            # Render cold-start hotfix: bound the connect handshake and set server-side statement/
            # lock/idle-in-transaction timeouts via psycopg2's `options` (equivalent to running
            # `SET statement_timeout = ...` etc. right after connecting, but applied atomically as
            # part of session startup rather than as a separate round-trip). Kwargs are built by a
            # pure helper (no psycopg2 import needed) specifically so this can be unit-tested in an
            # environment where psycopg2 isn't installed — see tests/test_render_coldstart_hotfix.py.
            conn = psycopg2.connect(DATABASE_URL, **_postgres_connect_kwargs())
        except Exception as e:  # pragma: no cover - exercised only against a real Postgres server
            raise RuntimeError(
                "Database connection: FAILED. Could not connect to the configured PostgreSQL "
                "database within "
                f"{DB_CONNECT_TIMEOUT_SECONDS}s. (Details intentionally omitted from this message "
                "— the underlying driver error can include host/user/dbname — check DATABASE_URL, "
                "network access, and that the Postgres instance is reachable and accepting "
                "connections. If the instance was asleep/cold, retrying once often succeeds.)"
            ) from e

    _local.conn = conn
    return conn


def _rollback_quietly(conn):
    """Best-effort ROLLBACK after a failed statement. PostgreSQL aborts the entire transaction on
    the first failing statement (e.g. a UNIQUE violation) and refuses every further query on that
    same connection with 'current transaction is aborted' until an explicit ROLLBACK — a failure
    mode SQLite does not have. Without this, one bad query (e.g. a duplicate-email registration)
    would permanently wedge that thread's cached connection for the rest of the process's life.
    SQLite connections don't need this, but calling rollback() on them is harmless, so this helper
    is used unconditionally in the except-blocks below rather than branching on BACKEND again."""
    try:
        conn.rollback()
    except Exception:
        pass


def _discard_cached_connection():
    """Close and forget this thread's cached connection without leaking driver details."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None


def _is_retryable_postgres_connection_error(exc):
    """True only for broken/stale PostgreSQL connections, never ordinary SQL/data errors."""
    if BACKEND != "postgres":
        return False
    try:
        if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            return True
    except Exception:
        pass
    conn = getattr(_local, "conn", None)
    return bool(conn is not None and getattr(conn, "closed", 0))


def reset_connection_for_new_db_path():
    """Used by tests to force a fresh connection after changing SQLITE_PATH (e.g. to a fresh temp
    file) or after DATABASE_URL changes in-process (test-only; real deploys don't change env vars
    mid-process)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None


def _migration_path(basename_sqlite, basename_postgres):
    name = basename_postgres if BACKEND == "postgres" else basename_sqlite
    return os.path.join(_MIGRATIONS_DIR, name)


# Ordered, additive-only migrations. Each entry is (sqlite_filename, postgres_filename).
# NEVER remove an entry or reorder existing ones — append new migrations to the end. Every
# statement inside each file must be safe to re-run (CREATE TABLE IF NOT EXISTS / CREATE INDEX IF
# NOT EXISTS) since init_schema() runs on every app boot, not just once.
MIGRATIONS = [
    ("0001_init_sqlite.sql", "0001_init_postgres.sql"),
    ("0002_production_foundation_sqlite.sql", "0002_production_foundation_postgres.sql"),
    ("0003_password_reset_sqlite.sql", "0003_password_reset_postgres.sql"),
    ("0004_service_catalog_projects_sqlite.sql", "0004_service_catalog_projects_postgres.sql"),
    ("0005_quotation_invoice_payment_sqlite.sql", "0005_quotation_invoice_payment_postgres.sql"),
    ("0006_talent_sqlite.sql", "0006_talent_postgres.sql"),
    ("0007_wa_takeover_sqlite.sql", "0007_wa_takeover_postgres.sql"),
    ("0008_talent_profile_photo_url_sqlite.sql", "0008_talent_profile_photo_url_postgres.sql"),
    ("0009_ops_polish_sqlite.sql", "0009_ops_polish_postgres.sql"),
    ("0010_owner_notifications_sqlite.sql", "0010_owner_notifications_postgres.sql"),
    ("0011_notification_delivery_catalog_cache_sqlite.sql",
     "0011_notification_delivery_catalog_cache_postgres.sql"),
    ("0012_appointment_payment_settings_sqlite.sql",
     "0012_appointment_payment_settings_postgres.sql"),
    ("0013_tenant_appointments_payment_reviews_sqlite.sql",
     "0013_tenant_appointments_payment_reviews_postgres.sql"),
    ("0014_ai_admin_subscriptions_sqlite.sql", "0014_ai_admin_subscriptions_postgres.sql"),
    ("0015_tenant_followup_state_sqlite.sql", "0015_tenant_followup_state_postgres.sql"),
    ("0016_platform_takeover_sqlite.sql", "0016_platform_takeover_postgres.sql"),
    ("0017_fix_operating_hours_column_type_sqlite.sql",
     "0017_fix_operating_hours_column_type_postgres.sql"),
    ("0018_tenant_reengagement_template_sqlite.sql",
     "0018_tenant_reengagement_template_postgres.sql"),
    ("0019_payment_proof_file_hash_sqlite.sql",
     "0019_payment_proof_file_hash_postgres.sql"),
    ("0020_platform_settings_sqlite.sql",
     "0020_platform_settings_postgres.sql"),
]


def should_run_migrations_on_boot(backend=None, env_value=None):
    """Render cold-start hotfix: decide whether this boot should run init_schema() at all.

    Pure decision function (no I/O) so it can be unit-tested without a live DB connection —
    app.py's create_app() calls this with no arguments; tests pass backend/env_value explicitly.

    RUN_MIGRATIONS_ON_BOOT env var, if set, always wins (accepts "1"/"true"/"yes"/"on", case
    insensitive, for true; anything else is false). If unset, the safe default is:
      - SQLite  -> True.  Local dev and every test in this repo boots against a fresh/temp SQLite
        file with no schema yet, so migrations MUST run for the app to work at all — and since
        SQLite migrations are just local file writes, there is no cold-start cost to worry about.
      - Postgres -> False. This is the actual production hotfix: init_schema() re-executes all 13+
        migration files' worth of SQL against the network database on every single gunicorn boot,
        which is unnecessary once a database is already migrated (confirmed here: commit 456501b
        already ran migrations 0001-0013 successfully against production Postgres) and was a
        plausible contributor to Render Free-tier cold starts stalling before reaching "Gunicorn
        listening". A deploy that introduces a NEW migration should set RUN_MIGRATIONS_ON_BOOT=true
        for that one deploy (or run `python3 scripts/run_migrations.py` as a one-off Render job/
        shell command against the same DATABASE_URL) rather than leaving it on permanently.
    """
    if backend is None:
        backend = BACKEND
    if env_value is None:
        env_value = os.environ.get("RUN_MIGRATIONS_ON_BOOT")
    if env_value is not None:
        return env_value.strip().lower() in ("1", "true", "yes", "on")
    return backend != "postgres"


def init_schema():
    """Idempotent — safe to call on every app boot. Runs every migration in MIGRATIONS, in order,
    for whichever backend is active."""
    conn = get_connection()
    for sqlite_name, postgres_name in MIGRATIONS:
        path = _migration_path(sqlite_name, postgres_name)
        with open(path, "r", encoding="utf-8") as f:
            script = f.read()
        if BACKEND == "sqlite":
            try:
                conn.executescript(script)
            except sqlite3.OperationalError as e:
                # SQLite's ALTER TABLE has no "ADD COLUMN IF NOT EXISTS" (unlike Postgres, where
                # migration files use that directly) — init_schema() re-runs every migration file
                # on every boot, so a plain "ALTER TABLE ... ADD COLUMN" migration (e.g. 0008) hits
                # "duplicate column name" on the 2nd+ boot. That's the expected/idempotent outcome
                # here (the column already exists from a previous run), not a real failure — every
                # other statement in these files already uses CREATE TABLE/INDEX IF NOT EXISTS, so
                # this is the one DDL shape SQLite can't express idempotently in pure SQL.
                if "duplicate column name" not in str(e):
                    raise
        else:
            # psycopg2's simple-query protocol (used automatically when execute() is called with
            # no parameters) accepts multiple ';'-separated statements in one call, same as
            # sqlite3's executescript — this is the untested-in-this-sandbox path described in
            # this module's HONESTY NOTE above.
            cur = conn.cursor()
            cur.execute(script)
            cur.close()
    conn.commit()


def execute(query, params=()):
    """INSERT/UPDATE/DELETE. Returns the cursor (SQLite callers may read .lastrowid; Postgres
    callers should prefer insert_returning_id() instead, since psycopg2 cursors don't populate
    .lastrowid)."""
    query = _adapt_placeholders(query)
    conn = get_connection()
    try:
        if BACKEND == "sqlite":
            cur = conn.execute(query, params)
        else:
            cur = conn.cursor()
            cur.execute(query, params)
        conn.commit()
        return cur
    except Exception as e:
        _rollback_quietly(conn)
        if _is_retryable_postgres_connection_error(e):
            _discard_cached_connection()
        raise


def insert_returning_id(query, params=(), id_column="id"):
    """Run an INSERT and return the new row's id, portably across backends.

    SQLite: uses cursor.lastrowid (works because every table here has an INTEGER PRIMARY KEY
    AUTOINCREMENT id column, so lastrowid always maps to id).
    Postgres: appends "RETURNING <id_column>" to the query (if not already present) and fetches
    it — psycopg2 cursors do not populate .lastrowid at all.
    """
    conn = get_connection()
    try:
        if BACKEND == "sqlite":
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid

        q = query.rstrip().rstrip(";")
        if "RETURNING" not in q.upper():
            q = f"{q} RETURNING {id_column}"
        q = _adapt_placeholders(q)
        cur = conn.cursor()
        cur.execute(q, params)
        row = cur.fetchone()
        conn.commit()
        cur.close()
        return row[0] if row else None
    except Exception as e:
        _rollback_quietly(conn)
        if _is_retryable_postgres_connection_error(e):
            _discard_cached_connection()
        raise


def _row_to_dict(row, columns=None):
    if row is None:
        return None
    if BACKEND == "sqlite":
        return dict(row)
    return dict(zip(columns, row))


def query_one(query, params=()):
    """Run one SELECT and recover once from a stale Postgres connection.

    SELECTs are safe to repeat after a broken connection; writes are deliberately NOT auto-retried
    elsewhere in this module because a lost ACK could otherwise duplicate a side effect.
    """
    query = _adapt_placeholders(query)
    for attempt in range(2):
        conn = get_connection()
        try:
            if BACKEND == "sqlite":
                cur = conn.execute(query, params)
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row is not None else None

            cur = conn.cursor()
            cur.execute(query, params)
            row = cur.fetchone()
            columns = [d[0] for d in cur.description] if cur.description else []
            cur.close()
            conn.commit()
            return _row_to_dict(row, columns)
        except Exception as e:
            _rollback_quietly(conn)
            retryable = _is_retryable_postgres_connection_error(e)
            if retryable:
                _discard_cached_connection()
            if attempt == 0 and retryable:
                continue
            raise

def query_all(query, params=()):
    """Run a SELECT-many and recover once from a stale Postgres connection. See query_one()."""
    query = _adapt_placeholders(query)
    for attempt in range(2):
        conn = get_connection()
        try:
            if BACKEND == "sqlite":
                cur = conn.execute(query, params)
                rows = [dict(row) for row in cur.fetchall()]
                conn.commit()
                return rows

            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
            cur.close()
            conn.commit()
            return [_row_to_dict(row, columns) for row in rows]
        except Exception as e:
            _rollback_quietly(conn)
            retryable = _is_retryable_postgres_connection_error(e)
            if retryable:
                _discard_cached_connection()
            if attempt == 0 and retryable:
                continue
            raise
