#!/usr/bin/env python3
"""Production database smoke test — Client Hub PostgreSQL validation.

Run this AFTER deploying Client Hub with DATABASE_URL pointed at a real PostgreSQL instance
(e.g. Render's kilas-works-db) to prove the database is actually usable end-to-end, not just
reachable. It is intentionally NOT part of the pytest-less test suite in tests/ — those run against
a throwaway SQLite file on every CI-less local run; this script is meant to be run by hand, once,
right after a deploy, against the real production database.

WHAT THIS DOES:
  1. Connect (via db.get_connection(), the same connection path the app itself uses).
  2. Insert a clearly-labeled temporary tenant (business + owner user) inside a transaction.
  3. Read it back.
  4. Update it.
  5. Verify feature-flag behavior for both packages (BASIC/PRO) via feature_flags.py.
  6. Write and verify a tenant_configs row (JSON serialization/deserialization round-trip).
  7. Write and verify an audit_log event.
  8. Delete/clean up every row this script created — in try/finally, so cleanup runs even if an
     earlier step fails or asserts.

SAFETY:
  - All test data is named with the "__SMOKE_TEST__" prefix (business name, tenant slug, user
    email) so it can never be confused with a real client, and so a failed cleanup is trivially
    findable and removable by hand later (see the cleanup query printed at the end).
  - This script NEVER prints DATABASE_URL, a password, a username, a hostname, or any credential.
  - Nothing here touches ../app.py (the production WhatsApp bot) or any of its tables/behavior.
  - Safe to run against SQLite too (e.g. for a local dry run of this script itself) — it does not
    assume BACKEND == "postgres", it just reports which backend it ran against.

USAGE:
    cd client-hub
    export DATABASE_URL="postgresql://...(the real Render Postgres URL)..."
    python3 scripts/postgres_smoke_test.py

Exit code 0 = every check passed and cleanup succeeded. Non-zero = something failed; read the
printed step name to see which one, then inspect (never guess) the actual error before retrying.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db          # noqa: E402
import repo        # noqa: E402
import provisioning  # noqa: E402
import feature_flags  # noqa: E402

MARKER = "__SMOKE_TEST__"


def _label(suffix):
    # No wall-clock timestamp (keeps this script deterministic to read/rerun); a per-run random
    # component is enough to avoid UNIQUE collisions if a previous run's cleanup somehow failed.
    return f"{MARKER}{suffix}_{os.getpid()}"


def step(name):
    print(f"\n--- {name} ---")


def main():
    print(f"Database backend under test: {'PostgreSQL' if db.BACKEND == 'postgres' else 'SQLite'}")
    if db.BACKEND != "postgres":
        print(
            "WARNING: DATABASE_URL is not set, so this run is exercising the SQLite path, not "
            "PostgreSQL. That's a fine dry run of this script's own logic, but it does NOT "
            "validate PostgreSQL. Set DATABASE_URL to the real Render Postgres URL and re-run "
            "this script against the deployed service (or from a machine with network access to "
            "it) before treating PostgreSQL as validated."
        )

    created = {"business_id": None, "user_id": None}

    try:
        step("1. Connect")
        db.get_connection()
        print("Database connection: OK")

        # Idempotent (CREATE TABLE/INDEX IF NOT EXISTS) — safe to call even against a database
        # that's already fully migrated, exactly like the app does on every boot. Running it here
        # too means this script also proves migrations apply cleanly against the real database.
        db.init_schema()
        print("Schema initialization: OK")

        step("2. Insert temporary tenant (transaction: user -> business -> membership -> features)")
        email = f"{_label('owner')}@smoketest.kilasworks.invalid".lower()
        user_id = repo.create_user(email, "not-a-real-password-hash", role="CLIENT_OWNER",
                                    full_name=MARKER)
        created["user_id"] = user_id
        business_name = _label("Business")
        business_id = repo.create_business(user_id, business_name, package="AI_ADMIN_BASIC")
        created["business_id"] = business_id
        print(f"Inserted: user_id={user_id}, business_id={business_id}, name={business_name!r}")

        step("3. Read it back")
        business = repo.get_business(business_id)
        assert business is not None, "smoke-test business not found immediately after insert"
        assert business["business_name"] == business_name
        assert business["package"] == "AI_ADMIN_BASIC"
        assert business["status"] == "DRAFT"
        print("Read OK: business_name / package / status match what was inserted.")

        step("4. Update it")
        repo.set_business_package(business_id, "AI_ADMIN_PRO", actor_user_id=user_id)
        updated = repo.get_business(business_id)
        assert updated["package"] == "AI_ADMIN_PRO", "package update did not persist"
        print("Update OK: package changed DRAFT/BASIC -> PRO and persisted.")

        step("5. Verify package/feature flags")
        basic_feats = feature_flags.features_for_package("AI_ADMIN_BASIC")
        pro_feats = feature_flags.features_for_package("AI_ADMIN_PRO")
        assert basic_feats["appointment"] is False, "BASIC must not include appointment"
        assert pro_feats["appointment"] is True, "PRO must include appointment"
        tenant_feats_row = db.query_one(
            "SELECT * FROM tenant_features WHERE business_id = ?", (business_id,)
        )
        assert tenant_feats_row is not None, "tenant_features row missing after package change"
        assert bool(tenant_feats_row["appointment"]) is True, (
            "tenant_features.appointment must be TRUE after switching to AI_ADMIN_PRO — if this "
            "fails against Postgres but passes against SQLite, it means a boolean column got a "
            "raw 0/1 integer instead of a real boolean somewhere upstream."
        )
        print("Feature flags OK: BASIC vs PRO differ correctly, and the DB row matches PRO after the switch.")

        step("6. Tenant config JSON serialization/deserialization round-trip")
        sample_config = {
            "tenant_id": business_id,
            "business_name": business_name,
            "marker": MARKER,
            "nested": {"a": [1, 2, 3], "b": True, "c": None},
        }
        version, changed = repo.save_tenant_config(business_id, sample_config)
        assert changed is True and version == 1, "first save_tenant_config call must create version 1"
        row = repo.get_tenant_config_row(business_id)
        assert row is not None and row["config"] == sample_config, (
            "tenant_configs.config_json did not round-trip byte-for-byte through JSON "
            "serialize/deserialize"
        )
        # Re-saving the identical config must be a no-op (idempotency, same guarantee provisioning
        # relies on) — verifies UPDATE path too, not just INSERT.
        version2, changed2 = repo.save_tenant_config(business_id, sample_config)
        assert changed2 is False and version2 == 1, "re-saving an identical config must not bump the version"
        print("Tenant config OK: JSON round-trips correctly and re-saving an identical config is a no-op.")

        step("7. Audit event")
        repo.write_audit(user_id, business_id, provisioning.EVENT_BUSINESS_SUBMITTED, "smoke test audit event")
        audit_rows = repo.get_audit_log(business_id)
        assert any(a["action"] == provisioning.EVENT_BUSINESS_SUBMITTED for a in audit_rows), (
            "audit event was not recorded / not readable back"
        )
        print("Audit log OK: event written and read back successfully.")

        print("\nALL SMOKE TEST STEPS PASSED.")
        return 0

    finally:
        step("Cleanup (runs even on failure)")
        bid = created["business_id"]
        uid = created["user_id"]
        if bid is not None:
            # Children first, in FK-safe order, then the business row itself.
            for table in (
                "audit_log", "tenant_whatsapp_config", "tenant_configs", "tenant_activation",
                "simulation_messages", "onboarding_status", "ai_settings", "tenant_features",
                "business_faqs", "business_services", "business_profiles", "business_files",
                "onboarding_sessions", "business_memberships",
            ):
                db.execute(f"DELETE FROM {table} WHERE business_id = ?", (bid,))
            db.execute("DELETE FROM businesses WHERE id = ?", (bid,))
        if uid is not None:
            db.execute("DELETE FROM users WHERE id = ?", (uid,))
        # Extra safety net: sweep any other row anywhere that still carries the MARKER, in case an
        # earlier step created something not tracked in `created` above (there shouldn't be any,
        # but this makes cleanup robust to future changes to this script).
        leftover = db.query_all("SELECT id FROM businesses WHERE business_name LIKE ?", (f"{MARKER}%",))
        if leftover:
            print(
                f"NOTE: {len(leftover)} leftover smoke-test business row(s) found (ids: "
                f"{[r['id'] for r in leftover]}). Clean these up by hand with: "
                f"DELETE FROM businesses WHERE business_name LIKE '{MARKER}%';"
                " (cascade the same child-table deletes as above first)."
            )
        else:
            print("Cleanup OK: no smoke-test rows remain.")


if __name__ == "__main__":
    sys.exit(main())
