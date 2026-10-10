# Bounded recording/upload to editable transcript — 2026-10-10

## Production project activation completed first

Owner explicitly approved the existing CLIENT_OWNER audience. Render service `srv-da7ti2psrm7s73dh9i2g` (`kilas-works-client-hub`, repository IKUS2024/kilas-works-ai-admin, main, client-hub root) received a **merge**, not replacement, of exactly three environment keys:

```
KILAS_CONTENT_PROJECTS_ENABLED=true
KILAS_CHAT_CONTENT_DEMO_ENABLED=false
KILAS_LISTENING_DEMO_ENABLED=false
```

Render acknowledged the update and automatically triggered `dep-db4t9ll9fdbs73ar2lm0` on `ba98005d55731888a990402787973054c3f7c095`; LIVE at **2026-10-10T06:02:52.124572Z**. New worker booted at 06:02:46 UTC. No error-level logs through the inspected 06:03:22 UTC window. Read-only Render Postgres query verified project/script/link/release tables and release marker `kilas_content_projects_and_chat_v1` checksum `e1462beebb19a99770bbff78a3eab383a3d036406b174ce1d73ca77fcf4196a2`, exactly matching committed PostgreSQL SQL. No customer rows were fetched. No rollback was needed. Production browser/HTTP access remains untested; denied access was not bypassed. Available tools do not provide an independent environment-value getter; update acknowledgement, the new deployment and migration evidence establish the applied activation.

## New feature remains disabled and paid transport remains locked

New code flag `KILAS_CHAT_TRANSCRIPTION_ENABLED` defaults off and was **not** set in production. It additionally requires existing AI, Automation and Content Project access gates. When off it renders no audio controls, reads no transcription table and runs no new migration. When enabled, an independent checksum-guarded additive migration creates only `kilas_chat_transcriptions`; existing release SQL/checksums are unchanged.

`transcription_provider.budget_ready()` returns **False**, with no environment bypass. Thus setting the feature flag or possessing an OpenAI key cannot submit paid STT or request a microphone through the UI. All working-path tests replace both readiness and provider responses at the offline boundary. Synthetic tests are not a production model-success claim.

Verified official documentation, read-only on 2026-10-10:

- [Create transcription](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create): `POST /v1/audio/transcriptions`, verified `gpt-4o-mini-transcribe`, multipart file and JSON response. Adapter reuses existing `OPENAI_API_KEY`, fixed server-owned model, normalized WAV, 5s connect / 45s read timeout, bounded 64KiB JSON response, no redirects or automatic retries.
- [Speech to text](https://developers.openai.com/api/docs/guides/speech-to-text): documented supported input formats and provider upload limit. Application intentionally accepts a smaller validated subset: WAV, MP3, M4A/MP4, WebM and Ogg, **10MiB / 180 seconds**. Media is decoded locally with existing bounded FFmpeg/file+pipe validation into WAV before sending. No fabricated model or client-supplied model/provider/URL is accepted.

## User flow and safety behavior

Only explicit recording/upload and the Transkripsikan audio button can initiate work. Consent names OpenAI and explains transcript persistence; mic capture requires an actual user gesture and consent. Browser recording supports preview, stop, discard, permission-pending cancellation, errors, page teardown and late-stream fencing. No capture or paid provider call happened in development/QA.

Jobs are owner/conversation/project scoped and require the currently selected project at submission. Idempotent operation keys plus normalized-audio fingerprint prevent replay across retries and reject changed payloads. Owner lock makes a maximum two attempts per rolling 24h and insertion atomic across workers. This is a bounded secondary safety cap, **not customer charging or the missing STT budget policy**. Retries use the same key; fresh work requires explicit new audio selection. Completed/failed/cancelled requests are never automatically resubmitted. Cancellation tombstones prevent a late start; conditional status updates prevent a late result restoring cancelled text. After 90s an abandoned PROCESSING job becomes FAILED on status lookup without resubmission. Cancellation cannot guarantee cancellation of an already accepted provider request or its cost.

Only transcript, consent timestamp, fingerprint, status and bounded provider usage evidence persist. Raw audio is temporary/in-memory and is not stored in the database; FFmpeg temporary files are removed. Original transcript survives reload. Editing happens in a textarea; copying it to the existing project script is explicit, resets review consent and preserves the general-chat composer. The existing reviewed/CAS/immutable-revision flow performs the save; no automatic translation, TTS, clone, video generation or external send occurs. A saved edited transcript is a manual project revision, not an asserted audio/script provenance link. Local discard does not delete the server transcript or saved revisions.

## Missing budget path and smallest remaining paid QA

Existing `usage.py` recognizes CHAT/WEB/IMAGE/PDF operations and text-model rates, with no STT audio-token/duration reservation/rate/settlement policy. Existing Audio balance handles Dubbing/TTS and has no approved OpenAI STT charging mapping. Neither system was edited or treated as a substitute. Persisted provider usage evidence is **not** a settled charge.

Before live use, separately approve and implement the STT reservation/limit/cost settlement path, including uncertain provider acceptance and cancellation accounting. Then verify the existing OpenAI key's transcription permission/model access without creating credentials. The smallest paid QA approval is one short owner-provided, non-sensitive WAV (e.g. <=10s), one `gpt-4o-mini-transcribe` request, an explicit provider budget ceiling, and review/edit/save verification. No global feature activation, automatic retry, translation or TTS should be bundled with that one-call approval. At this release the hard guard must remain closed; approval alone cannot bypass it.

## QA and scope

**18 transcription tests passed**, including desktop/mobile browser, disposable PostgreSQL concurrency, and a 130-second compressed MP3 regression. The combined run before that final MP3 test passed **71 cases** (17 transcription + 54 existing content/chat/listening cases). **17 Node tests passed** (7 recorder + 10 existing listening lifecycle), and all **13 existing AI/Video/Audio regression suites exited successfully** with provider transport blocked. Offline tests cover validation, consent/CSRF, ownership/stale selection, replay/conflicts, daily bound, cancellation/late results, crash recovery, checksum/idempotency and reviewed project revisions. External browser requests and all real capture APIs are blocked; providers return non-sensitive synthetic text. Browser screenshots: `/tmp/kilas-transcription-qa/desktop.png`, `mobile.png`. CI configuration adds this suite and screenshots to existing Content Chat QA, but no new CI success is claimed until the implementation is pushed.

The implementation is handed off separately as a tested local commit/patch. It has not been pushed or deployed, so it does not delay or change the already-live project activation. The production SHA remains `ba98005d55731888a990402787973054c3f7c095`. No transcription runtime setting has been applied.

Auth/logout, Finance, Trading, credentials, permissions, billing/pricing/provider configuration are unchanged. `app.py` adds only the scoped default-off migration and transcription multipart cap. Project flag activation above is the sole production settings change.
