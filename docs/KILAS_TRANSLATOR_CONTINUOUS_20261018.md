# Live Translator continuous owner admission — 2026-10-18

## Verified production cause

Read-only owner-scoped counters and failed-turn metadata correlate the reported Android 09:17 WIB pause with three persisted `rate_limit` failures from 02:16:56.401039 through 02:17:17.839462 UTC. No transcript/audio was inspected. In the preceding hour the ledger contained exactly20 Live input operations:17 completed,1 dispatched/unknown and2 cancelled before dispatch. Both the Live admission and the shared sponsored-trial admission counted all20 against a test-style hourly attempt limit. The two cancelled operations had zero charge; the unknown dispatch correctly retained its full estimate. This was an application count gate, not evidence of a supplier timeout or exhausted monetary funding.

The current three related owner monthly campaign ledgers had $1.718862 combined conservative reserved estimates against the existing shared $22 allowance. These are internal reservations, not a provider invoice. No history, reservation, money allowance, subscription, pricing or expiry was reset/increased.

## Narrow change

Only the existing explicitly funded owner in STT `owner` mode **and** Live Translator `owner` mode skips Live daily/hourly test turn counts. Trial eligibility alone does not grant the exemption. The helper is shared by batch Auto-detect and realtime input admission. A server-only Live pipeline marker is required after session validation; a client-chosen `live-*` key on another endpoint cannot opt in. Other trial members, dictation, Learning and QA Live routes retain their count limits. This release does not expand the audience or grant continuous usage to every customer.

Every utterance still requires existing readiness/owner access, customer Audio entitlement or the existing sponsorship, current provider capacity checks, shared concurrency and full conservative cost reservation under the same durable global lock. The realtime 200-second lease/utterance limits remain. A cancelled reservation is released only before dispatch; dispatched unknown/cancelled/failed exposure remains charged. A duplicate turn cannot create another lease. Monthly campaign renewal preserves previous records and applies the existing policy.

Capacity errors now distinguish internal period spending allowance, QA hourly/daily limits, pending work and busy service in Indonesian, English, Spanish and Chinese. Persisted failed-turn reads retain that reason after reconnect. An internal allowance error does not advertise buying customer Audio seconds as its remedy; existing customer balance errors retain the existing purchase URL. Resume checks the current session; it does not replenish capacity or resubmit the failed utterance.

Startup prints only the fixed admission policy (modes and booleans), permitting production verification without revealing credentials. No new flags, migrations, provider calls or financial policy changes are required.

## Targeted offline evidence

- New9 real-SQLite contracts:25 sequential turns in the same session with sponsored-trial eligibility; repeat settlement/reconnect reads/duplicate lease denial; shared trial/dictation/hourly QA denial; QA4/day; scope/allowlist; before-dispatch cancellation and full unknown exposure; fixed monetary denial before worker creation; customer zero balance denial; combined concurrency; calendar renewal preserving old spend; four UI locale translations and purchase-link distinction.
-34 Python checks passed: the new9 contracts, existing23 realtime contracts and2 owner dictation/renewal contracts. Auto-detect processing regressions also passed after adding the server-only Live marker.
-44 existing frontend engine/API contracts passed: pause/Resume, cancellation ambiguity, reconnect verification, sequential listening/playback, quota pause and no automatic regeneration.
- Logs: `/tmp/kilas-translator-continuous-tests.log`, `/tmp/kilas-translator-continuous-final.log`, `/tmp/kilas-translator-continuous-node.log`.

No paid ASR/TTS/model calls, no generated live speech, no physical Android continuous-use acceptance, no sandbox calls. Production verification is limited to exact Render revision, startup policy, read-only counters/logs and process health; public HTTP is blocked by the environment proxy. A LIVE deployment alone is not an end-to-end speech test.
