# Translator latency: read-fence overhead, 2026-10-20

## Production diagnosis before this change

Read-only production logs from 07:48–07:51 UTC, on Start–Stop release
`29b986f3ad9a64b3a221a115eb31c32bce2c0844`, contained three completed turns.
No synthetic provider request was made for this diagnosis or correction.

| Completed sample | Translation ms | First delta ms | Translation fences ms | First TTS byte ms |
| --- | ---: | ---: | ---: | ---: |
| 07:48:27 | 3297.4 | 2018.5 | 801.4 | 6040.5 |
| 07:48:58 | 8407.8 | 7668.0 | 505.6 | 11017.8 |
| 07:51:32 | 20808.0 | 16949.3 | 1568.7 | 23677.0 |

These backend clocks start at final input commit, not at the browser's Stop
gesture. Input transport includes recording time. The first-delta clock used
before this patch includes the first authority fence. The dominant wait is
before useful translation output; these logs cannot distinguish provider queue,
inference, network and stream-parser buffering. Database overhead contributes
but cannot explain the entire 20.81-second translation stage.

## Focused correction

`live_translator.check_session` temporarily enables PostgreSQL autocommit only
for its existing read-only session/funding/proof checks. The old generic read
helper commits every SELECT; in autocommit the driver does not send that extra
COMMIT. Every event still performs the same fresh SELECTs. There is no cached
authority, skipped check or reduced cancellation cadence.

The context restores the original write mode on success and denial, skips
caller-owned transactions and SQLite, and discards a connection on mode-reset
failure. Existing bounded stale-read recovery remains in the shared helper;
no provider retry is added. Shared database code and all financial mutations
are unchanged.

New numeric-only diagnostics separate translation reservation, first provider
iterator event and first delta arrival before the authority fence. Content is
still checked before processing/publication. Existing latency fields remain.
The iterator-arrival metric still includes provider/network/parser time; it is
not a direct supplier inference measurement.

No model, prompt, output budget, language support, Eleven v4 voice/model,
Start–Stop/End, browser/audio pipeline, billing/quota or isolation policy changes.
No migration, configuration change or new dependency.

## Verification

- 57 targeted Python tests passed: timing, read-mode lifecycle, realtime,
  continuation, handoff, progressive output, early text and language contracts.
- Four additional tests passed against disposable local PostgreSQL 18, using
  two connections to verify next-fence proof revocation, End/cancel/expiry/
  foreign-owner denial and caller-owned transaction rollback. The eight mocked
  lifecycle tests also cover nesting, mode failures and replaced connections.
- Three Chromium Start–Stop browser tests passed with synthetic/mocked providers.
- Two older broad modules ran 57 tests with seven failures. Re-executing the
  exact HEAD implementation in the same isolated test environment reproduced
  the same seven failure names; they predate this patch. Broad suite is not green.
- `git diff --check` passed. No paid provider request or private audio fixture.

Actual local native-driver comparison: 50 fences retain 150 SELECTs in both
versions. Wire COMMITs fall from 150 to zero; elapsed time in one local run fell
from 76.532 ms to 47.525 ms (about 38%). This is a local overhead benchmark,
not a production end-to-end latency result or a real-time guarantee.

The remaining large first-output wait needs post-release numeric observations.
This correction alone does not establish a 1–2-second result or resolve the
unattributed supplier/network/parser portion. No physical-device or paid
post-change speech session is claimed. Production verification uses Render
deployment identity and startup/read-only logs; direct site HTTP from this
environment was previously blocked by its outbound proxy.
