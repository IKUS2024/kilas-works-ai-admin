"""Test-harness bootstrap for top-level bot tests — TEST INFRASTRUCTURE ONLY, no production code.

WHY THIS EXISTS: app.py's `_get_conversation_mode_safe()` now routes EVERY human-takeover check —
including Kilas Works' own conversations (tenant_id=None), not just tenants — through
client-hub/platform_inbox_service.py's `get_state()`, which queries Client Hub's own database for
a `platform_wa_conversation_state` table (added in migration 0016_platform_takeover). That is
correct, intentional production architecture (Platform Inbox / Human Takeover is live and verified
in production) — this file does NOT change that behavior in any way.

The gap this file closes is purely a TEST-HARNESS one: top-level test files (test_sales_engine.py
etc.) have historically never needed Client Hub's database to exist at all, since they only ever
exercised app.py's own in-memory state. Now that a production code path unconditionally reads from
Client Hub's DB even for Kilas Works' own number, a top-level test run with NO Client Hub schema
present hits "no such table: platform_wa_conversation_state", and `_get_conversation_mode_safe()`
correctly (and intentionally) fails SAFE to HUMAN_TAKEOVER — which then silences the AI for every
test that goes through the webhook. That fail-safe behavior is exactly right and is NOT touched
here; this file only makes sure the test environment has the table so tests can exercise the
REAL AI_ACTIVE path, not just the fail-safe one by accident.

WHAT THIS FILE DOES:
  1. ALWAYS generates its OWN fresh, private temporary SQLite file for this process and points
     CLIENT_HUB_DB_PATH at it via a DIRECT assignment (`os.environ["CLIENT_HUB_DB_PATH"] = ...`),
     NOT `os.environ.setdefault(...)`. This is a deliberate fix (see ISOLATION GUARANTEES below):
     `setdefault` would silently reuse whatever CLIENT_HUB_DB_PATH already happened to be in the
     process environment (e.g. inherited from a parent shell/CI runner that exports it globally),
     which does NOT guarantee a fresh path per test process — a direct assignment does. NEVER
     DATABASE_URL (that env var is left alone/unset; client-hub/db.py only touches Postgres when
     DATABASE_URL is actually set, so leaving it unset keeps this entirely on SQLite, and this
     module actively REFUSES to run at all if DATABASE_URL is set — see below).
  2. Uses `tempfile.mkstemp()` (NOT the deprecated/racy `tempfile.mktemp()`) to create the file,
     closes the returned file descriptor immediately (mkstemp hands back an OPEN fd — leaving it
     open would leak a file handle for the lifetime of the process), then lets client-hub/db.py's
     own sqlite3 connection logic open the path fresh.
  3. Adds client-hub/ to sys.path (mirroring exactly what app.py's own bridge-import block does)
     and calls client-hub's own db.init_schema() — which runs every migration in db.MIGRATIONS,
     including 0016_platform_takeover, using the SAME SQLite-auto-runs-migrations mechanism every
     other client-hub test file already relies on (see db.should_run_migrations_on_boot()).
  4. Registers an atexit cleanup that deletes the temp file when the test process exits.
  5. Exposes get_temp_db_path() so a test file that needs its OWN reference to the active DB path
     (e.g. for its own reset_*_db() helper's cleanup/re-init logic) can retrieve the EXACT SAME
     path this module is using, instead of generating a second, different one of its own — several
     top-level test files used to call tempfile.mktemp() themselves for this purpose; they now
     import this module first and call get_temp_db_path() instead (see those files for the
     before/after).

HOW TO USE: add exactly one line, `import _test_bootstrap`, to a top-level test file — AFTER its
existing `os.environ.setdefault(...)` block and BEFORE `import app as appmod`. Order matters:
client-hub/db.py reads CLIENT_HUB_DB_PATH into a module-level constant the first time it is
imported (directly here, or indirectly via app.py's own bridge-import block), so the env var must
be set before that first import happens anywhere in the process — this module does that import
itself (step 3 above), so as long as `import _test_bootstrap` runs before `import app as appmod`,
app.py's later `import db` (via its own bridge-import block) reuses the already-imported, already-
initialized module from sys.modules rather than re-reading the env var into a second, different
path. If a test file needs the DB path itself, call `_test_bootstrap.get_temp_db_path()` AFTER the
import, rather than generating its own with tempfile.

ISOLATION GUARANTEES:
  - Every test file is still run as its own separate `python3 test_x.py` process (see
    run_all_tests.py's own docstring for why — root app.py and client-hub/app.py sharing the name
    "app" makes any single-process/pytest-style collection unsafe). Each process importing this
    module gets ITS OWN fresh tempfile path, generated via tempfile.mkstemp() once per process at
    import time, and that path is ALWAYS used (direct assignment, never setdefault) — regardless
    of whatever CLIENT_HUB_DB_PATH value the process may have inherited from its environment. So
    there is no possibility of one test file's Client Hub state leaking into another's, and no
    possibility of a stale/shared path from a parent shell being silently reused, regardless of
    run order or how the process was launched.
  - Never points at production: DATABASE_URL is asserted unset by this module before doing
    anything; if a test process's environment somehow already has DATABASE_URL set (e.g. a
    developer's shell), this module deliberately does NOT touch client-hub's DB at all and prints
    a loud warning instead of risking a connection to a real database from a test run.
"""
import atexit
import os
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_CLIENT_HUB_DIR = os.path.join(_REPO_ROOT, "client-hub")

