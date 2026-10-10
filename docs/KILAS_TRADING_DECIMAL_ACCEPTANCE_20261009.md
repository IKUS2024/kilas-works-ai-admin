# Offline recorded-risk decimal acceptance

Bounded continuation on clean base `810c8419740ec4c2d8de45f145e2d14137078142`. This local change tightens the existing historical DEMO diagnostic reader. No broker connection, execution, AI, SDK/NTP request, source/risk/strategy change, commit, push or deployment is part of this deliverable.

## Concrete defect and correction

The prior reader converted risk fields with `Number()`. A JSON numeric literal `2000.0000000000000001` rounds to 2000 and was accepted with `cap_status=WITHIN_CAP`. This misclassified the recorded risk claim, although execution remained blocked. A before/after offline reproduction confirms `WITHIN_CAP` before and `REJECTED` after.

The reader now accepts bounded positive decimal **strings** for risk quantities and USD amounts, compares fixed eight-place integer units using `BigInt`, and returns canonical strings in its internal allowlisted projection. No `BigInt` escapes into JSON serialization. Display retains meaningful fractional places instead of rounding everything to cents: `2000.00000001` remains visible and must be `BLOCKED`. This is stricter schema acceptance, not a different cap or an execution gate.

## Exact selected-field input contract

All existing report/collection/clock/market/risk status and disabled-flag requirements still apply. Within every included risk record:

| Field | Required representation | Acceptance rule |
| --- | --- | --- |
| `notional_cap_usd` | Decimal string | Exactly USD2000; equivalent trailing-zero representations allowed |
| `scenarios[].volume_lots` | Decimal string | Positive; format validation only, never proof of broker minimum/step validity |
| `scenarios[].notional_usd` | Decimal string | Positive; exact comparison with cap |
| `scenarios[].cap_status` | Fixed enum | `BLOCKED` iff notional is greater than 2000; otherwise `WITHIN_CAP`; neither grants execution |

Decimal string grammar: `\d{1,9}(?:\.\d{1,8})?`, with strictly positive integer units after scaling. Missing/null/boolean/numeric fields, signs, exponent notation, nonfinite values, currency suffixes, HTML, zero, excessive length/precision and inconsistent status are rejected. The schema deliberately rejects numeric JSON scalars even when apparently integral, avoiding hidden parse-time rounding. Leading/trailing zeros are normalized without rounding. Cap, lot quantity and notional in the internal projection are now strings; the only current consumer is this reader's text renderer. No server API contract changes.

Library text inspection confirmed the existing recorded report uses compatible strings: cap `2000`, volume `0.01`, and notionals `4188.55000` / `4188.02000`. Only those selected lines were re-read; the full private report was not copied, uploaded or reimported for this continuation. Reusable tests use synthetic fixtures.

## Verified acceptance

- Ten parser/security test methods pass, including immediately below/equal/above-cap boundaries, rejection of missing/invalid decimal facts and the original numeric-rounding reproduction.
- Existing Trading38, analysis17, observation15 and host-isolation4 regressions pass: **84 test methods total**.
- Existing responsive browser suite passes. It additionally imports a synthetic `2000.00000001` boundary report, verifies both directions remain `BLOCKED` and the exact amount stays visible, then checks zero import network requests, unchanged Trading storage, disabled broker/AI controls, rejection/clear/reload and the existing MOCK workflows.
- JavaScript syntax and `git diff --check` pass. Logs: `/tmp/trading-precision-browser.log`, `/tmp/precision-test_kilas_trading.py.log`, `/tmp/precision-test_kilas_trading_analysis.py.log`, `/tmp/precision-test_kilas_trading_observation.py.log`, `/tmp/trading-precision-hosts.log`.

## Preserved blockers and next safe step

This compares a user-supplied **historical reported notional**, not independently verified broker sizing. It does not derive notional from contract size, verify volume minimum/step, infer freshness or evaluate real costs, margin, SL validity, net P&L or drawdown. Producer acceptance remains `NOT_IMPLEMENTED`; runtime/broker/AI/paper execution remain disabled. Candidate broker offset/DST/profile and GOLD mapping remain unverified. The recorded minimum 0.01 GOLD scenarios remain above the unchanged USD2000 cap and BLOCKED.

The next justified offline improvement is a separately scoped consistency check deriving hypothetical notional from sanitized, explicitly typed contract units/size, minimum/step lot rules, quote currency and bid/ask facts. Before that can validate the actual broker, those facts and their independent evidence must be provided and reviewed; synthetic values cannot satisfy broker acceptance. No current authorization permits broker orders or runtime activation. Before any later approved release of this local patch, bump the Trading asset cache version, review the diff and run applicable CI; this continuation performs no release.

## Subsequent local consistency step
The parent authorized and reviewed the next offline consistency scope. Its strict unit/fact contract, final combined94-test/browser results, actual report compatibility and combined self-review are in `docs/KILAS_TRADING_NOTIONAL_CONSISTENCY_20261009.md`. The decimal-boundary reproduction above remains valid; both patches are local and unreleased.
