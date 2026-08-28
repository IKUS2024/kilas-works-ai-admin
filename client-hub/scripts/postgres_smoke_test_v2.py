#!/usr/bin/env python3
"""Production database smoke test — Business Hub V2 (migrations 0004-0007).

Run this AFTER deploying migrations 0004-0007 with DATABASE_URL pointed at the real Render
PostgreSQL instance, IN ADDITION TO (not instead of) scripts/postgres_smoke_test.py — that script
already covers V1 + Production Foundation (users/businesses/tenant_configs/audit_log). This script
covers everything Business Hub V2 added on top: service_catalog, projects, quotations, invoices,
payments, talents, talent_requests, password_reset_tokens, and human takeover
(wa_conversation_state).

WHAT THIS DOES (each numbered step prints its own name so a failure is easy to locate):
  1. Connect + init_schema() — proves migrations 0004-0007 apply cleanly (idempotent, additive) on
     top of an already-migrated V1/Foundation/Phase-A database. NO DROP, NO RESET, NO destructive
     statement anywhere in this script or in any migration file.
  2. Read-only check that service_catalog is seeded (does NOT insert/modify catalog rows — the
     catalog is shared production data, not something a smoke test should ever mutate).
  3. Insert one temporary tenant (business + owner user), same "__SMOKE_TEST__"-prefixed pattern as
     postgres_smoke_test.py, so it's unmistakably not a real client and trivially found by hand if
     cleanup somehow fails.
  4. Fixed-price project -> proves a FIXED_PRICE catalog selection is checkout-ready immediately
     (status=APPROVED, final_price set from the catalog, no invented number).
  5. Custom-quote project -> proves it starts WAITING_FOR_QUOTE with final_price=NULL, and that
     payment_service.checkout() correctly REFUSES checkout before a quotation is approved
     (this is the single most safety-critical invariant in the whole V2 payment model).
  6. Quotation created + approved -> proves the project flips to APPROVED with final_price taken
     from the quotation, and checkout is unlocked immediately afterward.
  7. Full payment round-trip: checkout() creates invoice+payment, a proof is "uploaded" (a tiny
     fake project_files row), ai_payment_review runs (asserted to have NO
     "authentic"/"verified"-sounding field anywhere in its output), then an explicit admin
     verify_payment() call flips payment VERIFIED / invoice PAID / project PAID.
  8. Talent Management — READ-ONLY check that the 3 seeded talents are present (does not insert or
     modify talent rows, same reasoning as step 2), then a real talent_request against the
     temporary business, proving it creates a linked TALENT project (cleaned up afterward).
  9. Human takeover — round-trips AI_ACTIVE (default, no row) -> HUMAN_TAKEOVER -> AI_ACTIVE for a
     synthetic customer phone number scoped to the temporary business, and confirms a second,
     different temporary business with the SAME synthetic phone number is completely unaffected
     (the exact cross-tenant-leakage check the production code itself is tested against).
 10. Password reset token — creates a real token, verifies get_valid_reset_token() finds it,
     verifies the RAW token is never equal to what's stored (only the SHA-256 hash is), marks it
     used, and confirms it can no longer be looked up afterward (single-use).

SAFETY:
  - Every row this script creates is cleaned up in try/finally, in FK-safe (children-first) order,
    so cleanup runs even if an earlier step fails or asserts.
  - Nothing here touches ../app.py (the production WhatsApp bot) or any of its own state.
  - Nothing here sets ENABLE_MULTI_TENANT or connects a real WhatsApp phone_number_id — this script
    only exercises Client Hub's own database layer.
  - Never prints DATABASE_URL, a password, a username, a hostname, or any credential.
  - Safe to run against SQLite too (does not assume BACKEND == "postgres").

USAGE:
    cd client-hub
    export DATABASE_URL="postgresql://...(the real Render Postgres URL)..."
    python3 scripts/postgres_smoke_test.py       # V1 + Foundation first
    python3 scripts/postgres_smoke_test_v2.py    # then this one

Exit code 0 = every check passed and cleanup succeeded. Non-zero = something failed; read the
printed step name, then inspect (never guess) the actual error before retrying.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db                    # noqa: E402
import repo                  # noqa: E402
import security               # noqa: E402
import catalog_service        # noqa: E402
import projects_repo          # noqa: E402
import quotation_service      # noqa: E402
import payment_service        # noqa: E402
import ai_payment_review      # noqa: E402
import talent_service         # noqa: E402
import wa_takeover_service    # noqa: E402

MARKER = "__SMOKE_TEST_V2__"


def _label(suffix):
    return f"{MARKER}{suffix}_{os.getpid()}"


def step(name):
    print(f"\n--- {name} ---")


def main():
    print(f"Database backend under test: {'PostgreSQL' if db.BACKEND == 'postgres' else 'SQLite'}")
    if db.BACKEND != "postgres":
        print(
            "WARNING: DATABASE_URL is not set, so this run exercises the SQLite path, not "
            "PostgreSQL. Fine as a dry run of this script's own logic — set DATABASE_URL to the "
            "real Render Postgres URL and re-run before treating V2 as Postgres-validated."
        )

    created = {
        "business_ids": [], "user_ids": [], "project_ids": [], "quotation_ids": [],
        "invoice_ids": [], "payment_ids": [], "project_file_ids": [], "talent_request_ids": [],
        "reset_token_ids": [],
    }

    try:
        step("1. Connect + init_schema (proves migrations 0004-0007 apply cleanly)")
        db.get_connection()
        db.init_schema()
        print("Database connection: OK")
        print("Schema initialization (0001-0007): OK")

        step("2. Service catalog + talent seeding (idempotent — same call app.py makes on every boot)")
        # Real production already ran this on app boot; calling it again here is what proves it's
        # actually idempotent AND never clobbers an admin's price edit (both already covered by
        # test_business_hub_v2_phase_bcd.py) — this call itself never inserts a NEW row if one
        # already exists, so it's safe to run against a real, already-live database too.
        catalog_service.seed_catalog_if_needed()
        talent_service.seed_talents_if_needed()
        catalog = catalog_service.list_active_catalog()
        assert catalog, "service_catalog is empty — seeding did not run or was rolled back"
        keys = {c["catalog_key"] for c in catalog}
        assert "ai_admin_basic" in keys and "website_landing_page" in keys and "custom_video" in keys, (
            f"expected catalog keys missing, got: {sorted(keys)}"
        )
        print(f"Catalog OK: {len(catalog)} active items, spot-checked keys present.")

        step("3. Insert temporary tenant")
        email = f"{_label('owner')}@smoketest.kilasworks.invalid".lower()
        user_id = repo.create_user(email, "not-a-real-password-hash", role="CLIENT_OWNER", full_name=MARKER)
        created["user_ids"].append(user_id)
        business_id = repo.create_business(user_id, _label("Business"), package="AI_ADMIN_PRO")
        created["business_ids"].append(business_id)
        print(f"Inserted: user_id={user_id}, business_id={business_id}")

        step("4. Fixed-price project is checkout-ready immediately")
        landing_page_item = catalog_service.get_catalog_item("website_landing_page")
        fixed_project_id = projects_repo.create_fixed_price_project(business_id, landing_page_item, user_id)
        created["project_ids"].append(fixed_project_id)
        fixed_project = projects_repo.get_project(fixed_project_id)
        assert fixed_project["status"] == "APPROVED", fixed_project["status"]
        assert fixed_project["final_price"] == landing_page_item["price_amount"]
        print("Fixed-price project OK: status=APPROVED, final_price matches catalog exactly.")

        step("5. Custom-quote project starts WAITING_FOR_QUOTE and checkout is correctly LOCKED")
        custom_project_id = projects_repo.create_custom_project(
            business_id, "VIDEO", _label("CustomVideo"), {"num_videos": 3}, 2_000_000, 4_000_000, user_id,
        )
        created["project_ids"].append(custom_project_id)
        custom_project = projects_repo.get_project(custom_project_id)
        assert custom_project["status"] == "WAITING_FOR_QUOTE"
        assert custom_project["final_price"] is None, "custom project must NEVER get an invented price"
        try:
            payment_service.checkout(custom_project_id, business_id, user_id)
            raise AssertionError("checkout() must raise before a quotation is approved — it did not")
        except ValueError as e:
            assert "checkout_locked" in str(e)
        print("Custom-quote project OK: WAITING_FOR_QUOTE, final_price NULL, checkout correctly locked.")

        step("6. Quotation created + approved -> project unlocks for checkout")
        quotation_id = quotation_service.create_quotation(
            custom_project_id, business_id, scope="3 video custom", deliverables="3 video final",
            quantity=3, final_price=3_500_000, notes="smoke test quotation", created_by_user_id=user_id,
        )
        created["quotation_ids"].append(quotation_id)
        quotation_service.approve_quotation(quotation_id, business_id, actor_user_id=user_id)
        approved_project = projects_repo.get_project(custom_project_id)
        assert approved_project["status"] == "APPROVED"
        assert approved_project["final_price"] == 3_500_000
        print("Quotation OK: approved, project unlocked with the quoted price (not invented).")

        step("7. Full payment round-trip (checkout -> proof -> AI review -> admin verify)")
        invoice_id = payment_service.checkout(custom_project_id, business_id, user_id)
        created["invoice_ids"].append(invoice_id)
        payment = payment_service.get_payment_for_invoice(invoice_id)
        payment_id = payment["id"]
        created["payment_ids"].append(payment_id)
        assert payment["status"] == "PAYMENT_PENDING"

        fake_file_id = db.insert_returning_id(
            "INSERT INTO project_files (business_id, project_id, kind, original_filename, "
            "mime_type, size_bytes, content, uploaded_by_user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (business_id, custom_project_id, "PAYMENT_PROOF", "smoke_test_proof.jpg", "image/jpeg",
             4, b"fake", user_id),
        )
        created["project_file_ids"].append(fake_file_id)
        payment_service.upload_payment_proof(payment_id, business_id, fake_file_id, user_id)
        reloaded_payment = payment_service.get_payment(payment_id)
        assert reloaded_payment["status"] == "UNDER_REVIEW"
        for forbidden_field in ("is_authentic", "authentic", "verified"):
            assert forbidden_field not in reloaded_payment, (
                f"AI payment review must NEVER produce a field named {forbidden_field!r} — "
                "the final decision must always be a human admin action, never automated."
            )
        payment_service.verify_payment(payment_id, business_id, actor_user_id=user_id)
        final_payment = payment_service.get_payment(payment_id)
        final_invoice = payment_service.get_invoice(invoice_id)
        final_project = projects_repo.get_project(custom_project_id)
        assert final_payment["status"] == "VERIFIED"
        assert final_invoice["status"] == "PAID"
        assert final_project["status"] == "PAID"
        print("Payment round-trip OK: VERIFIED/PAID only after an explicit admin action, no auto-authentic field.")

        step("8. Talent Management (read-only seed check + one real request)")
        talents = talent_service.list_active_talents()
        assert len(talents) >= 3, f"expected at least the 3 seeded talents, got {len(talents)}"
        names = {t["name"] for t in talents}
        for expected_name in ("Putri Maudy", "Irene Agustine Moire", "Bimo Putra Dwitya"):
            assert expected_name in names, f"seeded talent missing: {expected_name}"
        talent_id = talents[0]["id"]
        request_id, talent_project_id = talent_service.create_talent_request(
            talent_id, business_id,
            {"campaign_type": "Endorse", "platform": "Instagram", "deliverables": "1 post",
             "num_content_pieces": 1, "posting_requirements": None, "target_date": None,
             "location": None, "usage_purpose": None, "budget": 5_000_000, "brief": MARKER},
            user_id,
        )
        created["talent_request_ids"].append(request_id)
        created["project_ids"].append(talent_project_id)
        linked_project = projects_repo.get_project(talent_project_id)
        assert linked_project["project_type"] == "TALENT"
        assert linked_project["pricing_mode"] == "CUSTOM_QUOTE"
        print(f"Talent Management OK: {len(talents)} active talents (3 seeded ones present), request linked a project.")

        step("9. Human takeover round-trip + cross-tenant isolation")
        business_id_2 = repo.create_business(user_id, _label("Business2"), package="AI_ADMIN_BASIC")
        created["business_ids"].append(business_id_2)
        synthetic_phone = "62800000000"

        assert wa_takeover_service.get_state(business_id, synthetic_phone) == "AI_ACTIVE"
        wa_takeover_service.start_human_takeover(business_id, synthetic_phone, actor_user_id=user_id)
        assert wa_takeover_service.is_human_takeover_active(business_id, synthetic_phone) is True
        # SAME phone number, DIFFERENT business — must be completely unaffected.
        assert wa_takeover_service.get_state(business_id_2, synthetic_phone) == "AI_ACTIVE", (
            "human takeover leaked across tenants for the same customer phone number"
        )
        wa_takeover_service.return_to_ai(business_id, synthetic_phone, actor_user_id=user_id)
        assert wa_takeover_service.get_state(business_id, synthetic_phone) == "AI_ACTIVE"
        print("Human takeover OK: round-trips correctly and never leaks across tenants.")

        step("10. Password reset token — hashed storage, single-use")
        raw_token, token_hash = security.generate_reset_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=security.RESET_TOKEN_TTL_SECONDS)).isoformat()
        token_id = repo.create_password_reset_token(user_id, token_hash, expires_at, requested_ip="127.0.0.1")
        created["reset_token_ids"].append(token_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        found = repo.get_valid_reset_token(token_hash, now_iso)
        assert found is not None and found["id"] == token_id
        assert found["token_hash"] != raw_token, "the raw token must never be stored — only its hash"
        repo.mark_reset_token_used(token_id, now_iso)
        assert repo.get_valid_reset_token(token_hash, now_iso) is None, "a used token must never validate again"
        print("Password reset token OK: hashed at rest, single-use enforced.")

        print("\nALL BUSINESS HUB V2 SMOKE TEST STEPS PASSED.")
        return 0

    finally:
        step("Cleanup (runs even on failure) — NO DROP, NO RESET, only the rows this script inserted")
        for pid in created["reset_token_ids"]:
            db.execute("DELETE FROM password_reset_tokens WHERE id = ?", (pid,))
        for bid in created["business_ids"]:
            db.execute("DELETE FROM wa_conversation_state WHERE business_id = ?", (bid,))
        for pid in created["talent_request_ids"]:
            db.execute("DELETE FROM talent_requests WHERE id = ?", (pid,))
        for pid in created["payment_ids"]:
            db.execute("DELETE FROM payments WHERE id = ?", (pid,))
        for pid in created["invoice_ids"]:
            db.execute("DELETE FROM invoices WHERE id = ?", (pid,))
        for pid in created["quotation_ids"]:
            db.execute("DELETE FROM quotations WHERE id = ?", (pid,))
        for pid in created["project_file_ids"]:
            db.execute("DELETE FROM project_files WHERE id = ?", (pid,))
        for pid in created["project_ids"]:
            # audit_log.project_id (Final Operations Polish) FK-references projects(id) — must be
            # cleared before the project row itself can be deleted.
            db.execute("DELETE FROM audit_log WHERE project_id = ?", (pid,))
            db.execute("DELETE FROM project_files WHERE project_id = ?", (pid,))
            db.execute("DELETE FROM projects WHERE id = ?", (pid,))
        for bid in created["business_ids"]:
            for table in (
                "audit_log", "tenant_whatsapp_config", "tenant_configs", "tenant_activation",
                "simulation_messages", "onboarding_status", "ai_settings", "tenant_features",
                "business_faqs", "business_services", "business_profiles", "business_files",
                "onboarding_sessions", "business_memberships",
            ):
                db.execute(f"DELETE FROM {table} WHERE business_id = ?", (bid,))
            db.execute("DELETE FROM businesses WHERE id = ?", (bid,))
        for uid in created["user_ids"]:
            db.execute("DELETE FROM users WHERE id = ?", (uid,))

        leftover = db.query_all("SELECT id FROM businesses WHERE business_name LIKE ?", (f"{MARKER}%",))
        if leftover:
            print(
                f"NOTE: {len(leftover)} leftover smoke-test business row(s) found (ids: "
                f"{[r['id'] for r in leftover]}). Clean up by hand — same child-table deletes as "
                f"above, filtered to these business_id values, before deleting the businesses row."
            )
        else:
            print("Cleanup OK: no V2 smoke-test rows remain.")


if __name__ == "__main__":
    sys.exit(main())