_bootstrapped = False
_temp_db_path = None


def get_temp_db_path():
    """Returns the exact CLIENT_HUB_DB_PATH this bootstrap is using for this process (or None if
    bootstrapping didn't happen — e.g. DATABASE_URL was set, or client-hub/ isn't present). Test
    files that need their own reference to the active DB (for their own reset/cleanup helper)
    should call this instead of generating a second, different tempfile of their own."""
    return _temp_db_path


def _make_fresh_temp_db_path():
    """tempfile.mkstemp() (not the deprecated/racy tempfile.mktemp()) — atomically creates the
    file and hands back an OPEN file descriptor, which we close immediately since we only want the
    PATH; client-hub/db.py's own sqlite3.connect() will open it fresh from there."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="kilas_test_client_hub_")
    os.close(fd)
    return path


def _cleanup_temp_db():
    if _temp_db_path and os.path.exists(_temp_db_path):
        try:
            os.remove(_temp_db_path)
        except OSError:
            pass


def _bootstrap():
    global _bootstrapped, _temp_db_path
    if _bootstrapped:
        return
    _bootstrapped = True

    if (os.environ.get("DATABASE_URL") or "").strip():
        print(
            "test_bootstrap: DATABASE_URL is set in this environment — REFUSING to touch Client "
            "Hub's database from a test run (tests must never point at a real/production "
            "database). Human-takeover checks for Kilas Works' own number will correctly fail "
            "safe to HUMAN_TAKEOVER in this run, same as any other genuine DB-read failure."
        )
        return

    if not os.path.isdir(_CLIENT_HUB_DIR):
        # No client-hub/ folder at all (e.g. this file copied somewhere standalone) — nothing to
        # bootstrap; app.py's own _CLIENT_HUB_AVAILABLE will be False and it degrades safely on
        # its own (see app.py's own bridge-import block).
        return

    _temp_db_path = _make_fresh_temp_db_path()
    # Direct assignment, NOT setdefault: this process ALWAYS gets its own fresh, private path —
    # never silently reuses a CLIENT_HUB_DB_PATH inherited from a parent shell/CI runner. See the
    # ISOLATION GUARANTEES section of this module's docstring.
    os.environ["CLIENT_HUB_DB_PATH"] = _temp_db_path
    os.environ.setdefault("SECRET_KEY", "test-bootstrap-secret-key")

    if _CLIENT_HUB_DIR not in sys.path:
        # append(), NEVER insert(0, ...): the calling test script's own directory (containing the
        # REAL root app.py) is already sys.path[0] by normal Python behavior. Both root app.py and
        # client-hub/app.py are literally named "app.py" — inserting client-hub/ ahead of that
        # position would make a later `import app as appmod` in the test file resolve to Client
        # Hub's Flask app instead of the bot's app.py (reproduced and confirmed while building this
        # fix). Appending keeps client-hub/'s own internal modules (db, platform_inbox_service,
        # etc., none of which collide with anything at the repo root) importable, without ever
        # letting client-hub/app.py shadow the real app.py.
        sys.path.append(_CLIENT_HUB_DIR)

    try:
        import db as _client_hub_db
        _client_hub_db.init_schema()
    except Exception as e:
        print(
            f"test_bootstrap: gagal init Client Hub test schema ({e}) — human-takeover checks "
            "untuk nomor Kilas Works sendiri akan fail-safe ke HUMAN_TAKEOVER (BENAR & AMAN, "
            "cuma berarti test ini gak nge-cover jalur AI_ACTIVE-nya)."
        )
        return

    atexit.register(_cleanup_temp_db)


_bootstrap()
