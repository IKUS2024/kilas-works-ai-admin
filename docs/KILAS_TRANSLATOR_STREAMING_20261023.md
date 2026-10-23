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
