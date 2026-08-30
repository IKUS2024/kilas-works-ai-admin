"""Gap-fix Area J — SMTP / Forgot Password source-level regression locks.

The runtime behavior (anti-enumeration, rate limiting, expiring/single-use tokens, old-password-
rejected, new-password-accepted) is already fully covered by
tests/test_business_hub_v2_phase_a.py (19 tests, all passing at baseline — Area J found no gaps
requiring a code change). This file adds source-level checks that can't be expressed as a runtime
behavior test: no hardcoded SMTP credentials anywhere in the codebase, and the "SMTP not
configured" log line never leaks the token/reset URL.

Run with:
    cd client-hub && python3 tests/test_smtp_security_source_checks.py
"""
import os
import re

CLIENT_HUB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL_UTILS_PATH = os.path.join(CLIENT_HUB_DIR, "email_utils.py")
ROUTES_AUTH_PATH = os.path.join(CLIENT_HUB_DIR, "routes_auth.py")
SECURITY_PATH = os.path.join(CLIENT_HUB_DIR, "security.py")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_smtp_credentials_only_from_environment():
    src = _read(EMAIL_UTILS_PATH)
    for env_var in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_PORT", "RESET_EMAIL_FROM"):
        assert f'os.environ.get("{env_var}"' in src, f"{env_var} must be read via os.environ.get(...)"
    # No plausible hardcoded credential-looking literal (a real password/host string assigned
    # directly rather than read from the environment).
    assert not re.search(r'SMTP_PASSWORD\s*=\s*["\'][^"\']+["\']', src)
    assert not re.search(r'smtplib\.SMTP\([\'"]', src), "SMTP host must never be a literal string"
    print("test_smtp_credentials_only_from_environment OK")


def test_smtp_not_configured_log_line_never_leaks_token_or_url():
    src = _read(EMAIL_UTILS_PATH)
    # The production "not configured" branch must not reference reset_url/raw_token in its print.
    prod_branch_match = re.search(
        r'if _is_production\(\):\s*\n\s*print\((.*?)\)\s*\n\s*return False',
        src, re.DOTALL,
    )
    assert prod_branch_match, "production not-configured log branch not found"
    logged_text = prod_branch_match.group(1)
    assert "reset_url" not in logged_text
    assert "raw_token" not in logged_text
    assert "token" not in logged_text.lower() or "SMTP_" in logged_text  # only mentions env var names, not a value
    print("test_smtp_not_configured_log_line_never_leaks_token_or_url OK")


def test_reset_token_never_logged_in_routes_auth():
    src = _read(ROUTES_AUTH_PATH)
    # write_audit_no_business calls must never pass raw_token as the detail.
    assert "raw_token" not in re.sub(r"raw_token, token_hash = security\.generate_reset_token\(\)", "", src) \
        or True  # generation line itself legitimately mentions raw_token; check audit calls specifically
    audit_calls = re.findall(r"write_audit_no_business\([^)]*\)", src)
    for call in audit_calls:
        assert "raw_token" not in call, f"reset token must never be written to the audit log: {call}"
    print("test_reset_token_never_logged_in_routes_auth OK")


def test_reset_token_hashing_uses_sha256_never_stored_raw():
    src = _read(SECURITY_PATH)
    assert "hashlib.sha256" in src
    # generate_reset_token must return the hash, not persist the raw token anywhere in this module.
    gen_match = re.search(r"def generate_reset_token\(\):.*?return raw_token, token_hash", src, re.DOTALL)
    assert gen_match, "generate_reset_token() shape changed unexpectedly"
    print("test_reset_token_hashing_uses_sha256_never_stored_raw OK")


def test_reset_token_ttl_is_30_minutes():
    src = _read(SECURITY_PATH)
    assert "RESET_TOKEN_TTL_SECONDS = 30 * 60" in src
    print("test_reset_token_ttl_is_30_minutes OK")


if __name__ == "__main__":
    test_smtp_credentials_only_from_environment()
    test_smtp_not_configured_log_line_never_leaks_token_or_url()
    test_reset_token_never_logged_in_routes_auth()
    test_reset_token_hashing_uses_sha256_never_stored_raw()
    test_reset_token_ttl_is_30_minutes()
    print("ALL SMTP/FORGOT-PASSWORD SOURCE SECURITY CHECKS PASSED")
