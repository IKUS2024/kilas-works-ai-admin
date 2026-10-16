# Authenticated native Translator rollout — 2026-10-16

This change follows the owner's explicit approval to share the existing inclusive
Rp500,000 prepaid allowance with authenticated Kilas accounts, without automatic
top-up. It supersedes the owner-only access description in earlier release notes.
Funding policy and provider credentials are unchanged.

## Diagnosis and continuity

Production metadata for owner 9 at 05:24–05:34 UTC shows legacy `kilas-male` and
`kilas-female` turns, with no new native Gemini dispatch. The legacy capture
intentionally releases the microphone while processing and playing each result.
Observed backend processing took 3689.4–9243.7 ms. Two turns returned `no_speech`;
one was cancelled. These are server timings, not audible latency measurements.
They do not establish the exact cause of the reported browser pause.

A separate defect was reproduced offline: a queued error callback from an already
finalized capture could interrupt its accepted turn during processing, playback,
or no-speech recovery. Retiring that capture generation at acceptance and recovery
prevents the stale callback from pausing the current turn. Three regressions failed
before the fix and pass afterward. This does not attribute the production report
to that specific defect.

When native access is ready, the normal Live entry opens the existing continuous
Gemini page with its explicit Google processing consent and native voice. Legacy
provider/model/voices and active sessions remain intact; no session is forcibly
ended or migrated. An active legacy session keeps its legacy page until the user
ends it. The legacy silence endpoint stays 2000 ms with its original
voice-activity/minimum-speech safeguards. That interval is a silence wait, not a
promise of a two-second full response.

## Shared authorization and accounting

`KILAS_LIVE_GEMINI_AUDIENCE=authenticated` explicitly allows existing authenticated
accounts to use native Translator. Its default is `owner`; synthetic QA always
remains owner-scoped. Funding owner 9 is the custodian of the existing campaign,
not a separate allowance issued to each user. No new role or credential is granted.

The campaign remains `gml-owner500k20261016`, with its original immutable price
version and one global USD10 internal cap. Every historical `gml-%` reserve counts
across every user and campaign. Audience changes neither reset the ledger nor
multiply the cap. Before each physical provider dispatch, a PostgreSQL advisory
lock serializes the shared allowance and each user's single active operation.
The conservative USD0.25 reservation is retained after every possible dispatch,
including unknown outcomes. No automatic paid retry or regeneration is added.
Existing global concurrency, per-account quota/balance/exemption and cancellation
checks remain in force. End and settlement remain available after rollout-off.

Only native routes receive the new audience permission. Session and turn ownership
remain tied to the authenticated user. Synthetic capture listing/export remains
restricted to its separately verified owner; other authenticated users gain no
capture/history/media access. No capture, session, turn or provider request is
created by rollout verification.

The acknowledged internal conversion and guard remain conservative application
accounting assumptions. They are not a verified exchange rate, supplier invoice,
or an absolute supplier billing stop. Supplier billing, automatic top-up and keys
are not changed by this release.

## Verification and release evidence

Offline Flask/Node tests, a disposable loopback PostgreSQL concurrency rehearsal,
and dedicated browser-free CI cover the changed paths. Startup diagnostics use
SELECT-only checks for owner 9 and one existing nonowner account. Both must report
the same remaining shared allowance; each snapshot remains subject to real
admission and account state when Start is requested.

The release evidence JSON records the exact tested commit, main tree, Render
deployment, runtime eligibility and before/after ledger. No provider calls,
microphone capture, browser tests, new accounts, credentials, subscriptions or
supplier-setting changes are made for verification. Actual audible Android
latency, background behavior and semantic final-word completeness remain
unverified. Cloud HTTP health may be unavailable through the CONNECT proxy;
Render live status and worker readiness logs then provide the runtime evidence.
