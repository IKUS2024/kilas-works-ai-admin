#!/usr/bin/env python3
"""Create the first KILAS_ADMIN account — Business Hub V2, Phase A.

WHY A SCRIPT AND NOT A ROUTE: an HTTP route that can create an admin account is itself a
production attack surface (anyone who finds the URL could try to use it). This is deliberately a
one-off, operator-run script instead — same trust model as running a Django `createsuperuser` or a
Rails `db:seed` task. It requires shell access to wherever Client Hub is deployed (Render Shell, or
running it once before first deploy against the same DATABASE_URL), which is already a higher trust
bar than any public URL could be.

SAFETY:
  - Refuses to run unless the BOOTSTRAP_ADMIN_TOKEN environment variable is set AND matches the
    --token argument exactly (constant-time compare) — this is a "you must already have privileged
    env access to this deployment" gate, not a guessable secret shipped in code.
  - Refuses to create a second admin with an email that already exists (use routes_admin's package/
    role management instead, once that exists, for promoting additional admins later — out of scope
    for Phase A, which only needs to unblock the FIRST admin account).
  - Password is read via getpass (never echoed to the terminal, never passed as a plain CLI arg
    that would land in shell history).
  - Every action is written to the SAME audit_log table Client Hub already uses.

USAGE (run once, from wherever DATABASE_URL / CLIENT_HUB_DB_PATH is already configured):
    cd client-hub
    export BOOTSTRAP_ADMIN_TOKEN="<a long random value only you know>"
    python3 scripts/bootstrap_admin.py --email admin@kilasworks.id --token "$BOOTSTRAP_ADMIN_TOKEN"
    (you will be prompted for a password interactively)

After the first admin exists, delete/rotate BOOTSTRAP_ADMIN_TOKEN — it has no further purpose once
at least one KILAS_ADMIN account exists, and leaving it set is unnecessary residual attack surface.
"""
import argparse
import getpass
import hmac
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db          # noqa: E402
import repo        # noqa: E402
import security    # noqa: E402

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the first KILAS_ADMIN account.")
    parser.add_argument("--email", required=True, help="Email for the new admin account.")
    parser.add_argument("--token", required=True, help="Must match BOOTSTRAP_ADMIN_TOKEN env var.")
    parser.add_argument("--full-name", default=None)
    args = parser.parse_args()

    expected_token = os.environ.get("BOOTSTRAP_ADMIN_TOKEN")
    if not expected_token:
        print("REFUSED: BOOTSTRAP_ADMIN_TOKEN is not set in this environment. Set it first, "
              "then re-run with the same value passed to --token.", file=sys.stderr)
        return 1
    if not hmac.compare_digest(expected_token, args.token):
        print("REFUSED: --token does not match BOOTSTRAP_ADMIN_TOKEN.", file=sys.stderr)
        return 1

    email = args.email.strip().lower()
    if not EMAIL_RE.match(email):
        print(f"REFUSED: {email!r} is not a valid email address.", file=sys.stderr)
        return 1

    db.init_schema()

    existing = repo.get_user_by_email(email)
    if existing is not None:
        print(f"REFUSED: a user with email {email!r} already exists (role={existing['role']}). "
              "This script only creates a NEW account — it will not change an existing one.",
              file=sys.stderr)
        return 1

    password = getpass.getpass("New admin password (min 8 chars, not echoed): ")
    if len(password) < 8:
        print("REFUSED: password must be at least 8 characters.", file=sys.stderr)
        return 1
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("REFUSED: passwords did not match.", file=sys.stderr)
        return 1

    password_hash = security.hash_password(password)
    user_id = repo.create_user(email, password_hash, role="KILAS_ADMIN", full_name=args.full_name)
    repo.write_audit_no_business(user_id, "ADMIN_BOOTSTRAPPED", f"email={email}")
    print(f"OK: KILAS_ADMIN account created (id={user_id}, email={email}). "
          f"You can now log in normally at /login. Consider unsetting BOOTSTRAP_ADMIN_TOKEN now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
