"""Explicit inactive activation candidate; never imported by startup or routes.

This records reviewed evidence, not inferred credits or historical charges. An
operator must separately approve and execute the production transition. Existing
supplier unknowns are preserved; a fresh audit must classify customer gaps.
"""

from datetime import datetime, timezone, timedelta
import re
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
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
