"""Inactive, explicitly priced Work steps; internal calls never consume Chat units.

Only a configured per-successful-logical-step contract is implemented here.
There is no default Work tariff, Free Work allowance or sandbox conversion.
"""

from contextvars import ContextVar
import hashlib
import json
import os
import db
from . import credit_policy as policy, credit_wallet as wallet, usage

CURRENT = ContextVar("kilas_credit_work_step", default=None)
KINDS = {
    "AI_TEXT": "WORK_TEXT",
    "WEB": "WORK_WEB",
    "WATCH": "WORK_WATCH",
    "DOCUMENT": "WORK_DOCUMENT",
    "PROJECT": "WORK_PROJECT",
}
OPERATIONS = {"text", "search", "author", "native"}


def kind(step):
    if step["worker"] == "CODE":
        data = json.loads(step["input_json"])
        return (
            "WORK_CODE"
            if step["action"] == "patch" and data.get("patch") == "__GENERATE__"
            else "WORK_EXECUTION"
            if step["action"] == "test"
            else None
        )
    if step["worker"] == "EXECUTION":
        return "WORK_EXECUTION"
    if step["worker"] == "MARKET":
        return "WORK_MARKET"
    return KINDS.get(step["worker"])


def terms(pricing):
    try:
        config = json.loads(os.environ.get("KILAS_CREDIT_TARIFFS_JSON", "{}"))
        value = config["limits"][pricing]
        if (
            pricing == "WORK_WATCH"
            and config.get("watch_billing") != "per_completed_observation"
        ):
            raise ValueError()
        if (
            config["version"] != "customer-credit-v1"
            or config.get("work_allocation") != "per_successful_logical_step"
        ):
            raise ValueError()
        if config["rates"][pricing]["units"] != 1:
            raise ValueError()
        if (
            not isinstance(value["operations"], dict)
            or not value["operations"]
            or set(value["operations"]) - OPERATIONS
        ):
            raise ValueError()
        for item in value["operations"].values():
            if (
                not isinstance(item["models"], list)
                or not item["models"]
                or any(not isinstance(m, str) for m in item["models"])
                or type(item["max_calls"]) is not int
                or not 1 <= item["max_calls"] <= 4
                or type(item["input_bytes"]) is not int
                or not 1 <= item["input_bytes"] <= 2000000
                or type(item["output_tokens"]) is not int
                or not 1 <= item["output_tokens"] <= 24576
            ):
                raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise wallet.WalletError("work_terms_unapproved") from None


def contract(job, step):
    from . import credit_work, model_policy

    pricing = kind(step)
    if pricing in ("WORK_EXECUTION", "WORK_MARKET"):
        raise wallet.WalletError("work_funding_transition_unapproved")
    if not pricing:
        raise wallet.WalletError("work_operation_unpriced")
    checkpoint = json.loads(job["checkpoint_json"])
    from .workspace_execution_worker import requested

    if step["worker"] == "PROJECT" and (
        checkpoint.get("generate_outputs")
        or requested(json.loads(step["input_json"]).get("request", ""))
    ):
        raise wallet.WalletError("work_funding_transition_unapproved")
    bounds = terms(pricing)
    runtime = {
        "chat": model_policy.luna_model(),
        "complex": model_policy.SOL,
        "web": os.environ.get("KILAS_AI_OPENAI_WEB_MODEL", ""),
        "selected": checkpoint.get("author_model"),
    }
    # Stored source IDs are immutable and account scoped. Include the owned source
    # content when an existing document/project is being revised.
    sources = {}
    if checkpoint.get("document_source_id"):
        from . import work_artifacts

        sources["document"] = policy.fingerprint(
            work_artifacts.source(
                job["user_id"],
                checkpoint["document_source_id"],
                job["origin_conversation_id"],
            )
        )
    if step["worker"] == "PROJECT":
        from .workspace_projects import sources as project_sources

        sources["project"] = policy.fingerprint(project_sources(job, checkpoint))
    if step["worker"] == "CODE":
        from .agent_workers import code_worker

        data = json.loads(step["input_json"])
        workspace = code_worker.prepare(job, data["repo"])
        if workspace:
            sources["code"] = policy.fingerprint(
                code_worker.snapshot(workspace)["content"]
            )
    key = step["idempotency_key"]
    # A successful quiet observation schedules a distinct next occurrence. An
    # attempt number, retry, timeout or process restart is never a new occurrence.
    if step["worker"] == "WATCH":
        waiting = db.query_one(
            "SELECT operation_key FROM kilas_credit_work_waits WHERE user_id=? AND step_id=? AND state IN ('WAITING','APPROVED') ORDER BY created_at DESC LIMIT 1",
            (job["user_id"], step["id"]),
        )
        key = (
            waiting["operation_key"]
            if waiting
            else key
            + ":watch:"
            + policy.fingerprint(
                {"due": job["next_wake_at"], "previous": step["output_json"]}
            )[:24]
        )
    return {
        "key": key,
        "credit_mode": True,
        "pricing_feature": pricing,
        "bounds": bounds,
        "profile": {
            "credit_fingerprint": policy.fingerprint(
                {
                    "contract": "work-logical-step-v1",
                    "job": job["id"],
                    "step": step["id"],
                    "request": credit_work.job_digest(job, step),
                    "runtime": runtime,
                    "sources": sources,
                    "bounds": bounds,
                    "pricing": pricing,
                }
            )
        },
    }


