"""Account-bound Interpreter turns; supplier leases remain entirely separate."""

import json
import os
import sqlite3
import db
from . import credit_policy as policy, credit_wallet as wallet, credit_audio, usage

MODEL = "gemini-3.8-live"


def operation(ident, index):
    if type(index) is not int or not 0 <= index <= 100000:
        raise wallet.WalletError("invalid_interpreter_turn")
    return wallet._key(f"interpreter:{ident}:turn:{index}")


def limits():
    try:
        value = json.loads(os.environ.get("KILAS_CREDIT_TARIFFS_JSON", "{}"))
        item = value["limits"]["INTERPRETER"]
        maximum = wallet._amount(item["source_ms"])
        ratio = wallet._amount(item["output_ratio_milli"])
        if (
            value["version"] != "customer-credit-v1"
            or item["models"] != [MODEL]
            or maximum > 600000
            or ratio > 10000
        ):
            raise ValueError()
        return maximum, ratio
    except (ValueError, KeyError, TypeError):
        raise wallet.WalletError("interpreter_terms_unapproved") from None


def _paid(conn, user):
    if not policy.table_exists(conn, "kilas_ai_subscriptions"):
        return False
    return usage._plan(conn, user, usage._now())[0] != "FREE"


def session_in(conn, user, ident):
    if not policy.table_exists(conn, "kilas_credit_interpreter_sessions"):
        return None
    return usage._query(
        conn,
        "SELECT model,settings_digest,billing_mode,status FROM kilas_credit_interpreter_sessions WHERE user_id=? AND session_id=?",
        (user, ident),
        one=True,
    )


def admit_in(conn, user, ident, index, settings):
    policy.lock_account_in(conn, user)
    item = session_in(conn, user, ident)
    if not policy.enabled():
        raise wallet.WalletError("credit_policy_disabled")
    settings_digest = policy.fingerprint(settings)
    if item and (tuple(item[:2]) != (MODEL, settings_digest) or item[3] != "ACTIVE"):
        raise wallet.WalletError("interpreter_session_changed")
    owner = policy.owner(conn, user)
    if item and (item[2] == "OWNER") != owner:
        raise wallet.WalletError("interpreter_identity_changed")
    if item and item[2] == "LEGACY":
        return {"mode": "LEGACY"}
    if not item and not owner and _paid(conn, user):
        usage._query(
            conn,
            "INSERT INTO kilas_credit_interpreter_sessions(user_id,session_id,model,settings_digest,billing_mode,created_at) VALUES (?,?,?,?,'LEGACY',?)",
            (user, ident, MODEL, settings_digest, usage._now().isoformat()),
        )
        return {"mode": "LEGACY"}
    if owner:
        if not item:
            usage._query(
                conn,
                "INSERT INTO kilas_credit_interpreter_sessions(user_id,session_id,model,settings_digest,billing_mode,created_at) VALUES (?,?,?,?,'OWNER',?)",
                (user, ident, MODEL, settings_digest, usage._now().isoformat()),
            )
        return {"mode": "OWNER"}
    maximum, ratio = limits()
    key = operation(ident, index)
    digest = policy.fingerprint(
        {
            "contract": "interpreter-source-v1",
            "session": ident,
            "turn": index,
            "settings": settings,
            "model": MODEL,
            "maximum_source_ms": maximum,
            "output_ratio_milli": ratio,
        }
    )
    result = policy.admit_in(
        conn, user, key, "TRANSLATOR", maximum, digest, pricing_feature="INTERPRETER"
    )
    if not result["dispatch"]:
        raise wallet.WalletError("interpreter_turn_closed")
    if not item:
        usage._query(
            conn,
            "INSERT INTO kilas_credit_interpreter_sessions(user_id,session_id,model,settings_digest,billing_mode,created_at) VALUES (?,?,?,?,'CUSTOMER',?)",
            (user, ident, MODEL, settings_digest, usage._now().isoformat()),
        )
    usage._query(
        conn,
        "INSERT INTO kilas_credit_interpreter_turns(user_id,session_id,turn_index,operation_key,maximum_ms,output_ratio_milli) VALUES (?,?,?,?,?,?)",
        (user, ident, index, key, maximum, ratio),
    )
    return {"mode": "CUSTOMER", "maximum_ms": maximum, "ratio": ratio}


def begin(user, ident, index, settings):
    try:
        with wallet._locked(user) as conn:
            foreign = usage._query(
                conn,
                "SELECT user_id FROM kilas_credit_interpreter_sessions WHERE session_id=?",
                (ident,),
                one=True,
            )
            if foreign and foreign[0] != user:
                raise wallet.WalletError("interpreter_identity_conflict")
            return admit_in(conn, user, ident, index, settings)
    except Exception as error:
        pg = getattr(getattr(db, "psycopg2", None), "IntegrityError", ())
        if isinstance(error, sqlite3.IntegrityError) or (pg and isinstance(error, pg)):
            raise wallet.WalletError("interpreter_identity_conflict") from None
        raise


