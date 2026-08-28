"""Kilas Works Client Hub — repo.get_ai_settings() / repo.get_tenant_config_row() PostgreSQL
JSON/JSONB compatibility fix.

Production bug: `TypeError: the JSON object must be str, bytes or bytearray, not dict`.
get_ai_settings() called json.loads() unconditionally on normalized_config_json/missing_fields_json.
On SQLite these columns are plain TEXT, so the driver always returns a str and json.loads() was
correct. On PostgreSQL, ai_settings.normalized_config_json/missing_fields_json are JSON/JSONB
columns (see migrations/0002_production_foundation_postgres.sql) and psycopg2 already deserializes
JSON/JSONB into a native Python dict/list before this function ever sees it — so json.loads() on an
already-a-dict value raised the TypeError above in production.

Fix: use the value directly when it is already the expected native Python type (dict for
normalized_config_json, list for missing_fields_json); otherwise parse it with json.loads() (still
covers str/bytes/bytearray, i.e. the real SQLite path). A genuinely malformed JSON string is still
passed to json.loads() and still raises the same json.JSONDecodeError as before this fix — malformed
data is not silently accepted differently than it was.

The identical bug (and identical fix, via the same shared repo._coerce_json_column() helper) also
applied to repo.get_tenant_config_row()'s `row["config"] = json.loads(row["config_json"])` —
tenant_configs.config_json is the same JSON/JSONB-on-Postgres-vs-TEXT-on-SQLite shape, used by the
future bot-integration config path (tenant_config_service.get_tenant_config()). Covered below too.

A third instance of the same class of bug lived in repo.save_tenant_config()'s idempotency check:
`existing["config_json"] == config_json` compared a native dict (what psycopg2 hands back for a
JSONB column on Postgres) against a freshly json.dumps()'d string — never equal, so every
re-provision of an unchanged tenant looked "changed" and incorrectly bumped config_version every
time. Fixed by normalizing `existing["config_json"]` through the same _coerce_json_column() helper
and comparing the resulting native dict against config_dict (also a native dict) instead of
comparing strings. Covered in the section below this one.

This suite cannot open a real PostgreSQL connection from this sandbox (no live Postgres instance,
no psycopg2 installed — see db.py's own HONESTY NOTE), so the "already a dict/list" scenarios are
exercised by monkeypatching db.query_one() to return a row shaped exactly the way psycopg2 would
hand it back for a JSON/JSONB column (a real dict/list, not a string) — this exercises the exact
code path repo.get_ai_settings() runs, independent of which driver produced the row. The
SQLite-string scenarios are exercised end-to-end against the real SQLite backend this repo's tests
always use, so both shapes are covered by an actual call to get_ai_settings().

Follows the exact same plain-script convention as every other test file in this repo: assert
statements, functions named test_*, a final "ALL ... TESTS PASSED" line. Run with:
    cd client-hub && python3 tests/test_repo_ai_settings_postgres_json_compat.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DB = tempfile.mktemp(suffix=".db")
os.environ["CLIENT_HUB_DB_PATH"] = _TMP_DB
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("DATABASE_URL", None)

import db  # noqa: E402
import repo  # noqa: E402
import security  # noqa: E402


def reset_db():
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)
    db._local.conn = None
    db.init_schema()


def _make_business():
    user_id = repo.create_user(f"jsoncompat_{os.urandom(4).hex()}@test.com", security.hash_password("password123"))
    return repo.create_business(user_id, "JSON Compat Co")


def _stub_query_one_returning(fake_row):
    """Monkeypatches db.query_one so the very next call (and only that call — restores itself
    immediately after) returns fake_row, simulating exactly what psycopg2 hands back for a row
    whose JSON/JSONB columns are already native dict/list objects, without needing a real
    PostgreSQL connection."""
    original = db.query_one

    def _fake(query, params=()):
        db.query_one = original
        return fake_row

    db.query_one = _fake
    return original


# ---------------------------------------------------------------------------
# PostgreSQL-style: driver already returns native dict/list
# ---------------------------------------------------------------------------

def test_postgres_style_dict_and_list_used_directly_no_type_error():
    fake_row = {
        "business_id": 1,
        "ai_status": "DONE",
        "normalized_summary": "Kedai kopi ramah",
        "normalized_config_json": {"business_name": "Kopi ABC", "features_enabled": {"faq": True}},
        "missing_fields_json": ["business_hours"],
        "last_error": None,
    }
    original = _stub_query_one_returning(fake_row)
    try:
        result = repo.get_ai_settings(1)
    finally:
        db.query_one = original  # already restored by the fake, but keep this deterministic
    assert result is not None
    assert result["normalized_config"] == {"business_name": "Kopi ABC", "features_enabled": {"faq": True}}
    assert result["missing_fields"] == ["business_hours"]
    print("test_postgres_style_dict_and_list_used_directly_no_type_error OK")


def test_postgres_style_empty_dict_and_list_are_falsy_and_skipped_like_before():
    """Preserve existing behavior: an empty dict/list/None for these columns is falsy, so the
    original `if row and row.get(...)` guard skips assigning normalized_config/missing_fields at
    all — unchanged by this fix, verified explicitly so the fix doesn't accidentally start parsing
    "nothing there yet" as real data."""
    fake_row = {
        "business_id": 2, "ai_status": "PENDING",
        "normalized_config_json": None, "missing_fields_json": None,
    }
    original = _stub_query_one_returning(fake_row)
    try:
        result = repo.get_ai_settings(2)
    finally:
        db.query_one = original
    assert result is not None
    assert "normalized_config" not in result
    assert "missing_fields" not in result
    print("test_postgres_style_empty_dict_and_list_are_falsy_and_skipped_like_before OK")


# ---------------------------------------------------------------------------
# SQLite-style: real end-to-end path, columns come back as TEXT strings
# ---------------------------------------------------------------------------

def test_sqlite_style_json_strings_still_parsed_correctly():
    reset_db()
    bid = _make_business()
    config_dict = {"business_name": "Kopi ABC", "features_enabled": {"faq": True, "appointment": False}}
    missing = ["business_hours", "services"]
    repo.save_ai_normalized_config(bid, "Kedai kopi ramah", config_dict, missing)

    result = repo.get_ai_settings(bid)
    assert result is not None
    assert isinstance(result["normalized_config_json"], str), "SQLite column must still be a raw TEXT string"
    assert isinstance(result["missing_fields_json"], str)
    assert result["normalized_config"] == config_dict
    assert result["missing_fields"] == missing
    print("test_sqlite_style_json_strings_still_parsed_correctly OK")


def test_sqlite_style_no_ai_settings_yet_returns_row_without_parsed_fields():
    reset_db()
    bid = _make_business()
    result = repo.get_ai_settings(bid)
    # A freshly created business has an ai_settings row (status PENDING) but no normalized config
    # yet — normalized_config_json/missing_fields_json are NULL, so the parsed keys must be absent,
    # not present-but-None and not raise.
    assert result is not None
    assert "normalized_config" not in result
    assert "missing_fields" not in result
    print("test_sqlite_style_no_ai_settings_yet_returns_row_without_parsed_fields OK")


def test_nonexistent_business_returns_none_not_a_crash():
    reset_db()
    result = repo.get_ai_settings(999999)
    assert result is None
    print("test_nonexistent_business_returns_none_not_a_crash OK")


# ---------------------------------------------------------------------------
# Malformed JSON semantics must be unchanged (still a real, visible failure — not silently ignored)
# ---------------------------------------------------------------------------

def test_malformed_json_string_still_raises_same_error_as_before():
    fake_row = {
        "business_id": 3, "ai_status": "DONE",
        "normalized_config_json": "{not valid json",  # a genuinely corrupt string value
        "missing_fields_json": None,
    }
    original = _stub_query_one_returning(fake_row)
    raised = False
    try:
        repo.get_ai_settings(3)
    except json.JSONDecodeError:
        raised = True
    finally:
        db.query_one = original
    assert raised, "a malformed JSON string must still raise json.JSONDecodeError, not be silently accepted"
    print("test_malformed_json_string_still_raises_same_error_as_before OK")


def test_bytes_value_still_parsed_correctly():
    """Some drivers/wrappers can hand back JSON text as bytes rather than str — json.loads()
    already supports bytes/bytearray natively, this just confirms the fix's isinstance check
    doesn't accidentally reject that valid path."""
    fake_row = {
        "business_id": 4, "ai_status": "DONE",
        "normalized_config_json": b'{"business_name": "Kopi ABC"}',
        "missing_fields_json": b'["business_hours"]',
    }
    original = _stub_query_one_returning(fake_row)
    try:
        result = repo.get_ai_settings(4)
    finally:
        db.query_one = original
    assert result["normalized_config"] == {"business_name": "Kopi ABC"}
    assert result["missing_fields"] == ["business_hours"]
    print("test_bytes_value_still_parsed_correctly OK")


