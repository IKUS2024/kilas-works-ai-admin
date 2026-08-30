#!/usr/bin/env python3
"""Aggregate test runner — Gap-fix Area L.

Runs EVERY test_*.py file (top-level bot tests AND client-hub/tests/) as its OWN separate `python3`
subprocess, never via in-process import or pytest auto-discovery. This is a DELIBERATE design
choice, not an oversight:

  - app.py exists as TWO DIFFERENT modules sharing the same name — the WhatsApp bot at the repo
    root, and the Client Hub Flask app at client-hub/app.py. Every existing test file already does
    `import app as appmod` (top-level) or `import app as client_hub_app` (client-hub), after
    inserting the right directory onto sys.path. Collecting both kinds of file into ONE Python
    process (e.g. pytest's default auto-discovery) would either raise a duplicate-module error or
    silently hand the wrong cached module to whichever file imports second — a real, structural
    collision, not a hypothetical one. Running each file as its own subprocess sidesteps this
    completely: every subprocess gets a fresh `sys.modules`, so the two `app.py` files never
    coexist in the same interpreter.
  - Every test file already manages its own isolated state (a fresh tempfile SQLite DB path set
    via CLIENT_HUB_DB_PATH before any import; in-memory dict resets via its own reset_state()/
    reset_db() helper, called at the top of every individual test function). Subprocess isolation
    means it is categorically IMPOSSIBLE for one file's module-level globals to leak into the next
    file's run, regardless of execution order — this is a stronger guarantee than pytest's default
    single-process model would give for free, with zero changes to any test file needed.
  - Only files matching the exact `test_*.py` glob are ever picked up — a non-test utility script
    (e.g. `generate_katalog_pdf.py`, `scripts/bootstrap_admin.py`, `scripts/run_migrations.py`) is
    structurally excluded, never accidentally executed as a "test".

Usage:
    python3 run_all_tests.py                  # run everything once, forward order
    python3 run_all_tests.py --reverse         # same, but reverse file order (order-safety check)
    python3 run_all_tests.py --repeat 3        # run the whole suite N times in a row
    python3 run_all_tests.py --only tenant     # only run files whose path contains this substring
    python3 run_all_tests.py --top-level-only  # skip client-hub/tests entirely
    python3 run_all_tests.py --client-hub-only # skip top-level tests entirely

Exit code is 0 only if every single file passed, in every requested repeat/order — suitable for use
as a CI gate. This script makes NO production code changes and does not alter any test's own
pass/fail semantics; it only orchestrates running the existing files and aggregates their results.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
CLIENT_HUB_DIR = os.path.join(REPO_ROOT, "client-hub")
CLIENT_HUB_TESTS_DIR = os.path.join(CLIENT_HUB_DIR, "tests")


def discover_test_files(include_top_level=True, include_client_hub=True):
    """Returns [(display_name, absolute_path, cwd)]. `cwd` is set to the directory each file's own
    docstring documents running it from (repo root for top-level tests, client-hub/ for
    client-hub/tests/*), matching exactly how a human would run them by hand — every file resolves
    its own paths via __file__, so this is about behavioral parity with the documented convention,
    not a strict import requirement."""
    files = []
    if include_top_level:
        for path in sorted(glob.glob(os.path.join(REPO_ROOT, "test_*.py"))):
            files.append((f"top-level/{os.path.basename(path)}", path, REPO_ROOT))
    if include_client_hub:
        for path in sorted(glob.glob(os.path.join(CLIENT_HUB_TESTS_DIR, "test_*.py"))):
            files.append((f"client-hub/tests/{os.path.basename(path)}", path, CLIENT_HUB_DIR))
    return files


def run_one(path, cwd, timeout=120):
    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, path], cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.time() - start
        return result.returncode == 0, elapsed, result.stdout, result.stderr
    except subprocess.TimeoutExpired as e:
        elapsed = time.time() - start
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return False, elapsed, stdout, f"TIMEOUT after {timeout}s"


def run_suite(files, label):
    print(f"\n=== {label} ({len(files)} files) ===")
    failures = []
    for display_name, path, cwd in files:
        ok, elapsed, stdout, stderr = run_one(path, cwd)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {display_name} ({elapsed:.1f}s)")
        if not ok:
            failures.append(display_name)
            print("    --- stdout tail ---")
            for line in stdout.strip().splitlines()[-20:]:
                print(f"    {line}")
            print("    --- stderr tail ---")
            for line in stderr.strip().splitlines()[-20:]:
                print(f"    {line}")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reverse", action="store_true", help="run files in reverse order")
    parser.add_argument("--repeat", type=int, default=1, help="run the whole suite N times")
    parser.add_argument("--only", default=None, help="only run files whose display name contains this substring")
    parser.add_argument("--top-level-only", action="store_true")
    parser.add_argument("--client-hub-only", action="store_true")
    args = parser.parse_args()

    files = discover_test_files(
        include_top_level=not args.client_hub_only,
        include_client_hub=not args.top_level_only,
    )
    if args.only:
        files = [f for f in files if args.only in f[0]]
    if args.reverse:
        files = list(reversed(files))

    if not files:
        print("No test files matched — nothing to run.")
        sys.exit(1)

    all_failures = []
    for run_idx in range(1, args.repeat + 1):
        label = f"RUN {run_idx}/{args.repeat}" + (" (reverse order)" if args.reverse else "")
        failures = run_suite(files, label)
        all_failures.extend((run_idx, f) for f in failures)

    total_runs = len(files) * args.repeat
    total_failed = len(all_failures)
    print(f"\n=== SUMMARY: {total_runs - total_failed}/{total_runs} test-file runs passed ===")
    if all_failures:
        print("FAILURES:")
        for run_idx, name in all_failures:
            print(f"  run {run_idx}: {name}")
        sys.exit(1)
    print("ALL TEST FILES PASSED.")
    sys.exit(0)


if __name__ == "__main__":
    main()
