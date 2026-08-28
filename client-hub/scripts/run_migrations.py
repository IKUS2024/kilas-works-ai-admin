#!/usr/bin/env python3
"""Run Client Hub's database migrations out-of-band — Render cold-start hotfix companion script.

WHY THIS EXISTS: as of this fix, a normal `gunicorn app:app` boot no longer re-runs
db.init_schema() against a PostgreSQL database on every cold start by default (see
db.should_run_migrations_on_boot() and app.py's create_app() for the exact logic) — that was a
plausible contributor to Render Free-tier cold starts stalling before Gunicorn ever reached
"listening". Migrations still need to run at least once for a brand new database, and again
whenever a NEW migration file is added to db.MIGRATIONS. This script does exactly that, once,
without booting the full Flask app.

USAGE:
    One-off migration run (e.g. after adding a new migration file, before the next deploy, or to
    initialize a brand new database) — run this from wherever DATABASE_URL is already configured
    (a Render Shell against the Client Hub service, or locally against the same DATABASE_URL):

        cd client-hub
        python3 scripts/run_migrations.py

    This is also exactly what RUN_MIGRATIONS_ON_BOOT=true does automatically on every boot — set
    that env var for one deploy instead of running this script by hand if you prefer, then unset it
    again afterward so subsequent cold starts stay fast.

    Safe to run multiple times — every migration file is idempotent (see db.py's MIGRATIONS
    docstring), so re-running an already-migrated database is a no-op.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402


def main():
    backend_label = "PostgreSQL" if db.BACKEND == "postgres" else "SQLite"
    print(f"Database backend: {backend_label}")
    try:
        db.get_connection()
        print("Database connection: OK")
    except Exception as e:
        print(f"Database connection: FAILED ({e})")
        sys.exit(1)

    print(f"Running {len(db.MIGRATIONS)} migration file(s)...")
    db.init_schema()
    print("Schema initialization: OK (migrations executed)")


if __name__ == "__main__":
    main()
