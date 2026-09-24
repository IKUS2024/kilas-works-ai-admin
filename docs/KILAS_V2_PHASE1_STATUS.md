# Kilas V2 Phase 1 status

Status: IN PROGRESS — route wiring and integration tests checkpoint.

Branch: `feature/kilas-core-v2`.
Starting feature SHA: `387aa9d9a182111d12a6096969071e49d76a7e7d`.
Current commit before this checkpoint (adapter): `a8f8279f352c1debfbd32c018fa3fb37f3e3cb2d`.
Remote main inspected: `05d50a8bdf14ede2b1ec588f1fe78619f7387f0c`.
The status-bearing commit is identified by `git log -1 -- docs/KILAS_V2_PHASE1_STATUS.md`;
its own SHA cannot be embedded in its contents. Subsequent checkpoints record the preceding milestone SHA.

## Completed
- Read all four requested source documents completely; no prior status/Core implementation existed.
- Restored the exact remote feature tree (807255c0e97eeb246eb89bf44c38f1cbb7a95116)
  and commit after clone authentication was unavailable. All original blob hashes verified.
  Other workspaces were read only, and no existing work was discarded.
- Immutable validated inbound/history/result contracts, text-only simulator scope.
- Default-off `KILAS_CORE_V2_ENABLED` plus strict comma-separated positive integer
  `KILAS_CORE_V2_TEST_BUSINESS_IDS` environment allowlist. Both required; no wildcard.
- Injectable stateless `process_message`, ten-message history bound, one provider call,
  validated normalized result, sanitized provider failure, no automatic retry or live capabilities.
- External message IDs are correlation only in the core. The simulator adapter must reject supplied
  IDs explicitly until durable replay storage is implemented in a later authorized phase.

- Adapter preserves quota/history/progress/UI response using only existing simulation repository methods.
  Text/media/scope validation precedes reservation. Supplied external IDs are rejected; identical
  legacy text remains a new attempt. Errors preserve the reserved user row and generic assistant reply.

- Simulator route wired only after existing login/business/session checks. Disabled or non-allowlisted
  businesses retain the original legacy block unchanged. Full hub CSRF and Finance-session guards verified.
- Real existing repository methods tested with a disposable minimal SQLite fixture, including atomic
  quota reservation. No existing migration chain was executed; init_schema is a failing test tripwire.

## Tests
Dependency setup is outside the repository (no requirements changes): Flask 3.1.3, requests 2.34.2,
psycopg2-binary 2.9.13 and their dependencies installed in `/tmp/kilas-phase1-deps`.
For this checkout use:

```sh
export PYTHONPATH=/tmp/kilas-phase1-deps:/workspace/scratch/2b27258f2497/kilas-works-ai-admin/client-hub
python scripts/run_offline_tests.py --only test_kilas_core
```

PASS: 2 isolated test files, **30 tests** (12 contracts/gate/service + 18 adapter/route).
Coverage: validation, flag default off/allowlist/payload non-control, real authenticated business access,
unknown/unauthorized/archived businesses and stale/absent actor, CSRF, missing session, Finance-session
redirect, tenant/session history isolation, latest-ten history, duplicate policy, media rejection,
one provider call, provider failures, legacy response/error parity, quota across sessions/tenants,
concurrent last-slot reservation, onboarding progress, and no live writes/network/actions.

Individual milestone commands also passed:
- `python scripts/run_offline_tests.py --only test_kilas_core_contract.py` (7 initially, then 12).
- `python scripts/run_offline_tests.py --only test_kilas_core_simulator.py` (7 initially, then 18).

Additional existing regression:
- `python scripts/run_offline_tests.py --only test_finance_fx_precision.py`: **3 passed, 1 failed**,
  `test_combined_total_rounds_once`: expected 1, actual 50.
- Reproduced the identical failure in `/tmp/kilas-phase1-baseline`, extracted with `git archive`
  from starting feature SHA `387aa9d9a182111d12a6096969071e49d76a7e7d`, using its own client-hub
  PYTHONPATH and the same dependencies/offline runner. This is a confirmed pre-existing Finance
  issue, not a Phase 1 regression. Both Finance source and that test remain byte-for-byte unchanged.
- `test_postgres_sql_adapter_external_audit.py` runner exited 0, but the file has no main invocation;
  **not counted as test coverage**. `test_ai_onboarding_features_enabled_fix.py` is empty at baseline.
- Existing broad simulator/auth/Finance suites invoke migration chains during setup; not run under
  the explicit no-migrations instruction. The new suite directly covers the touched simulator path
  and existing auth/repository behavior without those migrations.
- `python -m compileall -q client-hub/kilas_core client-hub/tests/test_kilas_core_simulator.py`: PASS.
- `git diff --check`: PASS.

## Remaining / exact next action
1. Route wiring and integration suite complete; checkpoint this valid milestone.
2. Inspect `git diff --name-only 387aa9d9a182111d12a6096969071e49d76a7e7d HEAD` against the exact allowlist.
3. Verify final test run and clean tree; mark COMPLETE with baseline FX caveat. STOP; do not begin Phase 2.

## Boundaries / blockers
No code outside the allowlist will change. No Finance, schema/migrations, UI, WhatsApp
production path, deployment, or Render changes. No production database access.
No Phase 1 blockers. Pre-existing Finance FX failure is recorded above and remains outside scope. Use GitHub Git-data API for remote milestone commits if Git transport remains unavailable.
Tests must not invoke existing migration chains; use isolated test fixtures and network denial.
Do not start Phase 2.
