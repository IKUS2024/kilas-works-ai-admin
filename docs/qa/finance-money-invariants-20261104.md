# Finance monetary invariant follow-up — 2026-11-04

Base: `9219cb871f700e91666762b0cf50c973d1dc461b` (first audit release). No UI, pricing, model, credentials, database migration, production financial mutation or paid provider call.

## Confirmed defects and repairs

1. **Mixed decimal/group separators silently inflated amounts.** `1,234.567` and `1.234,567` produced **123456700 minor units**, whereas the documented last-separator decimal contract and existing six-digit fractional parser require **123457 minor units** after ROUND_HALF_UP to two ledger decimals. `1,234.567,890` was also wrongly accepted as an integer. The thousands-only regex now requires one consistent separator. Mixed valid locale forms fall through to the existing decimal parser; alternating malformed forms reject. The existing single-separator convention (`1,234` / `1.234` = 1234 major units), scale and rounding policy are unchanged. Direct IDR/USD/EUR, signed amounts, transaction entry, internal transfer and invoice payment paths are covered.

2. **An unpaid installment could change currency without conversion.** A 100.00 IDR plan with 50.00 IDR items permitted moving a rule to a USD account while retaining 5000 minor units. The HTTP form also allowed this once supplied the correct parent/child category fields. The installment invariant now compares the selected account currency to the authoritative plan currency before updating the rule. Both direct service and actual HTTP regressions reject USD without changing the rule; the same valid HTTP form can select another IDR account and its payment remains exactly 5000 IDR minor units.

3. **Reversal or reassignment could hide restored cash in an inactive account.** Opening 10000, transferring/spending 10000, and deactivating the now-zero account was valid. Voiding the transfer/expense restored 10000 to that inactive account, excluded from available balance totals. Reassigning a prior expense and changing/voiding an FX exchange have the same risk. Under the existing business write lock, transaction revisions/voids, both internal-transfer accounts, and both FX-exchange accounts must be active before mutation. Rejections leave records, audit and revision rows unchanged. No account is automatically reactivated. The existing `create_account` reactivation path restores the same account identity; a subsequent reversal succeeds and available totals reconcile. Already-void idempotent replays remain unchanged.

## Evidence

- Identical final new tests on a detached exact-base worktree: **11 tests, 29 assertion failure events, 0 setup/runtime errors** (subtests explain the event count). All three defects fail on real disposable service/HTTP paths. Full output is in the JSON companion.
- Candidate focused suite: **170 tests, 0 failures/errors/skips** across 18 suites. This includes all 159 first-release current tests, receipt/Bridge tests, and 11 new tests. The final strengthened installment HTTP test was rerun independently: 2/2 pass.
- Disposable loopback PostgreSQL 18: **10 tests pass**: 3 new currency/reversal invariants, 2 existing native calculation cases, and 5 existing native edit/concurrency/rollback cases. The script refuses non-loopback targets or any database not named `kilas_finance_qa`.
- `git diff --check` passes. Dedicated calculation workflow includes the new SQLite and PostgreSQL regressions. Remote exact-head CI still needs inspection after publication.

Run the suites named in `.github/workflows/finance-calculation-audit.yml` using `client-hub/tests/run_finance_regressions.py`. New native script: `client-hub/tests/finance_invariant_postgres_qa.py`, with the same guarded disposable setup as the existing native scripts.

## Separate manual-audit work and remaining uncertainty

Per coordinator instruction, unrelated fixture modernization is excluded from this critical-fix branch. Branch `fix/finance-manual-fixture-audit` at `728d8320` contains current authenticated/locale fixtures, a current mocked OpenAI receipt fixture for manual scenarios, 41 reused import-service assertions plus an archived-route check, and restoration of branch/recurring/invoice/report/reset assertions. Its **239 tests pass** independently. No archived analyst/operator/assistant/import HTTP flow was re-enabled. One original operator-success scenario was replaced by an explicit unavailable/no-write assertion; its archived success behavior is not claimed as tested.

That separate branch also fixes an independently reproduced onboarding defect: Finance GET on a business with no branch returned 400 because dashboard rendering unconditionally called the branch-required transfer list. It renders an empty transfer list only until a branch exists; transfer mutation gates stay intact. This is not included in the three monetary fixes.

The entire historical Finance baseline is **not certified green**. The prior 59-file/1211-test result still documents hundreds of legacy scanner/archived-AI setup failures. A broader follow-up rerun was deliberately interrupted to prioritize this critical release; it is not a completed baseline. Archived provider/HTTP scenarios and remaining legacy suites require separate classification or extraction of supported manual invariants. Historical production rows were not inspected or repaired, and no claim is made about whether any customer used the affected paths.

## Integration

Draft PR only. Coordinator owns independent review, merge and deployment. No migration or environment change is required. The three production modules changed are `routes_finance.py`, `finance_installments.py`, and `finance_service.py`. Before release, review the intentional behavior change that editing/reversing financial records on an inactive account requires reactivating that account through the existing flow.
