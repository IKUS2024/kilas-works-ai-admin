# AI Call recovery and public follow-ups — 2026-10-20

Scope: AI Call, including its current-information search tool. Based on main
0f33bb4e5b285cbc0bb6fe0355da4e27ca625b30. No text-chat Search, Finance,
Translator, Voice Over, billing, model/provider or shared adapter changes.

## Verified causes and changes

- One read-poll timeout previously propagated to CallSession.fail, cancelling
  microphone capture and ending the existing server conversation. Synthetic
  baseline tests reproduce capture cancellation on the first timeout. Retry only
  GET polling on timeout/network/502/503/504, twice with 300/600ms delay, retaining
  session and cursor. Never retry admission, audio POST, model or search dispatch.
  Authentication/protocol failures remain terminal; Stop cancels backoff.
- Public query minimization required every keyword in the current utterance.
  After “cuaca Jakarta hari ini”, “Kalau Bandung besok?” could not resolve
  “cuaca Bandung besok”. Allow short Indonesian/English follow-ups to reuse only
  the immediately previous validated public query, with a prior topic anchor and
  current words. Private/opt-out turns clear context. Invented query tokens still
  fail before reservation. Integrated worker fixture verifies two distinct turns,
  new location, and no extra paid search/retry.
- The Call prompt explicitly demanded concise answers/short sentences. Replace
  that with request-appropriate depth, reasons, steps, examples and coverage of
  requested parts, while honoring explicit brevity and avoiding filler. Provider
  generation cap and metered accounting envelope stay unchanged (1024 output
  tokens); no unapproved spending or claim of unlimited output.

## Availability and lifecycle audit

Existing production readiness at 2026-10-20T16:16:04Z reports authenticated
scope, continuous=true, configured_ready=true, public_search_configured=true,
and both owner/nonowner ready with account funding. The old shared allowance is
exhausted; account-funded use remains ready. Free/unfunded accounts still depend
on existing allowance/entitlements: this release does not grant unlimited paid
usage or reset trial spend. No internal QA-only gate was found in this live
configuration. Existing fixtures test nonowner readiness, account ownership,
CSRF, credit exhaustion and metered continuation beyond four responses/90 seconds.

Capture continues across normal turns, including silence; the existing watchdog
measures missing audio frames, not silent speech. Explicit Stop, hidden page,
device loss and capture failure stop recording/output. Provider session resumption
retains its checkpoint. This patch does not remove foreground privacy fences or
introduce unsafe automatic microphone restart.

## Verification

- 61 Node Call tests pass, including four new read-poll recovery cases.
- Python public-query 6, public-search 58, conversation 3 and Call lifecycle/budget
  32 tests pass. Full Call runner and synthetic browser outcomes recorded in the
  release artifact.
- Existing public-search fixtures cover provider-origin citation links, stale
  dated rates, missing sources, timeout/empty/error, one attempt per request,
  recoverable next request and late results. No real provider requests made.
- Baseline regression evidence: old polling fails three new transient-recovery
  cases (capture already cancelled); old query minimizer returns None for the
  public follow-up. Current implementation passes.
- Pre-existing offline paid-smoke harness has two failures and one error because
  production setup exceeds its 8192-byte diagnostic fence (`setup_changed`).
  Reproduced with baseline main modules. Do not relax this paid diagnostic safety
  fence or execute a paid smoke without a separately approved bounded budget.

No guarantee of perfect model answers or physical microphone reliability. Model
semantics, actual provider availability and physical devices remain unverified
by synthetic tests. Production browser validation belongs to the parent because
this execution proxy previously denied direct production HTTP.

Minimum release: non-force push current main, single Render Client Hub deployment,
verify exact commit reaches LIVE and sanitized startup readiness. Preserve all
newer main changes. Rollback, if required, is a targeted revert of this commit.
