"""One-shot production account identity repair helper.

This module is intentionally inert unless every ACCOUNT_REPAIR_* environment variable is present
and ACCOUNT_REPAIR_ENABLED=1. It exists only to make a user-authorized production account repair
atomic and auditable without exposing password hashes or running ad-hoc writable SQL from tooling.

The repair swaps the desired login email away from a legacy account onto the real data-bearing
account, preserves the legacy account under an archive email, and copies the already-reset password
hash from the legacy login row to the real account so the user can immediately log in with the
password they just chose.

It is strict and idempotent:
- exact expected user IDs must match
- exact source/target/archive states are verified under row locks
- any unexpected state aborts startup rather than guessing
- a second run after successful repair is a no-op
"""

import os

import db


def _enabled():
    return (os.environ.get("ACCOUNT_REPAIR_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def run_from_env():
    if not _enabled():
        return False

    source_email = (os.environ.get("ACCOUNT_REPAIR_SOURCE_EMAIL") or "").strip().lower()
    target_email = (os.environ.get("ACCOUNT_REPAIR_TARGET_EMAIL") or "").strip().lower()
    archive_email = (os.environ.get("ACCOUNT_REPAIR_ARCHIVE_EMAIL") or "").strip().lower()
    source_id_raw = (os.environ.get("ACCOUNT_REPAIR_SOURCE_USER_ID") or "").strip()
    target_id_raw = (os.environ.get("ACCOUNT_REPAIR_TARGET_USER_ID") or "").strip()

    if not all((source_email, target_email, archive_email, source_id_raw, target_id_raw)):
        raise RuntimeError("Account repair enabled but configuration is incomplete.")
    if len({source_email, target_email, archive_email}) != 3:
        raise RuntimeError("Account repair emails must be distinct.")

    try:
        expected_source_id = int(source_id_raw)
        expected_target_id = int(target_id_raw)
    except ValueError as exc:
        raise RuntimeError("Account repair user IDs must be integers.") from exc

    if expected_source_id == expected_target_id:
        raise RuntimeError("Account repair source and target user IDs must differ.")

    conn = db.get_connection()
    cur = conn.cursor()
    try:
        # Lock every row that can participate in the swap so concurrent gunicorn startups cannot
        # interleave this repair.
        sql = db._adapt_placeholders(
            """SELECT id,email,password_hash FROM users
               WHERE lower(email) IN (lower(?), lower(?), lower(?))
               ORDER BY id FOR UPDATE"""
        )
        cur.execute(sql, (source_email, target_email, archive_email))
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description]
        by_email = {
            str(dict(zip(columns, row))["email"]).strip().lower(): dict(zip(columns, row))
            for row in rows
        }

        # Idempotent completed state: the data-bearing account already owns the desired login
        # address and the former legacy account is safely preserved under the archive address.
        completed_target = by_email.get(target_email)
        completed_archive = by_email.get(archive_email)
        if (
            completed_target
            and int(completed_target["id"]) == expected_source_id
            and completed_archive
            and int(completed_archive["id"]) == expected_target_id
            and source_email not in by_email
        ):
            conn.rollback()
            print("Account repair: already completed")
            return True

        source = by_email.get(source_email)
        target = by_email.get(target_email)
        if not source or int(source["id"]) != expected_source_id:
            raise RuntimeError("Account repair source account did not match the expected user.")
        if not target or int(target["id"]) != expected_target_id:
            raise RuntimeError("Account repair target account did not match the expected user.")
        if archive_email in by_email:
            raise RuntimeError("Account repair archive email is already in use.")

        # Preserve the password the user just reset on the mistaken legacy account without ever
        # reading or logging plaintext credentials.
        reset_password_hash = target["password_hash"]

        cur.execute(
            db._adapt_placeholders("UPDATE users SET email=? WHERE id=?"),
            (archive_email, expected_target_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Account repair could not archive the legacy login.")

        cur.execute(
            db._adapt_placeholders("UPDATE users SET email=?, password_hash=? WHERE id=?"),
            (target_email, reset_password_hash, expected_source_id),
        )
        if cur.rowcount != 1:
            raise RuntimeError("Account repair could not move the desired login to the source account.")

        # Burn any old reset links for both rows after the identity swap.
        cur.execute(
            db._adapt_placeholders(
                "UPDATE password_reset_tokens SET used_at=CURRENT_TIMESTAMP "
                "WHERE user_id IN (?,?) AND used_at IS NULL"
            ),
            (expected_source_id, expected_target_id),
        )

        # Leave a durable audit trail without storing emails/password material in the audit detail.
        cur.execute(
            db._adapt_placeholders(
                "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)"
            ),
            (expected_source_id, None, "ACCOUNT_IDENTITY_REPAIRED",
             "desired login reassigned to existing data-bearing account; legacy account preserved"),
        )
        cur.execute(
            db._adapt_placeholders(
                "INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)"
            ),
            (expected_target_id, None, "ACCOUNT_IDENTITY_ARCHIVED",
             "legacy login archived during authorized duplicate-account repair"),
        )

        conn.commit()
        print("Account repair: completed")
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
