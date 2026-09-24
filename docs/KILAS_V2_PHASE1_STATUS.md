# Kilas V2 Phase 1 status

Status: IN PROGRESS — contracts and rollout gate checkpoint.

Branch: `feature/kilas-core-v2`.
Starting feature SHA / current commit before this checkpoint: `387aa9d9a182111d12a6096969071e49d76a7e7d`.
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

## Tests
- PASS (7 tests): `python scripts/run_offline_tests.py --only test_kilas_core_contract.py`.
- Existing `test_ai_onboarding_features_enabled_fix.py` is empty at the base SHA; do not claim coverage from it.

## Remaining / exact next action
1. Contracts/gate test passed; checkpoint ready. Continue with service implementation.
2. Implement injectable service and tests; checkpoint.
3. Implement safe simulator adapter and tests; checkpoint.
4. Wire only the existing simulator handler behind the gate; checkpoint.
5. Run focused offline regressions, inspect full Phase 1 diff against starting SHA, mark COMPLETE.

## Boundaries / blockers
No code outside the allowlist will change. No Finance, schema/migrations, UI, WhatsApp
production path, deployment, or Render changes. No production database access.
No functional blockers. Use GitHub Git-data API for remote milestone commits if Git transport remains unavailable.
Tests must not invoke existing migration chains; use isolated test fixtures and network denial.
Do not start Phase 2.