def start(user, ident, settings):
    from . import credit_activation
    credit_activation.gate(user)
    if not policy.enabled():
        return None
    return begin(user, ident, 0, settings)


def dispatched(user, ident, index):
    with wallet._locked(user) as conn:
        usage._query(
            conn,
            "UPDATE kilas_credit_interpreter_turns SET dispatched=1 WHERE user_id=? AND session_id=? AND turn_index=? AND status='ACTIVE'",
            (user, ident, index),
        )


def settle(
    user,
    ident,
    index,
    source_ms,
    output_ms,
    digest,
    *,
    confirmed=False,
    known_failure=False,
):
    with wallet._locked(user) as conn:
        row = usage._query(
            conn,
            "SELECT operation_key,maximum_ms,output_ratio_milli,dispatched,status FROM kilas_credit_interpreter_turns WHERE user_id=? AND session_id=? AND turn_index=?",
            (user, ident, index),
            one=True,
        )
        if not row:
            return
        if source_ms > row[1] or output_ms > source_ms * row[2] // 1000:
            raise wallet.WalletError("interpreter_meter_outside_bounds")
        if row[4] != "ACTIVE":
            return
        # A zero-source turn cannot use Free minutes or purchased credits, even
        # when an idle supplier lease retains its conservative cost estimate.
        success = confirmed or (source_ms == 0 and not known_failure)
        definitive = known_failure or not row[3]
        usage._query(
            conn,
            "UPDATE kilas_credit_interpreter_turns SET source_ms=?,output_ms=?,source_digest=?,confirmed=?,status=? WHERE user_id=? AND session_id=? AND turn_index=?",
            (
                source_ms,
                output_ms,
                digest,
                int(confirmed),
                "COMPLETE" if success else "FAILED" if definitive else "UNKNOWN",
                user,
                ident,
                index,
            ),
        )
        policy.finish_in(
            conn,
            user,
            row[0],
            source_ms if success else 0,
            success=success,
            definitive_failure=definitive,
        )


def close(user, ident):
    conn = usage._connect()
    try:
        if policy.table_exists(conn, "kilas_credit_interpreter_sessions"):
            usage._query(
                conn,
                "UPDATE kilas_credit_interpreter_sessions SET status='CLOSED' WHERE user_id=? AND session_id=?",
                (user, ident),
            )
            conn.commit()
    finally:
        conn.close()


def abandon(user, ident):
    # End also works after process loss. Missing RAM metering is UNKNOWN, never
    # zero-use evidence or an automatic refund. Supplier End must run first.
    conn = usage._connect()
    try:
        if policy.table_exists(conn, "kilas_credit_interpreter_sessions"):
            policy.lock_account_in(conn, user)
            usage._query(
                conn,
                "UPDATE kilas_credit_interpreter_turns SET status='UNKNOWN' WHERE user_id=? AND session_id=? AND status='ACTIVE'",
                (user, ident),
            )
            usage._query(
                conn,
                "UPDATE kilas_credit_interpreter_sessions SET status='CLOSED' WHERE user_id=? AND session_id=?",
                (user, ident),
            )
            conn.commit()
    finally:
        conn.close()


class Meter:
    def __init__(self, admission):
        self.sealed = False
        self.maximum = admission["maximum_ms"]
        self.ratio = admission["ratio"]
        self.source = credit_audio.SourceMeter()
        self.output = credit_audio.SourceMeter(24000)

    def input(self, raw):
        if self.sealed:
            raise wallet.WalletError("interpreter_turn_closed")
        candidate = self.source.clone()
        if candidate.feed(raw) > self.maximum:
            raise wallet.WalletError("interpreter_source_limit")
        self.source = candidate

    def audio(self, raw):
        if self.sealed:
            raise wallet.WalletError("interpreter_turn_closed")
        candidate = self.output.clone()
        if candidate.feed(raw) > self.source.milliseconds * self.ratio // 1000:
            raise wallet.WalletError("interpreter_output_limit")
        self.output = candidate

    def finish(self, user, ident, index, confirmed=False, known_failure=False):
        result = settle(
            user,
            ident,
            index,
            self.source.milliseconds,
            self.output.milliseconds,
            self.source.digest.hexdigest(),
            confirmed=confirmed,
            known_failure=known_failure,
        )
        self.sealed = True
        return result
