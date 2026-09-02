#!/usr/bin/env python3
"""Production schema diagnostic — white-screen bug investigation (Info Pembayaran / payment info
onboarding step).

WHY THIS EXISTS: migration 0012 (which adds appointment_enabled/payment_bank_name/
payment_account_number/payment_account_name/payment_instructions to business_profiles) being
PRESENT in this repo's migrations/ folder does NOT prove it has actually been RUN against the
real production PostgreSQL database. db.py's should_run_migrations_on_boot() intentionally
defaults to False for Postgres (a Render cold-start hotfix — see that function's own docstring),
so a migration added to this codebase after the last manual `RUN_MIGRATIONS_ON_BOOT=true` deploy
or the last `scripts/run_migrations.py` run would silently NOT be applied — and the very next
INSERT/UPDATE that touches a missing column would raise
`psycopg2.errors.UndefinedColumn: column "..." does not exist`, an unhandled exception that
(before this same investigation's routes_client.py fix) surfaced to the browser as a raw
500/blank response — the reported "Info Pembayaran -> Simpan & Lanjut -> white screen" bug.

WHAT THIS SCRIPT DOES: connects using the SAME DATABASE_URL the real app uses, and — READ ONLY,
NEVER writes/alters/drops anything — checks whether business_profiles actually has every column
migration 0012 (and every other migration) is supposed to have added. Reports ONLY column
names/types and counts. NEVER reads or prints any row's actual data (no customer names, phone
numbers, bank account numbers, payment instructions, or any other business/customer content).

USAGE (run from a Render Shell for the Client Hub service, or locally with DATABASE_URL exported
to point at the same production database):

    cd client-hub
    DATABASE_URL="<same value Render has set>" python3 scripts/check_business_profiles_schema.py

Exit code 0 = all required columns present. Exit code 1 = at least one is missing (the script
prints exactly which one(s), and the exact one-time fix command to run).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Columns this investigation cares about, mapped to the migration that introduces each ("0001" for
# columns that have existed since the very first schema — those are effectively unconditional).
REQUIRED_COLUMNS = {
    "business_id": "0001_init",
    "category": "0001_init",
    "short_description": "0001_init",
    "country": "0001_init",
    "timezone": "0001_init",
    "address": "0001_init",
    "business_phone": "0001_init",
    "owner_name": "0001_init",
    "primary_language": "0001_init",
    "additional_languages": "0001_init",
    "tone": "0001_init",
    "customer_salutation": "0001_init",
    "operating_hours": "0001_init",
    "closed_days": "0001_init",
    "online_or_offline": "0001_init",
    "appointment_rules_raw": "0001_init",
    "appointment_enabled": "0012_appointment_payment_settings",
    "payment_bank_name": "0012_appointment_payment_settings",
    "payment_account_number": "0012_appointment_payment_settings",
    "payment_account_name": "0012_appointment_payment_settings",
    "payment_instructions": "0012_appointment_payment_settings",
}


def main():
    database_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not database_url:
        print(
            "ERROR: DATABASE_URL is not set in this shell's environment. This script must be run "
            "with the SAME DATABASE_URL value the real Client Hub service uses (e.g. from a "
            "Render Shell on that exact service, where it's already set — or export it manually "
            "from Render's dashboard for a one-off local check). Refusing to guess/fall back to "
            "SQLite, since checking the wrong database would be worse than not checking at all."
        )
        sys.exit(2)

    import db  # noqa: E402 (import after sys.path adjustment above)
    if db.BACKEND != "postgres":
        print(
            f"ERROR: db.BACKEND resolved to {db.BACKEND!r}, not 'postgres', even though "
            "DATABASE_URL is set. This should not be possible — check db.py's backend-selection "
            "logic before trusting this result."
        )
        sys.exit(2)

    print(f"Connecting to PostgreSQL (backend={db.BACKEND})...")
    try:
        conn = db.get_connection()
    except Exception as e:
        # db.get_connection() already sanitizes the exception message (never includes
        # host/user/dbname from DATABASE_URL) — safe to print as-is.
        print(f"CONNECTION FAILED: {e}")
        sys.exit(2)
    print("Connection: OK")

    cur = conn.cursor()
    cur.execute(
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_name = 'business_profiles'"
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        print(
            "\nRESULT: business_profiles table does NOT EXIST at all on this database. "
            "Migration 0001 has never been applied. This is a much bigger problem than the "
            "payment-info columns alone — run scripts/run_migrations.py against this database "
            "before anything else."
        )
        sys.exit(1)

    existing = {r[0]: (r[1], r[2]) for r in rows}
    print(f"\nbusiness_profiles has {len(existing)} column(s) on this database.")

    missing = []
    for col, introduced_in in REQUIRED_COLUMNS.items():
        if col in existing:
            data_type, nullable = existing[col]
            print(f"  OK    {col:<28} ({data_type}, nullable={nullable})")
        else:
            print(f"  MISSING  {col:<28} (expected since {introduced_in})")
            missing.append((col, introduced_in))

    if missing:
        missing_migrations = sorted({m for _, m in missing})
        print(
            f"\nRESULT: {len(missing)} required column(s) MISSING: "
            f"{', '.join(c for c, _ in missing)}"
        )
        print(
            f"This confirms migration(s) {', '.join(missing_migrations)} have NOT been applied "
            "to this production database yet — this is a real, confirmed cause of the "
            "\"Info Pembayaran -> Simpan & Lanjut -> white screen\" bug (every save to one of "
            "these missing columns raises an UndefinedColumn error).\n"
            "\nFIX — run this exactly once, with DATABASE_URL pointed at this same database:\n"
            "  cd client-hub && python3 scripts/run_migrations.py\n"
            "(safe to run even if some migrations already applied — every statement is additive/"
            "idempotent; see migrations/*.sql and db.py's own docstring)."
        )
        sys.exit(1)

    print("\nRESULT: all required business_profiles columns are present. This specific "
          "missing-column hypothesis is RULED OUT for this database.")
    sys.exit(0)


if __name__ == "__main__":
    main()
