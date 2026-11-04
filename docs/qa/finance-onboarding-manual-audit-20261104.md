# Fresh workspace and retained manual Finance audit — 2026-11-04

## Production change and reproduced defect

Base: `eebd4add756dad8836273f0021ee2c87747d9c11` (PR206, preserving its money/inactive-account fixes).
A genuinely new owned business has no Finance branch. Access correctly binds `branch_id=None`, but dashboard calls `list_internal_transfers`, whose mandatory branch guard raises `branch_unavailable`; GET responds 400 before onboarding renders.
The only production change skips this listing when no branch is selected. Service guards, authentication, pricing, templates/design and writes are unchanged.

Copied the new test file alone into a detached worktree at exact base and ran:

```sh
python client-hub/tests/run_finance_regressions.py test_finance_empty_workspace_audit
```

Base: 4 tests, 1 failure, 0 errors: `test_fresh_workspace_repeated_get_renders_onboarding_without_financial_writes`, line31, `AssertionError: 400 != 200`. Other three controls pass. Fixed: 4/4 pass. The new tests verify two GETs return 200 and onboarding form, all Finance table rows remain identical, populated transfer ID/amount remains visible, foreign owner gets404, and direct list/write service calls with no branch still reject without writes.

## Validation

Current selected isolated offline suite: **417 tests, 0 failures/errors/skips** (per-suite machine-readable results adjacent). Execute the complete module selection in `.github/workflows/finance-calculation-audit.yml` with `client-hub/tests/run_finance_regressions.py`; the runner creates isolated fixture databases and blocks network calls. This comprises the existing174 critical/calculation/receipt/bridge tests,239 restored manual/boundary cases, and4 new onboarding tests.

Native PostgreSQL18, disposable loopback-only container: **15 tests, 0 failures/errors/skips**: workspace corrections4, money invariants4, calculations2, edits5. Execute `finance_workspace_postgres_qa.py` with `KILAS_PHASE7_POSTGRES_QA=1` and a disposable database named `kilas_phase7`; execute the other three `finance_{invariant,calculation,edit}_postgres_qa.py` scripts with `FINANCE_LOCAL_PG_QA=1` and disposable `kilas_finance_qa`. Synthetic credentials only. Container stopped after completion. No production Finance mutations or paid provider calls.

## Fixture changes and honest scope

The239-case selection is branches39, branch deletion4, bank manual42, phase2a25, phase2b25, phase3 reports20, phase5ab24, phase5c33 and personal reset27.
237 exercise retained manual service/accounting, access, reporting or rollback behavior; some also assert archived-route404. Two exclusively assert archived operator/import boundaries. Archived successful AI operator/import HTTP scenarios are NOT reported as passing. The import service42-case wrapper reuses41 named legacy methods plus one archived-route boundary test. Of115 original bank suite methods, **74 original methods were not executed** by this selection; they are not skips or passes.

Replaced stale signed-in session fabrication with current auth helper, made Indonesian text expectations explicit via locale, replaced removed Anthropic receipt mock with offline OpenAI contract, used actual category leaves, and supplied the existing signed reset review token. The original paid subscription-expiry branch case is replaced by current FREE access/emergency-disable behavior; no production subscription policy was changed. Product-unavailable tests explicitly disable self-service in their fixture as well as the obsolete beta flag, preserving real deny assertions. Archived assistant/operator/import routes remain unavailable. Two reused bank methods retain original service rejection/VOID checks while updating their trailing HTTP expectations to404.

Exact deployed-base legacy comparison (eight preexisting suites, excluding the new bank wrapper): **197 tests, 11 failures, 42 errors, 0 skips**. The42 errors are38 branch and4 deletion fixtures referencing removed `finance_receipts.requests`; they previously prevented assertions from running. Eleven failure events across phase2a2, phase2b2, phase3 three, phase5ab2 and phase5c2 come from stale auth/locale or availability expectations. Corrected fixtures execute these assertions successfully. Personal reset27 already passed. These are comparison results, not evidence that the original red tests are acceptable indefinitely. See JSON for exact per-suite counts.

## Remaining gaps

This is not a claim that all historical Finance suites are green: the entire1211-test historical selection was not rerun for this follow-up. The74 unselected bank scenarios and other archived AI/provider suites require separate classification; archived product functionality must not be revived to satisfy them. No live authenticated onboarding/browser action was performed, and no production data was touched. Native PostgreSQL scripts cover services; the new HTTP onboarding assertions run against isolated SQLite. CI results for the final pushed head must be checked independently before integration. No merge or deployment is part of this deliverable.
