# Translator cloud checkpoint — 2026-10-16

## Current state

The latest user requirement is Gemini translation plus the **existing exact
Kilas Male/Female ElevenLabs mappings**, automatic translation in either
direction of the selected pair, and audio held until roughly 1.5 seconds of
silence. Native Gemini speech must not become this new pipeline's final output.
This supersedes the earlier instruction to retain native Gemini voice.

Production remains `6524b7117c88616ac6db84eb44cb034c47c9bc0d`, Render deployment
`dep-db8rlr7f3r2c73f65b10`. No production configuration or code was changed in
this task. The user requested a safe checkpoint so a subsequent turn can run
Ultra; the active inference cannot be switched by this checkpoint.

## Implemented locally, not released

The existing native client now has an opt-in utterance playback gate. It buffers
received PCM during speech, opens playback after 24000 silent PCM16k samples
(1.5 seconds), retains short intra-sentence pauses, and pauses/resumes the exact
remaining playback samples when new speech is detected. The native page opts in;
old engine callers retain their earlier default behavior.

Native capture optionally emits 100ms frames; legacy framing stays 200ms. Initial
voice threshold and 400ms pre-roll are retained. Silence alone does not admit a
new connection. Renewal prefers a quiet point after 45 seconds, retains the 59s
hard boundary, partitions input exactly once, and keeps accepted output across
generations and physical turns. The hard boundary still cannot prove semantic
word completeness.

The player can hold up to 90 seconds of accepted PCM for the opted-in UI. Pausing
retains unsounded samples and original ordering. Explicit End cancels promptly.
A network failure during speech observes only local silence for at most 10s;
it performs no new paid work. It drains accepted output after a local endpoint,
or ends with the already-reported error without autoplaying over ongoing speech.

A conservative local reference check recognizes near-identical delayed/scaled
playback echo; uncertain and mixed speech is retained. Browser echo cancellation
is still requested. This is not proof of acoustic echo rejection on Android.

Backend EOS drain keeps the four-second minimum but accommodates late PCM with
a 1.5s quiet wait, bounded at six seconds and the existing 90s paid lease. This
remains `tail_confirmed=false` without a qualified provider marker. Numeric
interruption/post-EOS timings were added without logging audio or text.

The native template is simplified to Translator, an orb/status and End in the
active view. Finish speaking is removed. Check session is replaced by a hidden,
contextual retry shown only after recovery fails. Consent and concise usage
disclosure appear before Start. English/Indonesian DOM tests and locale catalogs
were updated. This UI remains wired to the old native pipeline until integration
work below is implemented; it must not be presented as the requested final voice
architecture.

## Supported hybrid architecture for the next turn

The [Live Translation guide](https://ai.google.dev/gemini-api/docs/live-api/live-translate)
exposes one target per connection and no instructions. It provides translated
output transcription, but its continuous stream has no promised final utterance
marker. The [Live API contract](https://ai.google.dev/api/live) does not allow
changing setup while connected. Reusing a partial transcript as a complete
ElevenLabs script would risk losing the tail.

[Gemini 3.8 Live](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live)
supports instructions and function calls. Its response modality is AUDIO; do not
pretend a TEXT-only native response is supported. A viable integration uses a
blocking `publish_translation` function with complete source/target/text arguments.
The server validates source is in the selected pair and target is the opposite
member. A declared function and system instruction are supported by the
[official tool guide](https://ai.google.dev/gemini-api/docs/live-api/tools).

Proposed flow, **not implemented or inference-verified**:

1. Authenticate the existing account, choose only `kilas-male` or `kilas-female`,
   and resolve it through `audio_branded_voices.resolve`. Never accept provider
   IDs from the browser or substitute a stock/native voice.
2. Reserve the shared Gemini allowance before connecting. Stream PCM while the
   user speaks with explicit activity control. Send activityEnd at the 1.5s local
   endpoint. Ignore spoken instructions as translation data; the only declared
   function returns translation data and performs no external action.
3. Accept one complete validated function call only after every input sample and
   activityEnd have been sent. Reject early/duplicate/invalid/wrong-language
   results. Never forward any Gemini audio to the client. Missing function data
   is a bounded error, not an excuse for native-audio fallback or paid replay.
4. Close and settle the Gemini socket within its original 90s lease. Retain its
   conservative reserve after every possible dispatch. Gemini 3.8 is a model
   change that needs an explicit verified cost envelope; do not relabel the
   existing immutable 3.5 campaign policy. A derived `gml-*` campaign must still
   count **all** historical `gml-*` charges under the same global admission lock,
   same USD10 cap and same per-user operation fence.
5. Before the sole ElevenLabs POST, recheck End/account state, resolve the exact
   voice again, retain existing Creator/no-extension/no-overage checks, reserve
   customer seconds, and atomically reserve an explicit shared lifetime TTS
   character allowance. Preserve failed/unknown possible-paid dispatches.
6. Use the existing complete-script ElevenLabs streaming adapter and existing
   model/voice settings, once. Settle measured complete output even if End wins
   publication, while keeping a cancelled result private. Decode complete audio
   locally for the gated player; do not publish a partial encoder prefix.
7. Keep microphone/capture alive and queue subsequent complete utterances with
   explicit boundaries and ordering. Do not flatten two queued utterances of
   opposite languages into one translation turn. Bound queued PCM and surface
   overload instead of silently dropping or replaying speech.

## Activation and billing boundary

Hybrid code/routes/feature flag are **not yet implemented**. The next turn may
implement them within existing authorization. If incremental costs are not
bounded, the user explicitly requires the new integration to remain default OFF.
The existing working service must remain available without forcing active End.

The [current Google price table](https://ai.google.dev/gemini-api/docs/pricing)
lists3.8 Live audio input, text output and any generated audio separately.
The new model's bounded envelope must be reviewed before activation. This does
not authorize increasing or resetting the shared USD10/Rp500,000 allowance.

ElevenLabs adds existing-account TTS consumption. `require_subscription_credit`
checks Creator active, positive remaining credit, no extension and no overage;
it does not atomically reserve a finite shared amount for this new integration.
The existing per-account free-test exemption is also not such a global cap.
An explicit finite overall TTS character/credit allowance, its attribution to
existing prepaid credit, and a dispatch marker need to be made concrete before
enabling. No default amount or new purchase is authorized. Reuse of an existing
key does not establish budget approval. No new keys, top-ups or supplier billing
changes are needed for offline implementation.

## Evidence and limits

Read-only metadata since the last release shows three native operations: one
32s input/32.75s output bounded drain without a terminal marker, and two
`turn_cancelled` results. The trigger of each cancellation and the exact audible
cut are unconfirmed. Ledger at 06:35:29 UTC: USD 1.15 retained across all campaigns,
zero unsettled, leaving USD 8.85 under the shared cap. No paid automated calls
were made in this task.

Local validation: 16 Python suites passed; 234 Node tests passed, including 10 new
utterance/playback/echo/renewal/failure/PCM regressions. Ruff E9/F and diff checks
passed. Actual microphone/speaker acoustics, translation semantics, clone
similarity, first audible latency and both-direction provider behavior remain
unverified. No browser tests, new microphone capture, provider inference,
credentials, account grants or production mutation were used for verification.
