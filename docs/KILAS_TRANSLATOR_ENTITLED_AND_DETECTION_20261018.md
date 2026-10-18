# Production Translator audience and Auto diagnostics — 2026-10-18

## All entitled production customers

The previous release removed hourly/daily test turn counts only for the explicitly funded owner. Other existing sponsored customers still reached20/hour; normal paid nonowners also encountered the old pilot funding-audience restriction without sponsorship.

The production Live audience now accepts normal Audio-eligible `CLIENT_OWNER` customers independently of sponsorship. Existing sponsored users (including `CLIENT_MEMBER`) retain their actual dated eligibility and current persisted provider proof. Fresh auth/role checks and available customer Audio balance or existing sponsorship remain required. This does not change roles, pricing, billing, balances, trial dates, provider credentials, subscriptions or spending limits. Non-Live STT and QA audience/count restrictions remain.

Only the server Live session pipeline can skip test counts. A client-provided `live-*` operation key cannot opt another endpoint in. Batch Auto reservations retain the server marker in the typed nonce through dispatch, preventing a later owner-only audience check from rejecting a legitimately admitted paid customer. Realtime uses the same Live audience. The normal funding ledger still reserves the full maximum before dispatch under its global lock and retains unknown exposure. Reconnect/duplicate settlement cannot create another debit or provider request.

Existing global/account input caps, shared learning/input spend, concurrency, per-utterance bounds, provider capacity/verification and output Audio allowance still apply. Production currently has a **shared $22 internal ASR allowance**, with the current campaign expiring November1UTC; this is not $22 of new funding for each user, nor a provider invoice or unlimited free usage. Other normal Chat/Audio quotas are unchanged. No production usage history was reset.

## Reported Auto uncertainty

Parent inspected the Android09:33WIB screenshot. Read-only production metadata shows one owner9 `detection_uncertain` turn at02:32:52.700353UTC, correlating with the reported time/mode. Its application log shows ASR request latency649.6ms and rejection between stages, before translation/TTS. **That latency is not recording duration.** No transcript or audio was fetched; exact screenshot/request content was not matched.

Existing logs did not retain confidence presence/value or capture duration, so they cannot establish whether that historical response had missing/invalid provider metadata or genuinely low confidence. Source and known response-fixture checks show the actual Scribe JSON `language_code`/`language_probability` fields are preserved, with ISO/legacy normalization before admission. Browser batch capture waits2seconds after detected voice; a179second safety cap refuses truncated input. Those source contracts do not prove the owner's recording was complete or noise-free.

The app now distinguishes absent/invalid detection metadata (`detection_unavailable`) from genuinely low probability (`detection_uncertain`), with concise localized recovery. Missing data is never presented as measured low confidence. The **0.7 application threshold stays unchanged**; unknown language, unsupported route and same-target detection remain rejected before translation/TTS. No guessed language or automatic paid retry was added.

New failure logs record only a fixed reason, numeric/missing/invalid confidence and bounded input milliseconds. They never contain transcript/audio, raw provider bodies, language names, user/session identifiers or credentials. This provides informative evidence on a future naturally occurring failure without extra API calls. The historical recognition cause remains unproven. Recovery is to select the known source language explicitly, then speak a new utterance; the failed recording is not automatically regenerated.

## Targeted verification and limits

-42 focused Python tests passed: real SQLite budget/settlement and actual HTTP admission for25 sequential **nonowner paid** turns without sponsorship and25 **sponsored nonowner member** turns; unchanged finite sponsorship/proof expiry; zero-balance/unentitled denial; cross-account shared-funding exhaustion before worker creation; non-Live/QA limits, concurrency, replay, cancellation/unknown retention and customer entitlement.
- Included Auto processing tests validate original voice propagation, completed audio authorization/ranges, low/missing/unknown language rejection before LLM/TTS and reverse-output rejection. Synthetic provider fixtures only; admission completions are locally settled mock outcomes, not real speech generation.
-44 frontend engine/API tests passed (pause/Resume/reconnect/cancellation/no duplicate submission).
- One focused Scribe response-schema preservation test passed; one final diagnostic/localization test passed for Indonesian, English, Spanish and Chinese. No live ASR/TTS/model/VM calls.
- Evidence: `/tmp/kilas-translator-all-entitled-final.log`, `/tmp/kilas-translator-all-entitled-node.log`, `/tmp/kilas-translator-detection-schema.log` and `/tmp/kilas-translator-detection-final.log`.

Production verification uses exact Render revision, startup policy and non-generating/read-only checks. Physical Android speech recognition/continuous-use acceptance is not performed. Public HTTP remains blocked by this environment's proxy. This release fixes application access/count scope and metadata error classification; it does not claim every utterance can be recognized correctly.