# ---------------------------------------------------------------------------
# get_tenant_config_row() — same fix, same shared helper (repo._coerce_json_column)
# ---------------------------------------------------------------------------

def test_tenant_config_row_postgres_style_dict_used_directly_no_type_error():
    fake_row = {
        "business_id": 10, "config_version": 3,
        "config_json": {"business_name": "Kopi ABC", "features_enabled": {"faq": True}},
    }
    original = _stub_query_one_returning(fake_row)
    try:
        result = repo.get_tenant_config_row(10)
    finally:
        db.query_one = original
    assert result["config"] == {"business_name": "Kopi ABC", "features_enabled": {"faq": True}}
    print("test_tenant_config_row_postgres_style_dict_used_directly_no_type_error OK")


def test_tenant_config_row_sqlite_style_json_string_still_parsed_correctly():
    reset_db()
    bid = _make_business()
    config_dict = {"business_name": "Kopi ABC", "tenant_id": bid}
    version, changed = repo.save_tenant_config(bid, config_dict)
    assert changed is True and version == 1

    row = repo.get_tenant_config_row(bid)
    assert row is not None
    assert isinstance(row["config_json"], str), "SQLite column must still be a raw TEXT string"
    assert row["config"] == config_dict
    print("test_tenant_config_row_sqlite_style_json_string_still_parsed_correctly OK")


