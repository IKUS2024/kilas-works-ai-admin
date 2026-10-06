# Manual analyst checkpoint — 2026-10-06

## Authorization and state

Owner approved use of the existing OpenAI subscription/credits for exact GPT-6.1 Sol, medium reasoning, with USD5/month and no automatic top-up. This phase implements the isolated adapter and tests. No production inference, credentials, data connector, scheduler, broker write, authentication change or new paid resource was activated. Production source remains `None`; inference defaults off. The UI reports UNAVAILABLE and disables analysis until prerequisites are met.

The existing executor recovered after the 08:50 UTC lifecycle interruption: shell access, retained files and completed test processes were verified. No replacement worker/environment was created. This checkpoint supersedes speculative recovery status.

## Verified model and prices

Official [model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and [release announcement](https://openai.com/index/introducing-gpt-6-1-sol/) were checked without inference. They document the exact API model, medium reasoning and structured outputs. Standard prices are USD2/million input and USD10/million output; cached input USD0.10 and cache write USD2.50. Regional processing adds 10%. This adapter pins default service tier and uses conservative cache-write input pricing plus that premium. Long-context/fast paths are excluded by its input bound and tier.

`analysis_policy.json` records the reviewed rates and a seven-day expiry (2026-10-13 UTC). Missing, altered or expired proof blocks calls. Fresh project-specific model access remains **unverified**: local credentials are absent, and production credentials were neither retrieved nor used. The adapter performs a non-inference GET for the exact model before any future POST; failure closes the path without substitution.

## Implemented behavior

- Manual proposal-only BUY/SELL/WAIT; fixed prompt/schema and exact model/effort/tier. No order tools, quantity selection or automatic application to paper positions.
- Server-injected DEMO snapshot only; fixture data is accepted solely in Flask test mode. No browser-supplied snapshot/prompt. Strict fields exclude account identifiers, balances, positions, credentials and broker telemetry. XAUUSD M1/M5/M15; 12–48 closed candles, source/timestamp recorded, maximum 120-second quote/capture age, deterministic OHLC/interval/spread validation. Synthetic dashboard replay is never sent to AI.
- USD5/month, USD0.25/day, at most 10 attempts/day (UTC); independent of the app's pilot quota exemption. Each call commits a USD0.077 maximum reservation in the existing Trader events ledger before HTTP. Actual valid usage settles to a conservative cost upper bound. Uncertain calls retain the full amount. Three unresolved/full-cost calls can exhaust the daily cap; 10 is a maximum, not guaranteed availability.
- Account lock serializes reservations; one pending request at a time. Stable request keys and normalized closed-bar identity prevent repeated billing. A crashed pending record blocks new calls across month boundaries. No automatic retry or refund. Malformed ledger/model/tier/usage freezes further analysis for review. Missing usage retains full cost. API invoice reconciliation/manual pending recovery is a future operator task.
- Fixed OpenAI destination, redirects disabled, bounded request/response/timeouts/output including reasoning, no credential generation or fallback. Pause/kill/freshness/policy are rechecked before and after inference. Invalid or stale proposals become WAIT; cached stale results cannot supply an actionable proposal.
- Explainable evidence retains market inputs, hash, prompt version, model/effort, rate proof, reservation, usage and decision in Trader records. Finance and the shared AI usage ledger are untouched. No migration was needed.

## Validation

Local checks passed: 38 original paper tests and 17 analyst tests on SQLite; all 55 on disposable PostgreSQL 18 with additive-table/idempotence/isolation verification. Analyst HTTP is stubbed; unexpected real HTTP fails tests. Covered concurrency, deduplication, stale/disconnected/REAL/extra-field rejection, missing/expired price proof, budget/day/month limits, timeout/pending recovery behavior, provider/model/tier/usage failures, strict SL/TP, kill/pause, pilot-only permission and CSRF checks.

Browser passed existing login → Service → Trading and functional paper entry, SL/TP, pause/resume, no-signal, 20-step replay, risk rejection, close and journal at widths 1440/768/390/320; no page errors. AI remains disabled/UNAVAILABLE after a paper error. Protected regressions passed: Finance 16, Assist connections 9, shared AI 24, production foundation 28 (including existing session behavior). Remote CI/deployment status is recorded in the follow-up delivery record; this local checkpoint alone does not claim either.

No authenticated executor production pilot session exists. Owner's phone screenshot verifies rendering only. Production paper operations and live AI analysis are not claimed tested. Production browser access from this executor was previously blocked by its proxy; no auth-cookie fabrication or bypass was attempted.

## Remembered device proposal — not implemented

Current CLIENT_OWNER sessions are browser sessions with an idle timer (default 1800 seconds; actual production override not freshly verified). There is no current remembered-device/revocation table. No timeout or login code changed in this phase.

For explicit approval: only the verified pilot may opt into “Remember this device 30 days” after fresh authentication on the owner's existing device. Store a hash of a random server token in an additive auth table; use a Secure, HttpOnly, SameSite=Lax cookie with fixed absolute 30-day expiry. Keep the normal idle timer, restoring a short session on a safe GET. Revoke that device on logout and all remembered pilot devices on password/email change or account disable; check revocation on sessions restored this way. Other users/admins retain their current policy. Provide device revocation UI.

Consequence: anyone holding that device/cookie can access the **full authenticated pilot product account**, including Finance and AI, not just Trading. This is not a hardware binding or a promise against cookie theft. Executor cannot opt in the owner's phone or obtain their production session. Owner must authenticate and select it. Parent must obtain action-time confirmation of this exact scope before auth changes; conceptual agreement to 30 days does not authorize global timeout removal.

## Next prerequisite and rollback

Parent should resolve approved read-only DEMO market source/MT5 setup and project model access before activation. No broker/account financial data goes to the model. Do not set `KILAS_TRADING_AI_ENABLED=true` until source/privacy/rate/budget and a bounded first-call plan are reviewed. USD5 is an application cap, not a new billing account or provider-wide spending cap. No VPS or other resource purchase is part of this phase.

Safe production UI verification needs the owner's existing login: open Trading, confirm MOCK/replay and UNAVAILABLE, perform a small paper entry, protection edit, close and inspect the journal. These are synthetic paper actions only; no broker connection exists.

Rollback: leave analysis unavailable/off; disable all Trading with `KILAS_TRADING_ENABLED=false` if needed, preserving additive Trader data. Redeploy the prior known live commit `c863e683c7c5d5b61b461ac9d420e50fe5eebed8` to revert this scaffold without destructive SQL. Preserve reservations/audit and inspect any pending record before future activation.
