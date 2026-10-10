# Synthetic listening prototype — local only, 2026-10-10

## Design and scope

Optional `/kilas-ai/listening-demo`, behind existing AI owner access and absent-by-default `KILAS_LISTENING_DEMO_ENABLED`. It does not depend on enabling content projects and creates no schema or stored listening records. There is no new product navigation/menu entry. The demo route is a local harness for `_listening_panel.html`, a reusable chat-hosted panel. General chat remains unchanged.

UI: English/Indonesian source/target, explicit synthetic-demo label, consent/privacy notice, original/translated text stream, start/stop/status, optional editable clarification reply. Reply is a generic question without personal facts; it is never spoken or sent. Only fixed synthetic text pairs are implemented. This is not live ASR, live translation, YouTube integration or Chrome's built-in Live Caption.

Real capture button is disabled. The page uses a synthetic stream with fake track objects. There is no microphone, system audio, recorder, speech output, WebSocket, API key, paid inference or provider/backend transport.

The reusable future `displayCapture` adapter is disabled by default. Its enabled branch was tested only with an injected fake `mediaDevices.getDisplayMedia` function: it requires an explicit user-gesture signal, requests video plus audio and excludes system audio. Browser-source settings are subsequently checked for a tab and at least one audio track. Source hints cannot force the chooser to provide audio; runtime rejection/cleanup remains necessary. UI does not enable/call this adapter.

Lifecycle handles explicit stop, ended tracks, pagehide/disconnect, completion, denied permission, unsupported API, missing audio, wrong source, renderer errors and a picker resolving after cancellation. All tracks/timers/listeners are cleaned. Stop/error/disconnect/completion clear caption and reply DOM; no storage API is used.

## Official basis

- https://developer.chrome.com/docs/extensions/how-to/web-platform/screen-capture — getDisplayMedia shows browser source selection and can request audio+video. This prototype uses no extension APIs.
- https://support.google.com/chrome/answer/10538231?hl=en — built-in Live Caption/Translate are separate Chrome features. Their processing/privacy guarantees must not be attributed to a future Kilas provider integration.

No all-PC, microphone, phone or mobile capture claims. Mobile screenshot checks layout only.

## Tests and artifacts

`node --test client-hub/tests/test_listening_lifecycle.mjs`: **10 passed**.

```sh
PYTHONDONTWRITEBYTECODE=1 KILAS_CONTENT_BROWSER_QA_DIR=/tmp/kilas-content-qa KILAS_LISTENING_BROWSER_QA_DIR=/tmp/kilas-listening-qa /tmp/kilas-content-venv/bin/pytest -q -p no:cacheprovider client-hub/tests/test_content_projects_prototype.py client-hub/tests/test_listening_demo.py
```

**20 passed in 12.46s**, including all 18 previous content-project checks plus listening access and synthetic Chromium UI flow. Existing project browser assertion now waits for the deferred VoiceOver initializer rather than checking visibility immediately after navigation; no existing product behavior was changed.

Browser checks: consent error, disabled real capture, EN→ID captions, optional reply, stop clearing, ID→EN captions, reply off, pagehide disconnect cleanup, restart and automatic completion. At desktop 1440px/mobile 390px there is no horizontal overflow. Real getDisplayMedia/getUserMedia/MediaRecorder/speech output are hard-blocked in the browser test, with **zero calls**; external network is blocked; localStorage/sessionStorage remain empty. Lifecycle error paths use injected fake streams.

Screenshots: `/workspace/kilas-listening-qa/desktop.png`, `/workspace/kilas-listening-qa/mobile.png`. Harness uses real scoped templates/routes with a simplified base shell and synthetic fixtures, not the full production shell. Real source selection/audio capture and provider quality/latency are untested.

Python AST parse and git diff whitespace check pass. Node, temporary Python test venv, Playwright and system Chromium were available. No new application dependencies were required.

## Decisions before a real integration

1. Select streaming ASR provider/model and supported input languages, partial/final segment protocol, chunk size/audio format, endpointing and accuracy/latency targets.
2. Select translation model/provider and whether to translate final segments only or throttle partial updates; define ordering, cancellation and reconnect/deduplication. No audio or captions may be transmitted before this is authorized and disclosed.
3. Define tenant-isolated authenticated backend transport with short-lived provider access, in-memory buffering, per-user concurrency limits and end-to-end cancellation. No provider credentials in browser. Current demo has no such backend.
4. Approve explicit real-capture consent, third-party processing region/retention/deletion policy and no-recording behavior. Realtime processing is distinct from saving a recording.
5. Obtain verified ASR per-minute and translation/reply token rates; choose max session minutes, spending cap, idle/disconnect timeout and user-facing paid-start confirmation. No price estimate or provider choice has been assumed; no existing pricing/billing changed.
6. For suggested replies, approve a narrowly grounded instruction policy: user-provided facts only, uncertainty surfaced, no invented commitments; read/edit only. Synthetic demo implements a generic clarification question, not an AI reply provider.

## Boundaries and rollback

Shared content project prototype is preserved. Finance, Trading, global auth/session/CSRF, pricing/billing/provider configuration remain untouched. No production migration, push, deployment, paid job or external send. Leave/remove `KILAS_LISTENING_DEMO_ENABLED` for rollback; no data migration exists.

Deliverable incremental patch is based on the earlier content-project patch, not clean main. Apply/review the content-project patch first. Production integration and real audio testing are separate work requiring the above decisions and authorization.

## Latest UX direction: one conversation

The final user-facing flow belongs in existing AI chat, not separate menus. The extracted `_listening_panel.html` is reusable; its current standalone route is only a test harness. No new product menu entry is added. This iteration does not replace general chat or mount real recording in it.

Mapping for next bounded phase:

- Existing: AI conversations/messages and owner-scoped attachments; Translator script translation/TTS; saved personal voices with consent gates; content project metadata for source/version provenance.
- New work required: explicit microphone consent and gesture, bounded recording capture, STT provider, editable transcript message artifact, persistent owner-scoped reference to the previous recording/transcript, continuation resolution inside the same conversation, and confirmed handoff to translated-script/TTS jobs.
- Conversation references must resolve a previously authorized owner-owned recording by stable ID and provenance, without asking for another upload. That persistence is separate from the current synthetic listening panel's no-storage behavior. Define retention/deletion/consent before storing recordings.
- Optional output voice must use an explicitly chosen stock or already-consented personal voice. No automatic voice cloning, invented user facts, external sends or background paid jobs. Every paid STT/translation/TTS action needs a clear user-confirmed boundary.
- Real microphone/audio integration, personal voice changes and paid testing wait for explicit bounded test approval. This is a design mapping only, not implemented provider functionality.
