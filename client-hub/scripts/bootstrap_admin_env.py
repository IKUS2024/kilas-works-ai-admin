#!/usr/bin/env python3
"""
One-time non-interactive bootstrap for the FIRST Kilas Works admin on Render Free.

Use only for the initial admin account, then immediately remove the
BOOTSTRAP_ADMIN_* environment variables and restore the normal Start Command.

Required environment variables:
  BOOTSTRAP_ADMIN_EMAIL
  BOOTSTRAP_ADMIN_PASSWORD
  BOOTSTRAP_ADMIN_CONFIRM=CREATE_FIRST_KILAS_ADMIN

Safety:
- Refuses to run without the exact confirmation phrase.
- Refuses if any KILAS_ADMIN already exists.
- Refuses if the requested email already exists with another role.
- Never prints the password.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db          # noqa: E402
import repo        # noqa: E402
import security    # noqa: E402

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONFIRM_VALUE = "CREATE_FIRST_KILAS_ADMIN"


def fail(message):
    print(f"REFUSED: {message}", file=sys.stderr)
    return 1


def main():
    confirm = os.environ.get("BOOTSTRAP_ADMIN_CONFIRM", "")
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")

    if confirm != CONFIRM_VALUE:
        return fail(
            "BOOTSTRAP_ADMIN_CONFIRM must equal CREATE_FIRST_KILAS_ADMIN."
        )

    if not email or not EMAIL_RE.match(email):
        return fail("BOOTSTRAP_ADMIN_EMAIL is missing or invalid.")

    if len(password) < 12:
        return fail("BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters.")

    existing_admin = db.query_one(
        "SELECT id, email, role FROM users WHERE role = ? LIMIT 1",
        ("KILAS_ADMIN",),
    )
    if existing_admin is not None:
        return fail(
            f"a KILAS_ADMIN already exists ({existing_admin['email']}); "
            "this bootstrap only creates the first admin."
        )

    existing_user = repo.get_user_by_email(email)
    if existing_user is not None:
        return fail(
            f"a user with email {email!r} already exists "
            f"(role={existing_user['role']}); refusing to change its role."
        )

    password_hash = security.hash_password(password)
    user_id = repo.create_user(
        email,
        password_hash,
        role="KILAS_ADMIN",
        full_name="Kilas Works Admin",
    )
    repo.write_audit_no_business(
        user_id,
        "ADMIN_BOOTSTRAPPED",
        f"email={email}; method=render_free_env_bootstrap",
    )

    print(
        f"OK: first KILAS_ADMIN created (id={user_id}, email={email}). "
        "Immediately remove BOOTSTRAP_ADMIN_EMAIL, "
        "BOOTSTRAP_ADMIN_PASSWORD, and BOOTSTRAP_ADMIN_CONFIRM, "
        "then restore the normal Start Command."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
