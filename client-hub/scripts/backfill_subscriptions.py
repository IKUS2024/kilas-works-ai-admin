#!/usr/bin/env python3
"""Backfill missing `subscriptions` rows for pre-existing ACTIVE AI Admin tenants — Fix 5
(production-safety patch, follows Area E). Same operator-run-script trust model as
scripts/bootstrap_admin.py: this is NOT an HTTP route (a public/admin-authenticated route that can
write billing-period data is unnecessary attack surface for a one-off migration-adjacent task —
shell access to the deployment is already a higher trust bar).

WHY THIS EXISTS: migration 0014 only CREATES the `subscriptions` table — it does not (and must
not) retroactively invent a billing period for a tenant that was activated before that table
existed. A tenant activated before this deploy could therefore be ACTIVE with package
AI_ADMIN_BASIC/AI_ADMIN_PRO and NO subscription row at all. As of the Fix 4 audit,
app.py's _tenant_subscription_permits_ai_runtime_safe() now REQUIRES a subscription row in ACTIVE
or GRACE state before the live bot will serve that tenant's customers — so an un-backfilled
pre-existing tenant would otherwise go silent (fail closed, correctly, but not usefully) the next
time /webhook resolves it. This script lets Kilas Admin close that gap deliberately, tenant by
tenant, using each tenant's REAL verified billing history — never a guess.

SAFETY MODEL:
  - Default mode is DRY RUN / LIST ONLY. No flag needed to list; a flag IS needed to write.
  - The list output never includes a token, credentials_reference, or anything from
    tenant_whatsapp_config — only business_id, business_name, package, and created_at (enough to
    identify the business and look up its real billing history elsewhere, e.g. payment records or
    an external invoice system).
  - A write requires ALL of: --business-id, --period-start, --period-end, AND --confirm. There is
    no "backfill everything found" bulk-write mode — every write is a single, deliberate,
    Kilas-Admin-reviewed action for one business at a time, using dates Kilas Admin explicitly
    supplies (this script performs zero date arithmetic of its own — see
    subscription_service.create_subscription_with_explicit_period()'s docstring for why).
  - Never touches a business whose package is "NONE" (creative-services-only — no subscription
    concept applies) or that already has a subscriptions row (idempotent no-op, matching
    create_subscription()'s own idempotency contract).
  - Running the list/dry-run step (or even re-running a write for an already-backfilled business)
    repeatedly is always safe — nothing is ever overwritten once a subscription row exists.

USAGE (run from wherever DATABASE_URL / CLIENT_HUB_DB_PATH is already configured — a Render Shell
against the Client Hub service, or locally against the same DATABASE_URL):

    cd client-hub

    # Step 1 — ALWAYS list first. Shows every ACTIVE AI Admin business with no subscription row.
    python3 scripts/backfill_subscriptions.py --list

    # Step 2 — for EACH business Kilas Admin has verified the real billing period for, backfill
    # it explicitly, one at a time (dates are the tenant's REAL current billing period, sourced by
    # Kilas Admin from their own records — e.g. when they were actually last paid/invoiced):
    python3 scripts/backfill_subscriptions.py \\
        --business-id 42 \\
        --period-start 2026-08-01 \\
        --period-end   2026-09-01 \\
        --grace-days 3 \\
        --confirm

    # Step 3 — re-run --list to confirm the business no longer appears (it now has a row).
    python3 scripts/backfill_subscriptions.py --list
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import repo  # noqa: E402
import subscription_service  # noqa: E402


def _print_list(rows):
    if not rows:
        print("No ACTIVE AI Admin business is missing a subscription row. Nothing to backfill.")
        return
    print(f"{len(rows)} ACTIVE AI Admin business(es) missing a subscription row:\n")
    print(f"{'business_id':<12} {'package':<16} {'business_name':<30} {'activated/created_at'}")
    print("-" * 90)
    for row in rows:
        print(f"{row['business_id']:<12} {row['package']:<16} {(row['business_name'] or '')[:30]:<30} {row['created_at']}")
    print(
        "\nTo backfill one of these (after verifying its real billing period from your own "
        "records), run:\n"
        "  python3 scripts/backfill_subscriptions.py --business-id <id> "
        "--period-start YYYY-MM-DD --period-end YYYY-MM-DD --confirm"
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list", action="store_true",
                         help="List ACTIVE AI Admin businesses missing a subscription row (default action if no --business-id given).")
    parser.add_argument("--business-id", type=int, default=None,
                         help="Business to backfill. Requires --period-start, --period-end, and --confirm.")
    parser.add_argument("--period-start", default=None, help="ISO date/datetime, e.g. 2026-08-01")
    parser.add_argument("--period-end", default=None, help="ISO date/datetime, e.g. 2026-09-01")
    parser.add_argument("--grace-days", type=int, default=subscription_service.DEFAULT_GRACE_DAYS,
                         help=f"Default {subscription_service.DEFAULT_GRACE_DAYS}.")
    parser.add_argument("--confirm", action="store_true",
                         help="Required to actually write. Without it, a --business-id run is a dry-run preview only.")
    parser.add_argument("--actor-admin-id", type=int, default=None,
                         help="KILAS_ADMIN user id to attribute the audit log entry to (recommended). "
                              "If omitted, the audit entry is recorded with no actor.")
    args = parser.parse_args()

    if args.business_id is None:
        _print_list(subscription_service.list_active_ai_admin_businesses_missing_subscription())
        return

    business = repo.get_business(args.business_id)
    if not business:
        print(f"ERROR: business_id={args.business_id} not found.")
        sys.exit(1)
    if business["status"] != "ACTIVE":
        print(f"ERROR: business_id={args.business_id} is status={business['status']!r}, not ACTIVE — refusing to backfill.")
        sys.exit(1)
    if business["package"] not in ("AI_ADMIN_BASIC", "AI_ADMIN_PRO"):
        print(f"ERROR: business_id={args.business_id} has package={business['package']!r} — no AI Admin subscription applies. Refusing.")
        sys.exit(1)
    existing = subscription_service.get_subscription(args.business_id)
    if existing:
        print(f"business_id={args.business_id} already has a subscription row (status={existing['status']!r}) — nothing to do.")
        return

    if not args.period_start or not args.period_end:
        print("ERROR: --period-start and --period-end are required to backfill a specific business "
              "(this script never invents a billing date). Use --list first if you haven't verified "
              "this business's real billing period yet.")
        sys.exit(1)

    plan_key = subscription_service.plan_key_for_package(business["package"])
    print(
        f"About to backfill: business_id={args.business_id} "
        f"({business['business_name']!r}, package={business['package']}) "
        f"plan_key={plan_key} period_start={args.period_start} period_end={args.period_end} "
        f"grace_days={args.grace_days}"
    )
    if not args.confirm:
        print("DRY RUN (no --confirm given) — nothing written. Re-run with --confirm to actually create this row.")
        return

    sub = subscription_service.create_subscription_with_explicit_period(
        args.business_id, plan_key, args.period_start, args.period_end,
        actor_user_id=args.actor_admin_id, grace_days=args.grace_days,
    )
    print(f"OK — subscription row created: {dict(sub)}")


if __name__ == "__main__":
    main()
