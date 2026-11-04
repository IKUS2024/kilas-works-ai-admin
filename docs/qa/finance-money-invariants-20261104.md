# Finance monetary invariant follow-up — 2026-11-04

Base: `9219cb871f700e91666762b0cf50c973d1dc461b` (first audit release). No UI, pricing, model, credentials, database migration, production financial mutation or paid provider call.

## Confirmed defects and repairs

1. **Mixed decimal/group separators silently inflated amounts.** `1,234.567` and `1.234,567` produced **123456700 minor units**, whereas the documented last-separator decimal contract and existing six-digit fractional parser require **123457 minor units** after ROUND_HALF_UP to two ledger decimals. `1,234.567,890` was also wrongly accepted as an integer. The thousands-only regex now requires one consistent separator. Mixed valid locale forms fall through to the existing decimal parser; alternating malformed forms reject. The existing clearly nonzero single-separator thousands convention (`1,234` / `1.234` = 1234 major units), scale and rounding policy are preserved. The review follow-up below disambiguates leading-zero fractional inputs. Direct IDR/USD/EUR, signed amounts, transaction entry, internal transfer and invoice payment paths are covered.

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

## Blocking-review corrections

Both review findings were reproduced on previous candidate `954ba7230b1e72bd1f7ba20c3fe22e5cf98e2046`: the 13 tests in the expanded parser/reversal suites produced **18 assertion failure events and zero errors**. The same suites plus the 12 existing workspace-correction tests pass after correction.

- `.500` / `,500` / `00.500` now produce **50 minor units**, `.123` / `0.123` produce **12**, and `0.005` / `,005` produce **1** after the existing half-up rounding. Previously these three-digit fractions matched thousands grouping. A grouped integer must now start with a nonzero group. Zero-prefixed multiple grouping such as `0.123.456` or `0,123.456`, and ambiguous nonzero-leading-zero forms `01.234` / `01,234`, reject rather than silently changing magnitude. Clearly grouped `1.234`, `1,234`, and repeated thousands remain supported. Six-digit precision, signed values and positive-only rejection after rounding to zero are tested. Actual transaction HTTP submissions cover both `.500` and `0.123`.
- `move_transaction_workspace` bypasses the generic revision helper, so it now independently requires its original account to be active **before** target defaults/category/account mapping. Both direct service and real HTTP regressions reproduce the old mutation and now verify the complete disposable SQLite dump is unchanged on rejection (including mapping, ledger, revisions and audit). Explicit reactivation through the existing account creation flow then allows the HTTP move. The target account is selected/reactivated by the existing `_workspace_move_target_account` behavior and validated as active by `_transaction_data`; no new automatic account-status change was added. Native PostgreSQL adds an atomic source-account rejection case.

Final local verification: **174 selected SQLite/offline tests pass**, plus **11 native PostgreSQL tests** (4 new invariants, 2 existing calculations, 5 existing edit/concurrency/rollback cases). Full logs are added to the JSON artifact. Remote CI on the new head must be checked separately.

### Mutation-path coverage and limits

- Guarded and exercised: generic transaction revisions (also used by invoice/bill payment edits), transaction void, internal transfer void, FX amount edit/void, and individual transaction workspace move. Current-workspace and foreign-owner checks are retained.
- Opening/current-balance setters already require active accounts. Account creation can explicitly reactivate an existing identity. The existing full-account workspace move transfers opening balance and all movable history together, rejects invoice/FX/internal-transfer/import/posted-schedule links, and leaves zero at its source; its existing workspace-correction suite passes. It was inspected but no new exhaustive inactive/full-account matrix was added in this patch.
- Verified reset intentionally voids all selected-branch monetary sources and zeroes openings as one operation; it is not routed through ordinary reversal guards. Its 27 current tests passed in the separately recorded manual audit, not as new regressions in this critical PR.
- Receipt/import/new-payment paths validate active destination accounts through their current service contracts; existing focused suites pass. Metadata-only notes, counterparty and attachment timestamp updates do not alter balance amounts.
- Remaining unexecuted cases include dedicated deactivation-versus-mutation race tests for every path, exhaustive full-account relocation combinations, legacy archived AI/provider suites, and production-history reconciliation. No production rows were examined or repaired. This is a scoped monetary invariant repair, not certification of every historical test.
