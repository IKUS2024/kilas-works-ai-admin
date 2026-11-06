"""Explicit inactive activation candidate; never imported by startup or routes.

This records reviewed evidence, not inferred credits or historical charges. An
operator must separately approve and execute the production transition. Existing
supplier unknowns are preserved; a fresh audit must classify customer gaps.
"""

from datetime import datetime, timezone, timedelta
import re
import os
import json
import hashlib
from pathlib import Path
import db
from . import credit_policy as policy, credit_wallet as wallet, usage

VERSION = "customer-credit-v1"
METER = "pcm-floor20ms-v1"


def stamp(value):
    if not isinstance(value, str):
        raise wallet.WalletError("activation_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise wallet.WalletError("activation_timestamp_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise wallet.WalletError("activation_requires_utc")
    return parsed.astimezone(timezone.utc).isoformat()


def prepare(*, cutoff, release_sha, tariff_digest, snapshot, baselines):
    if policy.enabled():
        raise wallet.WalletError("activation_must_be_disabled")
    if not re.fullmatch("[a-f0-9]{40}", release_sha) or not re.fullmatch(
        "[a-f0-9]{64}", tariff_digest
    ):
        raise wallet.WalletError("activation_identity_invalid")
    cutoff = stamp(cutoff)
    if (
        not isinstance(snapshot, dict)
        or type(snapshot.get("unresolved_nonowner_records")) is not int
        or type(snapshot.get("accepted_operations")) is not int
        or snapshot.get("meter_version") != METER
        or snapshot.get("unresolved_nonowner_records") != 0
        or snapshot.get("accepted_operations") != 0
        or not isinstance(snapshot.get("high_watermarks"), dict)
    ):
        raise wallet.WalletError("activation_review_required")
    normalized = []
    seen = set()
    for item in baselines:
        if (
            type(item.get("user_id")) is not int
            or item["user_id"] == policy.OWNER_ID
            or item.get("feature") not in policy.FREE
            or item.get("provenance")
            not in ("successful_usage", "successful_source_meter")
        ):
            raise wallet.WalletError("activation_baseline_unverified")
        start = (
            "LIFETIME"
            if item.get("period_start") == "LIFETIME"
            else stamp(item["period_start"])
        )
        end = "LIFETIME" if start == "LIFETIME" else stamp(item["period_end"])
        if start == "LIFETIME" and item["feature"] != "IMAGE":
            raise wallet.WalletError("activation_baseline_period_invalid")
        if start != "LIFETIME" and not start < end:
            raise wallet.WalletError("activation_baseline_period_invalid")
        units = wallet._amount(item["units"], zero=True)
        key = (item["user_id"], item["feature"], start)
        if key in seen:
            raise wallet.WalletError("activation_baseline_duplicate")
        seen.add(key)
        normalized.append((*key, end, units, item["provenance"]))
    digest = policy.fingerprint({"snapshot": snapshot, "baselines": sorted(normalized)})
    conn = usage._connect()
    try:
        if db.BACKEND == "postgres":
            usage._query(conn, "SELECT pg_advisory_xact_lock(74120602)")
        row = usage._query(
            conn,
            "SELECT cutoff,release_sha,tariff_digest,meter_version,snapshot_digest FROM kilas_credit_activation WHERE version=?",
            (VERSION,),
            one=True,
        )
        expected = (cutoff, release_sha, tariff_digest, METER, digest)
        if row:
            if tuple(row) != expected:
                raise wallet.WalletError("activation_record_immutable")
            conn.commit()
            return False
        now = usage._now()
        observed = usage._as_utc(stamp(snapshot["observed_at"]))
        if not timedelta(0) <= now - observed <= timedelta(minutes=5):
            raise wallet.WalletError("activation_audit_stale")
        if usage._as_utc(cutoff) < observed:
            raise wallet.WalletError("activation_cutoff_before_audit")
        if configured():
            verify_audit_in(conn, cutoff, normalized)
        usage._query(
            conn,
            "INSERT INTO kilas_credit_activation(version,cutoff,release_sha,tariff_digest,meter_version,snapshot_digest,created_at) VALUES (?,?,?,?,?,?,?)",
            (VERSION, *expected, now.isoformat()),
        )
        for user, feature, start, end, units, provenance in normalized:
            usage._query(
                conn,
                "INSERT INTO kilas_credit_quota_baselines(version,user_id,feature,period_start,period_end,units,provenance) VALUES (?,?,?,?,?,?,?)",
                (VERSION, user, feature, start, end, units, provenance),
            )
        payload = json.dumps(
            {"snapshot": snapshot, "baselines": sorted(normalized)},
            sort_keys=True,
            separators=(",", ":"),
        )
        usage._query(
            conn,
            "INSERT INTO kilas_credit_activation_payload(version,payload_json,baseline_digest,schema_checksum) VALUES (?,?,?,?)",
            (
                VERSION,
                payload,
                policy.fingerprint(sorted(normalized)),
                schema_checksum(),
            ),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def schema_checksum():
    return hashlib.sha256(
        Path(__file__).with_name("credit_wallet_schema.py").read_bytes()
    ).hexdigest()


def configured():
    # Candidate configuration is absent in production. No deployment or startup
    # manufactures a cutoff, baseline, approval or admission hold.
    return os.environ.get("KILAS_CREDIT_CUTOFF_CANDIDATE_ENABLED") == "yes"


def load_in(conn, *, admission=False):
    if not configured():
        return None
    if not policy.table_exists(conn, "kilas_credit_activation_payload"):
        raise wallet.WalletError("activation_record_required")
    if db.BACKEND == "postgres":
        usage._query(conn, "SELECT pg_advisory_xact_lock_shared(74120602)")
    version = os.environ.get("KILAS_CREDIT_ACTIVATION_VERSION")
    expected_release = os.environ.get("KILAS_CREDIT_POLICY_RELEASE_SHA")
    if version != VERSION:
        raise wallet.WalletError("activation_version_required")
    suffix = " FOR SHARE" if db.BACKEND == "postgres" else ""
    row = usage._query(
        conn,
        "SELECT cutoff,release_sha,tariff_digest,meter_version,snapshot_digest FROM kilas_credit_activation WHERE version=?"
        + suffix,
        (VERSION,),
        one=True,
    )
    payload = usage._query(
        conn,
        "SELECT payload_json,baseline_digest,schema_checksum FROM kilas_credit_activation_payload WHERE version=?",
        (VERSION,),
        one=True,
    )
    if not row or not payload:
        raise wallet.WalletError("activation_record_required")
    try:
        tariff = json.loads(os.environ.get("KILAS_CREDIT_TARIFFS_JSON", "{}"))
        body = json.loads(payload[0])
    except (ValueError, TypeError):
        raise wallet.WalletError("activation_manifest_invalid") from None
    baselines = usage._rows(
        conn,
        "SELECT user_id,feature,period_start,period_end,units,provenance FROM kilas_credit_quota_baselines WHERE version=? ORDER BY user_id,feature,period_start",
        (VERSION,),
    )
    if (
        row[1] != expected_release
        or row[2] != policy.fingerprint(tariff)
        or row[3] != METER
        or row[4] != policy.fingerprint(body)
        or payload[1] != policy.fingerprint([list(r) for r in baselines])
        or payload[2] != schema_checksum()
    ):
        raise wallet.WalletError("activation_manifest_changed")
    if admission and (not policy.enabled() or usage._as_utc(row[0]) > usage._now()):
        raise wallet.WalletError("activation_transition_hold")
    return {
        "version": VERSION,
        "cutoff": usage._as_utc(row[0]),
        "snapshot": body["snapshot"],
    }


def gate_in(conn, user):
    if not configured() or policy.owner(conn, user):
        return
    load_in(conn, admission=True)


def gate(user):
    if not configured():
        return
    conn = usage._connect()
    try:
        gate_in(conn, user)
    finally:
        conn.close()


def baseline_in(conn, user, feature, start):
    marker = load_in(conn)
    if not marker:
        return None
    period = start.isoformat() if start else "LIFETIME"
    row = usage._query(
        conn,
        "SELECT units FROM kilas_credit_quota_baselines WHERE version=? AND user_id=? AND feature=? AND period_start=?",
        (VERSION, user, feature, period),
        one=True,
    )
    return (row[0] if row else 0), marker["cutoff"]


def verify_audit_in(conn, cutoff, normalized):
    """Strict candidate verification against authoritative local DB state.

    Runs only under the explicit candidate admission hold and exclusive lock.
    Never treats an output/media estimate as processed Translator speech.
    """
    cutoff = usage._as_utc(cutoff)
    users = [
        r[0]
        for r in usage._rows(conn, "SELECT id FROM users")
        if not policy.owner(conn, r[0])
    ]
    day = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    expected = {}
    for user in users:
        for feature in policy.FREE:
            periods = (
                [None]
                if feature == "IMAGE"
                else [day, month]
                if day != month
                else [day]
            )
            for start in periods:
                units = policy.historical_raw_in(conn, user, feature, start, cutoff)
                if units:
                    expected[
                        (user, feature, start.isoformat() if start else "LIFETIME")
                    ] = units
        tests = [
            ("kilas_ai_usage", "status='PENDING'"),
            ("kilas_audio_jobs", "status IN ('QUEUED','PROCESSING')"),
            ("kilas_agent_jobs", "status NOT IN ('COMPLETED','FAILED','STOPPED')"),
            ("kilas_vo_stt_operations", "status IN ('RESERVED','DISPATCHED')"),
            ("kilas_credit_admissions", "status='RESERVED'"),
        ]
        for table, condition in tests:
            if policy.table_exists(conn, table) and usage._query(
                conn,
                "SELECT 1 FROM "
                + table
                + " WHERE user_id=? AND "
                + condition
                + " LIMIT 1",
                (user,),
                one=True,
            ):
                raise wallet.WalletError("activation_operations_not_drained")
        if policy.table_exists(conn, "kilas_audio_jobs"):
            clause = (
                " AND NOT EXISTS (SELECT 1 FROM kilas_credit_audio_links l WHERE l.user_id=j.user_id AND l.job_id=j.id)"
                if policy.table_exists(conn, "kilas_credit_audio_links")
                else ""
            )
            if usage._query(
                conn,
                "SELECT 1 FROM kilas_audio_jobs j WHERE j.user_id=? AND j.mode='translate' AND j.status='COMPLETED' AND j.created_at>=?"
                + clause
                + " LIMIT 1",
                (user, month.isoformat()),
                one=True,
            ):
                raise wallet.WalletError("activation_source_review_required")
        if policy.table_exists(conn, "kilas_vo_stt_operations") and usage._query(
            conn,
            "SELECT 1 FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key LIKE 'live-%-gi' AND created_at>=? LIMIT 1",
            (user, month.isoformat()),
            one=True,
        ):
            raise wallet.WalletError("activation_source_review_required")
        if policy.table_exists(conn, "kilas_live_translator_turns") and usage._query(
            conn,
            "SELECT 1 FROM kilas_live_translator_turns t JOIN kilas_live_translator_sessions s ON s.id=t.session_id WHERE s.user_id=? AND (t.status='PROCESSING' OR (t.status='COMPLETED' AND t.created_at>=?)) LIMIT 1",
            (user, month.isoformat()),
            one=True,
        ):
            raise wallet.WalletError("activation_source_review_required")
    supplied = {(r[0], r[1], r[2]): r[4] for r in normalized if r[4]}
    if supplied != expected:
        raise wallet.WalletError("activation_baseline_incomplete")