def test_tenant_config_row_no_config_yet_returns_row_without_parsed_field():
    reset_db()
    bid = _make_business()
    row = repo.get_tenant_config_row(bid)
    # No tenant_configs row exists yet for a freshly created business (nothing provisioned).
    assert row is None
    print("test_tenant_config_row_no_config_yet_returns_row_without_parsed_field OK")


def test_tenant_config_row_malformed_json_string_still_raises_same_error_as_before():
    fake_row = {"business_id": 11, "config_version": 1, "config_json": "{not valid json"}
    original = _stub_query_one_returning(fake_row)
    raised = False
    try:
        repo.get_tenant_config_row(11)
    except json.JSONDecodeError:
        raised = True
    finally:
        db.query_one = original
    assert raised, "a malformed JSON string must still raise json.JSONDecodeError, not be silently accepted"
    print("test_tenant_config_row_malformed_json_string_still_raises_same_error_as_before OK")


def test_tenant_config_row_bytes_value_still_parsed_correctly():
    fake_row = {"business_id": 12, "config_version": 1, "config_json": b'{"business_name": "Kopi ABC"}'}
    original = _stub_query_one_returning(fake_row)
    try:
        result = repo.get_tenant_config_row(12)
    finally:
        db.query_one = original
    assert result["config"] == {"business_name": "Kopi ABC"}
    print("test_tenant_config_row_bytes_value_still_parsed_correctly OK")


# ---------------------------------------------------------------------------
# save_tenant_config() idempotency comparison — same fix, same shared helper
# ---------------------------------------------------------------------------

def test_save_tenant_config_postgres_style_unchanged_dict_does_not_bump_version():
    """The exact bug: on Postgres, existing["config_json"] comes back as a native dict, not a
    string. Before this fix, comparing it against the freshly json.dumps()'d string was always
    False, so an UNCHANGED config incorrectly looked changed and bumped config_version on every
    re-provision. save_tenant_config() only ever needs one db.query_one() call to decide this (the
    SELECT for `existing`), so the same single-shot stub used for the read-path tests above works
    here too."""
    config_dict = {"business_name": "Kopi ABC", "features_enabled": {"faq": True}}
    fake_existing = {"config_json": dict(config_dict), "config_version": 5}
    original = _stub_query_one_returning(fake_existing)
    try:
        version, changed = repo.save_tenant_config(20, config_dict)
    finally:
        db.query_one = original
    assert changed is False, "an unchanged config must not look changed just because Postgres returns a native dict"
    assert version == 5, "version must not bump when nothing actually changed"
    print("test_save_tenant_config_postgres_style_unchanged_dict_does_not_bump_version OK")


