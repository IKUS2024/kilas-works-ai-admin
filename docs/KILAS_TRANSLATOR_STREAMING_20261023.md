# Translator native streaming refinement — 2026-10-23

Base: main `f86a6cefeb2403b23dc83f24ae54eb83c8406c6a` (PR128).

## Architecture and changes

The existing native path already uses two isolated Gemini Live Translate sockets,
with opposite fixed targets and `echoTargetLanguage=false`. It is independent of
AI Call. This release keeps its account ownership, consent, shared durable funding,
90-second leases, frame cursors, native language allowlist and original fallback.
The [current Google translation guide](https://ai.google.dev/gemini-api/docs/live-api/live-translate)
was checked on October 23: dedicated `gemini-3.5-live-translate-preview`, PCM16k
input / PCM24k output, 100ms input packets, captions, translation-only (no tools,
text input or system instructions). Setup now puts caption configuration inside
`generationConfig`, as the dedicated WebSocket guide specifies. It does not reuse
AI Call's conversational/roast prompts or its model/accounting configuration.

New native UI uploads every100ms instead of buffering500ms; its PCM-based phrase
pause is600ms instead of2s. Provider audio can be received during speech and played
at that short pause while the mic stays open. Start/End control the whole logical
session. No recording is uploaded at End. Legacy/cached engine callers keep their
old default timings. The dual-stream ordering and bounded post-EOS drain remain:
this is not zero-latency simultaneous interpreting, and fast alternating speakers
can still experience drain/renewal delays. A provider's missing final-word marker
still yields the existing explicit unconfirmed-tail warning.

Read reconnect retries at most twice (250/500ms backoff,2s read timeouts), preserving
the same session, operation and output cursor. No uncertain PCM/admission POST or
provider connection is replayed. Provider failures stop visibly; full provider
session resumption is **not implemented** for this translation-only model. Existing
bounded buffering, echo reference filtering, browser echo cancellation and immediate
End cancellation remain. Physical acoustic echo rejection is not certified.

The scoped white/orange UI adds swapped A/B pickers, direction-labelled original
and translated captions, volume, clear errors and cloned-voice fallback. Captions
are RAM/DOM-only, rendered via textContent, deduplicated by operation/target, bounded
to12 turns. Existing server history and private assets are unchanged. Google native
voice is explicitly not labelled as the user's saved clone. Only documented native
languages are offered; no150-language native claim. Classic remains its original
multi-stage engine and now says so visibly. Native becomes the default only when
its existing policy/readiness gates pass and no explicit provider override exists.

## Verification

- 83 native Node tests pass: early PCM before End in both selected directions,
  100ms packets,600ms pause, live microphone, echo/new speech, duplicate caption
  snapshots, literal prompt-injection markup, interruption, bounded reconnect,
  rejected protocol/direction/generation events and stop cleanup.
- 11 native Python suites pass with network blocked: provider wire, account/role
  isolation, budgets, capture, completion, two-way routing and readiness.
- Actual Chromium:320×640,390×844,768×1024,1440×900,480×300. No horizontal overflow;
  End visible, captions scrollable, swap works, state contrast verified. Native
  mobile2× pinch also keeps End inside the visual viewport and ends correctly. First
  inspection caught and fixed inherited white-on-white status text.
- Existing Chat zoom browser:57 cases pass, including pinch2×/3×,200% text,
  keyboard and history scrolling. No Chat, AI Call, Finance, Creative or Voice Over
  implementation files changed. Locale additions are Translator-only strings.
- Existing legacy suite has pre-existing failures:49-test base has2 assertions,
  8-test flow has5 assertions; both reproduced on the unmodified PR128 worktree.
  Other18 legacy non-browser suites pass. Existing Call search-smoke also fails
  on PR128;13 other Call Python suites pass. These unrelated tests were not edited.
- A dedicated native-streaming PR job preserves the existing broad QA job and
  adds isolated streaming/DOM/browser checks; PostgreSQL also runs on this PR.
- Local PostgreSQL test cannot run without an explicitly disposable loopback DB.
  Real speech semantics, injection resistance, microphone/headset quality, provider
  acceptance of the updated setup and real end-to-end latency remain untested.
- Browser installer download was denied403; preinstalled `/usr/bin/chromium` was
  used. No access restriction was bypassed. No paid provider calls were made.

Machine-readable synthetic evidence: `docs/qa/kilas-translator-native-streaming-20261023.json`.

## Production activation blocker

Read-only Render preflight: service `srv-da7ti2psrm7s73dh9i2g`, workspace
`tea-da34t2gu01pc73ft7uf0`, auto-deploy OFF, live PR128 deployment
`dep-dbdtqqss728c738gcvmg`. At22:20:30UTC startup reports
`KILAS_GEMINI_GATE enabled=false policy_valid=false qa_armed=false`.
AI Call's `configured_ready=true` independently confirms the existing Gemini key
presence, **not** access to the translation model. No secret value was read/logged.

Native Translator activation is pending a valid independently approved funding
policy. This release does not increase/reset a budget, change an audience/security
policy, set billing verification to yes, enable paid smoke tests or borrow AI Call
funding. Historical native usage must be included in any approved funding change.
The October16 release note recorded9.9USD retained against the then10USD allowance;
that is historical context, not a current balance. Code deployment alone cannot be
reported as live working native translation. Final deployment evidence is reported
in the task handoff; the runtime gate remains the source of truth.

## Activation diagnosis — 2026-10-23 23:19 UTC

PR130 deployed `69fe0524037447343b853f25a11d4999ce31ba86` as
`dep-dbdumfnf3r2c73c4bdgg` (Render LIVE 23:19:34 UTC). Passive startup evidence:

- `enabled=false`, `valid_if_enabled=true`, `billing_verified=true`, key present.
- Policy `owner_lifetime`, audience `authenticated`; no new identity/key is needed.
- Existing lifetime cap 10,000,000 microUSD ($10); retained historical allowance
  24,650,000 microUSD ($24.65); remaining zero. These are conservative ledger
  reservations, **not a claim about the supplier invoice**.
- Physical reserve 250,000 microUSD; paired Start needs 500,000 ($0.50).
- Existing internal valuation 25,000 IDR/USD, guard 250,000 IDR, total 500,000 IDR.

A feature-flag-only change cannot admit Start. Retained spend must not be reset,
refunded or hidden by renaming the campaign. Even one additional pair needs a
cumulative cap of at least 25,150,000 microUSD; the current authenticated lifetime
parser expressly caps this at 10,000,000 and its internal guard at 250,000 IDR.
Therefore activation requires an explicitly approved additional funding amount
and a reviewed funding-policy change that preserves all historical retained
liability. No such new standing allowance is implied by the separate $1 QA
approval. No funding/configuration values were changed.

## Prepared bounded QA and provider limitations

`live_gemini_smoke_10s.py` and `gemini_live_synthetic_10s/` preserve the original
complete synthetic sentences using offline tempo 1.6, silence padded to exactly
10 seconds. Tests verify hashes, PCM length, trailing silence and default OFF.
The old 15-second harness and its once-only run marker remain distinct. The new
harness is not startup-registered or armed; **zero paid tests executed**.

Official pricing checked October23: audio input $3.50/M tokens, output $21/M,
25 tokens/second. Two 10-second inputs plus two 30-second accepted outputs equal
$0.03325 at those rates, with zero source-synthesis cost. This is an accepted-audio
estimate, not a total provider ceiling. `maxOutputTokens=512` is a per-response
configuration, not a documented whole-connection limit; the continuous translator
can produce multiple outputs. Neither the received-byte cutoff nor the 45-second
timer proves a ceiling on generation already performed upstream. Under the user's
strict total $1 restriction, do not dispatch until a provider-enforced cumulative
bound is established or the user explicitly accepts this distinction. No budget,
new key, security setting or provider purchase was made to get around it.

The official resumption guide demonstrates `gemini-3.8-live`; the dedicated
3.5 translation guide does not establish compatible checkpoint/replay semantics.
Provider resumption is still unimplemented: browser read recovery preserves its
cursor only while the existing relay lives. On socket failure the session fails
visibly; there is no blind input replay, duplicate translation, hidden paid retry
or claimed cross-socket context restoration. Adding that behavior requires
confirmed translation-model handles/checkpoints and paired output deduplication;
copying AI Call state would not establish it. AI Call itself is unchanged.

Sources:
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/api/live
- https://ai.google.dev/api/generate-content#v1beta.GenerationConfig
- https://ai.google.dev/gemini-api/docs/live-api/session-management
- https://ai.google.dev/gemini-api/docs/live-api/live-translate
