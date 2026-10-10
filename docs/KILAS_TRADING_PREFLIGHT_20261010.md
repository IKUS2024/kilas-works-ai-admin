# Runnable offline diagnostic preflight

Preserved from base810c8419740ec4c2d8de45f145e2d14137078142 and integrated onto
verified Kilas AI release aa06a7edb6cc142776dce1b6dc1400b81342320f. The owner
authorized serial Trading release after that AI deployment. This
tool has no endpoint, source registration, network transport, SDK, inference or
execution capability. Existing diagnostic UI,8192-byte observation endpoint,
analysis.market_source=None, MOCK, risk/SL/strategy and other products unchanged.

## Run locally in the existing project Python environment

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/trading-venv/bin/python \
  scripts/trading_diagnostic_preflight.py /absolute/local/report.json \
  --policy-dir client-hub/tests/fixtures/trading_clock_policy \
  --sha256-file /absolute/local/report.sha256
```

All paths are local; there is no URL/file-ID fetch. Use the original report bytes
and its capture sidecar for integrity checking. Alternatively --sha256 accepts
one64-character hex digest. Without either, integrity is explicitly NOT_PROVIDED.
A sidecar match proves byte consistency with the supplied digest, not broker
authenticity. Report bytes are read in memory only and never copied or retained.
Stdout is a sanitized JSON explanation; it may be saved as the review result.

For a runnable synthetic demonstration:

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/trading-venv/bin/python \
  scripts/trading_diagnostic_preflight.py \
  client-hub/tests/fixtures/trading_preflight_synthetic.json \
  --policy-dir client-hub/tests/fixtures/trading_clock_policy
```

Node is used for the existing browser diagnostic parser; the project Python
environment supplies the existing market projection dependencies. This is a
repo review tool, not a new installer for the Windows broker host.

## Independent result stages

| Stage | Meaning |
| --- | --- |
| schema | Reuses parseReport, including128KiB/depth/value/duplicate/prototype/decimal/runtime-claim guards. No second diagnostic schema implementation. |
| integrity | Supplied byte digest match, missing digest or mismatch. No authentication claim. |
| policy_integrity | Three source files match immutable reviewed pins before import. Only pinned bytes are copied to a private temporary code directory; no raw report is written there. |
| demo_identity_binding | Uses project_collector_market and compares two sessions, sample/batch capture marks, ordered call intervals and risk session. This is consistency of recorded claims, not tenant or fresh SDK authentication. |
| clock_replay | Recomputes each qualify_batch output/hash, replays the original BatchFixtureSource with a clearly offline copy and recorded candidate window, and compares sequence, clock/tick/candle results. Never grants a live lease or permanently approved profile. |
| contract_specs | Exact numeric consistency between two market specs, step/grid and quote tick size. Economic units and GOLD mapping remain independently unverified. |
| minimum_lot_notional | Separately binds risk specs/quote to the second market and requires minimum lot/formula agreement. Reports BLOCKED_MINIMUM_LOT_CAP, within-cap arithmetic only, absent risk or an actual mismatch. Cap staysUSD2000. |
| runtime | Always disconnected/ineligible, AI/paper/broker false, producer NOT_IMPLEMENTED, replay only. Capture recency is disclosed separately and cannot prove source freshness. |

Exit0 means OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED, including valid reports with
economically BLOCKED minimum lot. Exit2 means invalid/mismatched report; exit3
means local input/parser/policy unavailable. No exit code authorizes trading.
Each failed stage names the next action without echoing private data or arbitrary
exceptions. Subsequent stages are explicitly NOT_EVALUATED rather than guessed.

## Verified evidence and tests

Thirteen new preflight methods PASS, including CLI exits and digest-file path,
private-field exclusion, policy-tamper rejection before execution, malformed/
oversized/duplicate/execution claims, session/call/sample mismatch, invalid NTP,
claimed qualification/hash/uncertainty/tick tampering, expired recorded lease,
changed specs/grid, mismatched risk quote/formula/lot and recent-looking
within-cap reports still unable to activate runtime. Initial CLI test failed
because its test module omitted sys; that test import was corrected. No
production guard or test expectation was weakened.

The actual October9 report was also read fully through Library text and passed
to preflight in memory. Both clock qualifications were recomputed and matched:
8 replies, uncertainty0.07884392079210205078125/0.08197677381241455078125 seconds.
Recorded DEMO binding/specs/formula are consistent; BUY0.01 lot4188.55 and
SELL0.01 lot4188.02 remain BLOCKED. It is STALE_HISTORICAL with no live lease.
This check deliberately reports integrity NOT_PROVIDED: Library text is not the
original binary report+sidecar. No private report/identifiers/balance/history/
raw packet fixture was persisted or committed. Only synthetic report and exact
reviewed offline policy source fixtures are included.

Parent-inspected October10 UI screenshot separately shows Demo Account - Hedge
on server10 and connection bars, with Algo Trading off. That is UI-level
presence only; static MarketWatch quotes/time are not fresh-source proof, SDK
session binding or bridge access. The report's provenance field and
static_ui_evidence_grants_sdk_binding=false keep that distinction explicit.
Do not activate Algo Trading based on this preflight or screenshot.

Existing diagnostic20, producer14 and host-isolation4 regressions also PASS.
Together with preflight13,51 unique methods PASS in this phase. Final metadata
fields were verified with focused positive/CLI tests. Syntax and diff-check
PASS; original policy pins/cap unchanged. No full historical suite or live
broker acceptance is claimed.
