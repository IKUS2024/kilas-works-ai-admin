"""Account/job-bound paid image consent; no worker dispatch from a consent POST."""

import json
import db
from . import (
    credit_policy as policy,
    credit_wallet as wallet,
    usage,
    autonomous_store as store,
)


def job_digest(job, step):
    return policy.fingerprint(
        {
            "instruction": job["instruction"],
            "constraints": job["constraints_json"],
            "checkpoint": job["checkpoint_json"],
            "origin": job["origin_conversation_id"],
            "worker": step["worker"],
            "action": step["action"],
            "input": step["input_json"],
            "key": step["idempotency_key"],
        }
    )


def rows(conn, user, job_id, step_id):
    suffix = " FOR UPDATE" if db.BACKEND == "postgres" else ""
    job = usage._query(
        conn,
        "SELECT * FROM kilas_agent_jobs WHERE id=? AND user_id=?" + suffix,
        (job_id, user),
        one=True,
    )
    step = usage._query(
        conn,
        "SELECT * FROM kilas_agent_steps WHERE id=? AND job_id=?" + suffix,
        (step_id, job_id),
        one=True,
    )
    # usage rows are positional, unlike the ordinary application db helpers.
    if not job or not step:
        raise wallet.WalletError("work_unavailable")

    def mapping(table, row):
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM " + table + " WHERE 1=0")
        names = [item[0] for item in cursor.description]
        cursor.close()
        return dict(zip(names, row))

    return mapping("kilas_agent_jobs", job), mapping("kilas_agent_steps", step)


def park(job, lease, step, error):
    if not policy.enabled() or step["worker"] != "IMAGE":
        return False
    token = policy.persist_consent(error)
    with wallet._locked(job["user_id"]) as conn:
        current, actual = rows(conn, job["user_id"], job["id"], step["id"])
        if (
            not store.locked(conn, job["id"], lease, job["revision"])
            or actual["status"] != "RUNNING"
        ):
            return False
        request = error.request
        if request[0] != job["user_id"] or request[1] != actual["idempotency_key"]:
            raise wallet.WalletError("work_quote_changed")
        usage._query(
            conn,
            "INSERT INTO kilas_credit_work_waits(token,user_id,job_id,step_id,operation_key,fingerprint,job_revision,job_digest,created_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(token) DO NOTHING",
            (
                token,
                job["user_id"],
                job["id"],
                step["id"],
                request[1],
                request[4],
                job["revision"],
                job_digest(current, actual),
                store.stamp(),
            ),
        )
        usage._query(
            conn,
            "UPDATE kilas_agent_steps SET status='NEEDS_APPROVAL',attempts=CASE WHEN attempts>0 THEN attempts-1 ELSE 0 END,error='credit_consent_required' WHERE id=?",
            (step["id"],),
        )
        usage._query(
            conn,
            "UPDATE kilas_agent_jobs SET status='NEEDS_APPROVAL',next_wake_at=NULL,last_error='credit_consent_required',updated_at=? WHERE id=?",
            (store.stamp(), job["id"]),
        )
    return True


def waiting(user, job_id):
    if not policy.enabled():
        return None
    return db.query_one(
        "SELECT token FROM kilas_credit_work_waits WHERE user_id=? AND job_id=? AND state='WAITING' ORDER BY created_at DESC LIMIT 1",
        (user, job_id),
    )


