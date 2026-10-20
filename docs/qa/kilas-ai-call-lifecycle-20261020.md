# AI Call lifecycle repair — local release candidate, 2026-10-20

## Scope and baseline

Fetched `origin/main` at investigation start and again after verification:
`ab6f8514e8da53da4f65a3da51faaf2f0eb00182`. Local branch:
`fix/ai-call-lifecycle-20261020`. It includes Finance's ten English defaults,
two-bar picker and legacy-seed correction, and Translator's measured ID/EN
reasoning setting/v4. No push, PR, merge, deployment, environment mutation,
credential/access creation, production data write or paid provider call occurred.

Runtime changes are confined to Call capture, Call session, and Call-only asset
cache versions. No shared adapter, provider/model/voice/setup, billing, quota,
search, Finance, Translator or Voice Over implementation changed. The separate
Chat/Search task has no overlapping runtime path in this patch.

## Flow inspected

1. AI Chat/agent chat includes `_ai_call_button.html` and `_ai_call_surface.html`.
   A deliberate Start AI call click opens the existing dialog and resumes Web
   Audio inside that gesture. Importing the modules starts no capture/network.
2. Free `/kilas-ai/call/readiness` precedes microphone permission and first valid
   AudioWorklet PCM frame. Only then does POST `/call/<owned nonce>` reserve a
   Call and start its provider worker. Permission/capability failures admit none.
3. CallCapture uses the existing mono16k PCM encoder (44.1/48k device resampling),
   continuously including quiet speech/silence. CallInput preserves byte order,
   upload indexes and a bounded backlog; neither uncertain uploads nor admissions
   are automatically replayed.
4. Authenticated Call routes enforce CSRF and ownership. Call workers enforce
   renewable funding, revocation leases, input/output buffers and retained cost.
   Snapshots carry ordered audio/text/source/reset/turn-complete frames. CallPlayer
   uses the existing Call jitter buffer and PCM24k playback.
5. Speaking lasts until actual playback drain plus the existing 300ms echo tail.
   The existing user-first, NO_INTERRUPTION policy suppresses mic speech during
   playback; it is the documented deliberate 2026-10-17 rollback, and remains.
   There is no user-facing Mute button in the current Call surface. This patch
   does not introduce new call controls or change interruption behavior.
6. End, Escape, hidden/pagehide, audio/capture errors abort local IO and send
   owned cancellation. The existing durable End-before-Start tombstone, account
   settlement, no-replay network failure policy, and resumable provider handoff
   remain. Transcript captions stay ephemeral; no history persistence is added.

## Verified bugs and repairs

### Early transcript disappears on first audio (user-visible empty caption)

`CallSession.poll()` cleared the caption on the first audio frame even if the
same answer's transcription had already arrived. Synthetic streams
`text -> audio -> turn_complete` and `answer 1 complete -> text 2 -> audio 2`
both failed before the patch: the final caption was the empty string.

The session now tracks whether a caption is awaiting its answer's audio, as it
already does for sources. It preserves that caption across polling boundaries,
and clears the marker on reset, turn completion, End and fresh Start. Tests also
ensure a text-only prior answer cannot leak its caption onto the next audio.