def test_save_tenant_config_sqlite_style_unchanged_json_string_does_not_bump_version():
    reset_db()
    bid = _make_business()
    config_dict = {"business_name": "Kopi ABC", "features_enabled": {"faq": True}}

    v1, changed1 = repo.save_tenant_config(bid, config_dict)
    assert v1 == 1 and changed1 is True

    row = repo.get_tenant_config_row(bid)
    assert isinstance(row["config_json"], str), "SQLite column must still be a raw TEXT string"

    v2, changed2 = repo.save_tenant_config(bid, dict(config_dict))  # same content, different dict object
    assert changed2 is False
    assert v2 == 1, "version must stay at 1 when re-saving an identical config"
    print("test_save_tenant_config_sqlite_style_unchanged_json_string_does_not_bump_version OK")


def test_save_tenant_config_actually_changed_config_increments_version_exactly_once():
    reset_db()
    bid = _make_business()
    v1, changed1 = repo.save_tenant_config(bid, {"business_name": "Kopi ABC"})
    assert v1 == 1 and changed1 is True

    v2, changed2 = repo.save_tenant_config(bid, {"business_name": "Kopi ABC", "category": "F&B"})
    assert changed2 is True
    assert v2 == 2, "a genuinely changed config must bump the version exactly once"

    # Re-saving that SAME new value again must NOT bump it a second time.
    v3, changed3 = repo.save_tenant_config(bid, {"business_name": "Kopi ABC", "category": "F&B"})
    assert changed3 is False
    assert v3 == 2, "re-saving an already-current config must not bump the version again"
    print("test_save_tenant_config_actually_changed_config_increments_version_exactly_once OK")


def test_save_tenant_config_malformed_existing_json_still_raises_same_error_as_before():
    fake_existing = {"config_json": "{not valid json", "config_version": 1}
    original = _stub_query_one_returning(fake_existing)
    raised = False
    try:
        repo.save_tenant_config(21, {"business_name": "Kopi ABC"})
    except json.JSONDecodeError:
        raised = True
    finally:
        db.query_one = original
    assert raised, "a malformed stored config must still raise json.JSONDecodeError, not be silently overwritten"
    print("test_save_tenant_config_malformed_existing_json_still_raises_same_error_as_before OK")


if __name__ == "__main__":
    test_postgres_style_dict_and_list_used_directly_no_type_error()
    test_postgres_style_empty_dict_and_list_are_falsy_and_skipped_like_before()
    test_sqlite_style_json_strings_still_parsed_correctly()
    test_sqlite_style_no_ai_settings_yet_returns_row_without_parsed_fields()
    test_nonexistent_business_returns_none_not_a_crash()
    test_malformed_json_string_still_raises_same_error_as_before()
    test_bytes_value_still_parsed_correctly()
    test_tenant_config_row_postgres_style_dict_used_directly_no_type_error()
    test_tenant_config_row_sqlite_style_json_string_still_parsed_correctly()
    test_tenant_config_row_no_config_yet_returns_row_without_parsed_field()
    test_tenant_config_row_malformed_json_string_still_raises_same_error_as_before()
    test_tenant_config_row_bytes_value_still_parsed_correctly()
    test_save_tenant_config_postgres_style_unchanged_dict_does_not_bump_version()
    test_save_tenant_config_sqlite_style_unchanged_json_string_does_not_bump_version()
    test_save_tenant_config_actually_changed_config_increments_version_exactly_once()
    test_save_tenant_config_malformed_existing_json_still_raises_same_error_as_before()
    print("\nALL repo JSON COMPAT TESTS PASSED (get_ai_settings + get_tenant_config_row + save_tenant_config)")
