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
    """Every query in this codebase is written with SQLite's '?' placeholder style. For the
    Postgres backend, translate to psycopg2's '%s' style. This is a plain substitution — safe
    because no query in this codebase ever embeds a literal '?' character in SQL text itself
    (all values always go through parameters, never string-formatted into the query)."""
    if BACKEND == "sqlite":
        return query
    return query.replace("?", "%s")


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
        return conn

    if BACKEND == "sqlite":
        conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    else:
        try:
            conn = psycopg2.connect(DATABASE_URL)
        except Exception as e:  # pragma: no cover - exercised only against a real Postgres server
            raise RuntimeError(
                "Database connection: FAILED. Could not connect to the configured PostgreSQL "
                "database. (Details intentionally omitted from this message — the underlying "
                "driver error can include host/user/dbname — check DATABASE_URL, network access, "
                "and that the Postgres instance is reachable and accepting connections.)"
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
]


def init_schema():
    """Idempotent — safe to call on every app boot. Runs every migration in MIGRATIONS, in order,
    for whichever backend is active."""
    conn = get_connection()
    for sqlite_name, postgres_name in MIGRATIONS:
        path = _migration_path(sqlite_name, postgres_name)
        with open(path, "r", encoding="utf-8") as f:
            script = f.read()
        if BACKEND == "sqlite":
            conn.executescript(script)
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
    except Exception:
        _rollback_quietly(conn)
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
    except Exception:
        _rollback_quietly(conn)
        raise


def _row_to_dict(row, columns=None):
    if row is None:
        return None
    if BACKEND == "sqlite":
        return dict(row)
    return dict(zip(columns, row))


def query_one(query, params=()):
    query = _adapt_placeholders(query)
    conn = get_connection()
    try:
        if BACKEND == "sqlite":
            cur = conn.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row is not None else None

        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
        columns = [d[0] for d in cur.description] if cur.description else []
        cur.close()
        return _row_to_dict(row, columns)
    except Exception:
        _rollback_quietly(conn)
        raise


def query_all(query, params=()):
    query = _adapt_placeholders(query)
    conn = get_connection()
    try:
        if BACKEND == "sqlite":
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        cur.close()
        return [_row_to_dict(row, columns) for row in rows]
    except Exception:
        _rollback_quietly(conn)
        raise