The provider permits this ordering: output transcription is sent near the audio
without a guaranteed exact ordering relative to model output. See the official
[Gemini Live server-content contract](https://ai.google.dev/api/live#BidiGenerateContentServerContent).
No change to provider setup or generation limits was needed.

### Capture can silently stop after startup while the session keeps running

CallCapture bounded permission, module loading and the first frame, but installed
no runtime frame watchdog. After a successful first frame, a capture pipeline
that stopped delivering while still reporting a live track/running context could
leave the UI polling indefinitely. Polling refreshes the backend heartbeat, so
ordinary network liveness does not terminate this lost-input state.

A Call-only 5-second missing-frame watchdog now fails closed, stops tracks and
lets the existing session error path abort uploads/playback and end the owned
Call. Every valid frame, including zero-valued silence, refreshes the watchdog.
This is not a speech loudness gate or a call-duration cap. Cancel removes it;
stale callbacks after End cannot terminate a new session or trigger a retry.

Before the patch, the regression failed because there was no runtime watchdog.
Afterward, native Chromium with a deliberately stalled worklet-delivery callback
showed ended UI, all media tracks stopped, owned End sent, and no later upload
or automatic replacement admission. The existing server remains the authority
for settlement; this patch does not claim to refund an already-dispatched lease.

Call-only imports and the enclosing script URL use `call-lifecycle-20261020` so
existing browsers can fetch the repaired modules on release.

## Validation

All external AI transport was mocked; Python tests use the repository's network-
blocking offline runner and disposable databases. Browser requests were limited
to a loopback server with injected Call HTTP responses. No key or real account
was needed. Evidence counters are in the adjacent JSON.

- Before-fix targeted frontend run: 26 passed / 3 failed. The three new failing
  cases were first-answer early caption, next-answer early caption, lost frames.
- After-fix lifecycle/capture/player: **46/46 passed**, including ten new tests.
- Combined Call frontend/DOM and relevant Translator API/engine/Safari-policy
  checks: **117/117 passed**. The original four-locale rendered-page fixtures
  exercise explicit Start, modal/focus, background cleanup and admission denial.
- Original Chromium synthetic user-first browser: passed with actual Web Audio,
  worklet capture/playback/drain, preserved captured bytes and next-question mic;
  zero automatic-opening requests, zero post-End uploads and zero page errors.
- New native Chromium Call UI browser: four scenarios passed. Normal caption-
  before-audio, End/Start and capture loss; denied permission; missing worklet;
  missing dialog. The latter three had zero provider admissions. This is mobile-
  viewport Chromium, not a physical Android/iOS or WebKit certification.
- Python Call collection: **11/12 files passed**. The existing default-off
  `test_kilas_ai_call_search_smoke.py` has two failures and one error both here
  and on a clean `ab6f8514` checkout. Current setup serializes to 8237 bytes,
  exceeding that historical once-only smoke's 8192-byte fence (`setup_changed`).
  The spending fence was not loosened and the old paid smoke was not armed.
- Preservation checks passed: `test_finance_legacy_seed_provenance.py`,
  `test_kilas_translator_measured_effort.py`,
  `test_kilas_live_translator_whole.py`, and `test_kilas_audio.py`.
- Broader Translator frontend: 254/266 passed; the same **12 named failures**
  reproduce on clean main. These untouched timing/layout/admission/continuity
  assertions are recorded separately; no Translator implementation/test changed.
- Broad Call Python lint reports three existing unused-symbol issues in historical
  smoke files; clean main reports the identical three. Changed JS/browser files
  pass syntax checks; `git diff --check` passes.

Useful commands (dependencies installed only into `/tmp`):

```sh
PYTHONDONTWRITEBYTECODE=1 KILAS_AI_CALL_UI_FIXTURE_PATH=/tmp/kilas-ai-call-ui.json /tmp/kilas-call-venv/bin/python -B scripts/run_offline_tests.py --only test_kilas_ai_call
KILAS_AI_CALL_UI_FIXTURE_PATH=/tmp/kilas-ai-call-ui.json KILAS_UI_DOM_TOOLS=/tmp/kilas-call-dom node --test client-hub/tests/test_kilas_ai_call*.mjs client-hub/tests/test_kilas_live_translator_api.mjs client-hub/tests/test_kilas_live_translator_engine.mjs client-hub/tests/test_kilas_live_translator_safari.mjs
NODE_PATH=/tmp/kilas-call-dom/node_modules KILAS_AI_CALL_UI_FIXTURE_PATH=/tmp/kilas-ai-call-ui.json node client-hub/tests/kilas_ai_call_lifecycle_browser.mjs
NODE_PATH=/tmp/kilas-call-dom/node_modules node client-hub/tests/kilas_ai_call_user_first_browser.mjs
```

The venv used Client Hub requirements plus pytest/ruff/playwright. The temporary
Node prefix used jsdom 26.1.0 and playwright; Chromium was `/usr/bin/chromium`.
`KILAS_CHROMIUM` can select another existing Chromium executable for the new test.
No project dependency or lockfile changed.

## Production evidence and remaining limits

- Render `list_services` returned `INVALID_ARGUMENT: no workspace selected`.
  Production log lookup is **pending workspace confirmation/selection**, not a
  completed empty-log check. No workspace was guessed or new access created.
- Read-only HTTP GETs for production `/healthz` and the two public Call assets
  were **denied by the execution proxy** (`Tunnel connection failed: 403 Forbidden`).
  No production release/SHA or runtime symptom is claimed verified by those GETs.
- Physical Safari/iOS and Android permission prompts, audio routing, interruptions
  and hardware latency remain unverified. Missing-feature and denied-permission
  behavior are covered by mocks/native Chromium. A running pipeline that delivers
  all-zero PCM is still valid silence and intentionally does not time out.
- Real-provider response quality, missing/truncated model audio and live search
  reliability require separately budgeted evidence. Model/output cap and existing
  no-retry protections were not changed speculatively. The two local reproductions
  establish real code defects, not attribution of every production complaint.

## Minimal release and rollback plan

1. Parent reviews this local patch and fresh main, preserving concurrent Chat/Search
   work and the Finance/Translator commits. Baseline-only QA failures must remain
   explicit; this is not an all-repository green claim.
2. Obtain AI-Call-specific production authorization before push/merge/deployment.
   Existing Finance/Translator deployment permission is not reused. No migration,
   configuration, provider/model, credential or resource change is needed.
3. After approval, release only through the existing Client Hub service, verify
   the exact SHA and versioned Call assets, then read non-content Call diagnostics.
   A model-connected acceptance call needs its own explicit credit/budget approval.
   Physical device permission/playback/End checks remain a separately stated gate.
4. Roll back only this Call commit if needed. Do not reset main or redeploy a tree
   that discards subsequent Finance/Translator/Chat changes. There is no data or
   schema rollback and no reason to change billing records.
