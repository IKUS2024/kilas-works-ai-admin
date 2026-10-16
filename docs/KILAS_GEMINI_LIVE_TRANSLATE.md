# Isolated Gemini Live Translate candidate

This candidate is disabled by default. It does not replace `/kilas-translator/live`,
change Voice Over/voice cloning, publish history, reactivate Learning, or apply a new
schema migration. No provider inference, real microphone or paid check was used to
build it. Passing synthetic tests does not establish live latency, language quality,
acoustic echo rejection, provider entitlements or the final-tail wire contract.

## Service and secret

Use the existing **kilas-works-client-hub** Render web service
`srv-da7ti2psrm7s73dh9i2g` in workspace `tea-da34t2gu01pc73ft7uf0`.
The owner installs **GEMINI_API_KEY** there, using a key belonging to Google project
`gen-lang-client-0998895673`. Do not send the key in chat, put it in Git, or install it
on the bot service. This implementation never reads Google OAuth connector tokens,
uses ADC, exposes a permanent key to the browser, or redirects a credential-bearing
request. Authentication uses the `x-goog-api-key` socket request header.

The project ID is documentation/attribution, not an authentication credential;
there is no project-ID environment variable or claim that Tier 1 is a spend cap.
Do not enable the candidate merely because a key is present.

## Required activation policy

All values below belong to the Client Hub service. No production values were set.

| Variable | Required value/meaning |
| --- | --- |
| `GEMINI_API_KEY` | Owner-installed secret; no value included here |
| `KILAS_LIVE_GEMINI_ENABLED` | Omit/`false` for OFF; explicit `true` only for approved activation |
| `KILAS_LIVE_GEMINI_BILLING_VERIFIED` | Omit until the owner/operator has verified funding and a conservative per-lease cost envelope; then `yes` |
| `KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID` | Exactly one approved owner; no all-user rollout |
| `KILAS_LIVE_GEMINI_CAMPAIGN` | New fixed campaign identifier, 1–70 ASCII letters/digits/underscore/hyphen |
| `KILAS_LIVE_GEMINI_BUDGET_MICRO_USD` | Explicit finite total internal allowance; no default amount |
| `KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD` | Verified conservative allowance per 90-second possible dispatch; no invented price/default |
| `KILAS_LIVE_GEMINI_EXPIRES_AT` | Fixed future RFC3339 expiry, at most 31 days away; no automatic renewal |

Existing customer audio balance/exemption, `KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS`
and usage-mode bounds still apply. Native output reserves 90 seconds before
dispatch and settles validated generated PCM cumulatively once per parent job.
An End race still accounts for valid generated output; it cannot reveal/replay it.
Unknown supplier outcomes retain the full internal lease allowance. Internal
allowance reservations are **not provider invoices or guaranteed provider USD
ceilings**. Activation requires a verified conservative cost envelope, project/key
access verification and the explicitly authorized limited wire check. This turn
did not perform that paid check. Keep the flag OFF until those gates are reviewed.

## Access and behavior

After approved deployment and policy activation, the allowlisted owner can open
`/kilas-translator/live/gemini`. No existing default/navigation link is changed.
The page explicitly selects a **one-way** source/target direction, uses native
Gemini speech, discloses Google audio processing, and requires its own consent.
It does not promise automatic A↔B routing or portability of an ElevenLabs voice.
Gemini detects the source; source-language filtering still requires real-wire
verification. Reported unsupported language codes fail closed. Target-language
speech is ignored (`echoTargetLanguage:false`), which is not acoustic AEC.

Start admits an owned session; paid dispatch is lazy until voice PCM arrives.
Capture stays active while translated PCM is played. **Finish speaking** flushes
the last partial capture frame, sends `audioStreamEnd`, waits for the provider's
terminal `turnComplete`, then drains every queued output sample. A missing final
marker times out visibly; silence alone never means the tail is complete.
**End** immediately cancels capture/playback and closes only that owned stream.
Read-only recovery never terminates another legitimate session automatically.

This pilot has fixed bounds: 60 seconds input audio, 90 seconds output audio,
90 seconds total server lease, 15 seconds final drain, 8 seconds input/client
playback backlog, 4,000 characters per transcript, two native transport slots,
and four private RAM outputs with ten-minute expiry. Speaker/headset echo must be
tested on real devices before claiming simultaneous speakerphone support.

## Protocol and isolation

The fixed model is `gemini-3.5-live-translate-preview`; the server uses the v1beta
`BidiGenerateContent` WebSocket. It forwards PCM16/16k mono in 100 ms provider frames
and validates PCM16/24k mono output. Browser upload batches are bounded (first
capture frame immediately, then up to 500 ms), output is fetched by monotonic cursor
and scheduled on one AudioContext clock with a bounded prebuffer. There is no
automatic reconnect, fallback provider, input replay, TTS job per clause or media
capture on module import. Server interruptions invalidate pending audio generation.

No source/target transcript or PCM is stored in the database. Generic owned Live
session rows, the existing hidden `live_session` audio ledger and a separately
funded native campaign retain admission/accounting metadata only. The current
single-worker assumption is checked; changing worker count is not part of this
candidate. No Finance, Assist, payment or subscription configuration is changed.

## Verification and release gates

Run the `Kilas Gemini Live Offline QA` workflow on this feature branch. It includes
browser-free Node playback/session tests, real disposable SQLite native protocol
tests, original Live/Voice Over/voice-clone/history/locale/Learning regressions,
and a disposable loopback PostgreSQL ledger rehearsal. Never point it at production.

Before enabling for the owner: review the candidate/CI, confirm the user-installed
secret and policy without displaying key values, approve a finite paid fixture
and cost envelope, verify the provider setup/flush/usage behavior and selected
language direction, measure first-output and last-tail latency plus queue starvation,
then perform bilingual and Android speaker/headset checks. No latency number from
mocks is a real-time product measurement. Deployment and activation remain separate
from this code/offline task. Rollback is flag OFF, with End still available.

Official references checked 2026-10-16:

- https://ai.google.dev/gemini-api/docs/live-api/live-translate
- https://ai.google.dev/api/live
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-live-translate-preview
- https://github.com/googleapis/python-genai/blob/main/google/genai/live.py