def supplier_only_in(conn, user):
    context = CURRENT.get()
    if not context:
        return False
    if context["job"]["user_id"] != user:
        raise wallet.WalletError("work_account_changed")
    row = usage._query(
        conn,
        "SELECT status,fingerprint FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?",
        (user, context["spec"]["key"]),
        one=True,
    )
    if not row or tuple(row) != (
        "RESERVED",
        context["spec"]["profile"]["credit_fingerprint"],
    ):
        raise wallet.WalletError("work_admission_closed")
    return True


def before_provider(operation, model, payload, output_tokens):
    context = CURRENT.get()
    if not context:
        return
    from . import autonomous_store as store

    spec = context["spec"]
    item = spec["bounds"]["operations"].get(operation)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    count = context["counts"].get(operation, 0)
    if (
        not item
        or model not in item["models"]
        or len(serialized) > item["input_bytes"]
        or type(output_tokens) is not int
        or not 0 < output_tokens <= item["output_tokens"]
        or count >= item["max_calls"]
    ):
        raise wallet.WalletError("work_provider_bounds")
    job = context["job"]
    with wallet._locked(job["user_id"]) as conn:
        if not store.locked(conn, job["id"], job["lease_token"], job["revision"]):
            raise wallet.WalletError("work_cancelled")
        ordinal = context["started"]
        usage._query(
            conn,
            "INSERT INTO kilas_credit_work_calls(user_id,operation_key,ordinal,kind,model,fingerprint) VALUES (?,?,?,?,?,?)",
            (
                job["user_id"],
                spec["key"],
                ordinal,
                operation,
                model,
                hashlib.sha256(serialized).hexdigest(),
            ),
        )
    context["counts"][operation] = count + 1
    context["started"] += 1


def provider_done():
    context = CURRENT.get()
    if context:
        context["completed"] += 1


def _metadata(context, *, success=False, known=False):
    return {
        "key": context["spec"]["key"],
        "fingerprint": context["spec"]["profile"]["credit_fingerprint"],
        "success": success,
        "known": known or context["started"] == context["completed"],
    }


def execute(job, step, callback):
    if not policy.enabled():
        from .credit_work import guard_mode

        guard_mode(job, step)
        return callback()
    pricing = kind(step)
    if not pricing:
        return callback()
    conn = usage._connect()
    try:
        legacy = (
            policy.owner(conn, job["user_id"])
            or usage._plan(conn, job["user_id"], usage._now())[0] != "FREE"
        )
    finally:
        conn.close()
    if legacy:
        return callback()
    from . import credit_work

    spec = contract(job, step)
    admitted = policy.admit(
        job["user_id"],
        spec["key"],
        "WORK",
        1,
        spec["profile"]["credit_fingerprint"],
        pricing_feature=pricing,
    )
    if not admitted["dispatch"]:
        error = wallet.WalletError("work_dispatch_closed")
        error._credit_work = {
            "key": spec["key"],
            "fingerprint": spec["profile"]["credit_fingerprint"],
            "success": False,
            "known": False,
        }
        raise error
    context = {
        "job": job,
        "step": step,
        "spec": spec,
        "started": 0,
        "completed": 0,
        "counts": {},
    }
    try:
        credit_work.dispatch(job, step, spec)
        marker = CURRENT.set(context)
        try:
            result = callback()
        finally:
            CURRENT.reset(marker)
        if context["started"] and context["started"] != context["completed"]:
            result._credit_work = _metadata(context)
        else:
            result._credit_work = _metadata(
                context,
                success=result.verified and result.status in ("SUCCEEDED", "WAITING"),
                known=True,
            )
        return result
    except Exception as error:
        known = bool(getattr(error, "usage", {}).get("provider_rejected"))
        meta = _metadata(context, known=known)
        error._credit_work = meta
        # Release known failures even if the worker lease is already cancelled.
        # Unknown supplier outcomes remain reserved for existing human review.
        if meta["known"]:
            policy.finish(
                job["user_id"], spec["key"], 0, success=False, definitive_failure=True
            )
        raise


def finish_in(conn, job, result):
    meta = getattr(result, "_credit_work", None)
    if not meta:
        return
    policy.finish_in(
        conn,
        job["user_id"],
        meta["key"],
        1 if meta["success"] else 0,
        success=meta["success"],
        definitive_failure=meta["known"],
    )