def decide(user, token, approve):
    with wallet._locked(user) as conn:
        wait = usage._query(
            conn,
            "SELECT job_id,step_id,operation_key,fingerprint,job_revision,job_digest,state FROM kilas_credit_work_waits WHERE user_id=? AND token=?",
            (user, token),
            one=True,
        )
        if not wait:
            return policy.consent_in(conn, user, token, approve)
        target = "APPROVED" if approve else "DECLINED"
        if wait[6] == target:
            return target
        if wait[6] != "WAITING":
            raise wallet.WalletError("work_consent_closed")
        job, step = rows(conn, user, wait[0], wait[1])
        if (
            job["status"] != "NEEDS_APPROVAL"
            or step["status"] != "NEEDS_APPROVAL"
            or job["revision"] != wait[4]
            or job_digest(job, step) != wait[5]
        ):
            raise wallet.WalletError("work_changed")
        # Resolve the actual configured model and exact immutable prompt again.
        from .agent_workers.image_worker import contract

        spec = contract(job, step, json.loads(step["input_json"]))
        if spec["key"] != wait[2] or spec["profile"]["credit_fingerprint"] != wait[3]:
            raise wallet.WalletError("work_changed")
        quote = usage._query(
            conn,
            "SELECT feature,maximum_units,quote_hash,terms_json FROM kilas_credit_consents WHERE token=?",
            (token,),
            one=True,
        )
        q = policy._quote(conn, user, wait[2], quote[0], quote[1], wait[3], None)
        if (
            policy.fingerprint(
                {
                    "feature": quote[0],
                    "maximum_units": quote[1],
                    "fingerprint": wait[3],
                    **q,
                }
            )
            != quote[2]
        ):
            raise wallet.WalletError("work_quote_changed")
        policy.consent_in(conn, user, token, approve)
        usage._query(
            conn,
            "UPDATE kilas_credit_work_waits SET state=? WHERE token=?",
            (target, token),
        )
        usage._query(
            conn,
            "UPDATE kilas_agent_steps SET status=?,error=? WHERE id=?",
            (
                "PENDING" if approve else "NEEDS_APPROVAL",
                None if approve else "credit_consent_declined",
                step["id"],
            ),
        )
        usage._query(
            conn,
            "UPDATE kilas_agent_jobs SET status=?,next_wake_at=?,revision=revision+1,last_error=?,updated_at=? WHERE id=?",
            (
                "RUNNING" if approve else "PAUSED",
                store.stamp() if approve else None,
                None if approve else "credit_consent_declined",
                store.stamp(),
                job["id"],
            ),
        )
        return target


def guard_mode(job, step):
    if policy.enabled():
        return
    conn = usage._connect()
    try:
        if not policy.table_exists(conn, "kilas_credit_work_waits"):
            return
        waiting = usage._query(
            conn,
            "SELECT 1 FROM kilas_credit_work_waits WHERE user_id=? AND operation_key=?",
            (job["user_id"], step["idempotency_key"]),
            one=True,
        )
        admitted = usage._query(
            conn,
            "SELECT 1 FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?",
            (job["user_id"], step["idempotency_key"]),
            one=True,
        )
        if waiting or admitted:
            raise wallet.WalletError("credit_policy_disabled")
    finally:
        conn.close()


def dispatch(job, step, spec):
    if not spec.get("credit_mode") and not policy.enabled():
        return
    with wallet._locked(job["user_id"]) as conn:
        current, actual = rows(conn, job["user_id"], job["id"], step["id"])
        if (
            not store.locked(conn, job["id"], job["lease_token"], job["revision"])
            or actual["status"] != "RUNNING"
            or job_digest(current, actual) != job_digest(job, step)
        ):
            raise wallet.WalletError("work_changed")
        admitted = usage._query(
            conn,
            "SELECT status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?",
            (job["user_id"], spec["key"]),
            one=True,
        )
        if (
            not admitted
            and not policy.owner(conn, job["user_id"])
            and (
                not policy.table_exists(conn, "kilas_ai_subscriptions")
                or usage._plan(conn, job["user_id"], usage._now())[0] == "FREE"
            )
        ) or (admitted and admitted[0] != "RESERVED"):
            raise wallet.WalletError("credit_admission_missing")
        old = usage._query(
            conn,
            "SELECT 1 FROM kilas_credit_work_operations WHERE user_id=? AND operation_key=?",
            (job["user_id"], spec["key"]),
            one=True,
        )
        if old:
            raise wallet.WalletError("work_dispatch_closed")
        usage._query(
            conn,
            "INSERT INTO kilas_credit_work_operations(user_id,operation_key,job_id,step_id,fingerprint,status,dispatched_at) VALUES (?,?,?,?,?,'DISPATCHED',?)",
            (
                job["user_id"],
                spec["key"],
                job["id"],
                step["id"],
                spec["profile"]["credit_fingerprint"],
                store.stamp(),
            ),
        )
        usage._query(
            conn,
            "UPDATE kilas_credit_work_waits SET state='CONSUMED' WHERE user_id=? AND operation_key=? AND state='APPROVED'",
            (job["user_id"], spec["key"]),
        )
