# Translator Start / Stop recording — 2026-10-20

Base main: `2bb08a35f3155e538f59c5a4e9ccec2ce423b200`, pulled with fast-forward from a clean Translator checkout. All newer sandbox/PDF/PPT/runtime changes and the Safari/backpressure releases remain in ancestry. This change touches only Translator frontend/control tests and this report. No backend admission, billing, package, quota, language/model/provider registry, schema, credentials, Finance or sandbox implementation/configuration changed.

## Result

After language/voice selection and the existing consent, the initial **Start** begins session preparation and records automatically once admission and microphone readiness succeed. No second Start or held pointer is required. The recording control reads **Stop** while opening/listening. A single Stop finalizes the current recording and immediately invokes the existing upload/final commit → translation → audio pipeline. After processing/playback it returns to **Start** for the next turn in either selected direction. The separate red **End** ends the logical session; its existing control/action remains intact.

The manual recording pipeline retains its existing internal `pushToTalk`/hold-v1 wire settings: that flag controls explicit turn finalization and whole-output accounting, not the new click interaction. It is deliberately not renamed or used to change provider dispatch. There is no new process button or silence-triggered auto-submit.

## Narrow lifecycle changes

- A native click binder handles mouse, touch, Space and Enter; pointer/key release no longer finalizes speech. Rapid repeated clicks/double-clicks and held-key repeats cannot produce duplicate starts or commits. Processing, playback/replay and paused states reject recording actions. Existing blur/pagehide/hidden cancellation remains safe.
- Initial Start asks for microphone permission synchronously in its user gesture, alongside the existing synchronous audio activation. A bounded, owned permission slot passes the same stream to the selected realtime/batch adapter after authoritative session admission. It does not start a recorder, worklet or paid provider before admission.
- Permission denial, admission failure, Stop while opening, End and hidden/pagehide clean up unconsumed or late permission streams. Later recording starts use the existing synchronous gesture capture directly. No capture/provider retry or alternate paid transport is introduced.
- A cancelled initial microphone startup now leaves intentional Stop at ready rather than turning it into a paused error. A real permission/runtime error still follows the existing actionable recovery path. Recovery clears the click debounce so a fresh Start immediately after Resume is accepted.
- Existing Safari gesture-primed reusable media, stored-byte replay without regeneration, early text, progressive audio, microphone/output exclusion, technical renewal, bounded coalesced upload and cost/tenant fences are preserved. Initial permission/recording is independent of selected language or account identity; all entitled accounts use the same existing backend admission.
- Versioned JS/CSS references use `record-toggle-20261020`. The template declares `data-recording-control="toggle-v1"`; the entry module imports the new toggle module and no longer imports the hold binder. The existing button ID/style/layout is retained, with native tap touch-action.

## Validation

- **219 focused Node tests passed**, including 10 added toggle/initial-permission cases: synchronous permission request and single adoption, double-click/repeat/busy-state fencing, Stop during unresolved permission, granted/late/denied/expired streams, End during admission, four alternating turns and exactly one submit per Stop. Prior engine, startup, gesture, playback, stored replay and upload-backpressure cases remain.
- **48 focused Python tests passed** for existing realtime/continuation/handoff/progressive/early-text/language contracts. All paid transports are mocked; no provider call or quota reset was performed.
- Browser coverage retains the previous four alternating-direction turns at 320/390/768/1440 widths, byte-identical cached replay, renewal, late permission cleanup, explicit Safari per-element permission policy, output denial→Resume, priming fallback, separate batch/realtime mic denial, real Chromium MP3/MSE/WebAudio decoders, Stop during progressive output, starvation and visibility recovery.
- Three new browser cases assert the initial Start records without another click; outside pointer release does not submit; actual double-clicks cannot duplicate two opposite-direction turns; permission requests occur in click gestures; Start/Stop/End labels and disabled processing are consistent; silent realtime/batch Stop closes all microphone tracks without provider dispatch.
- Seven progressive/backpressure browser regressions passed. They include the 18-second English→Indonesian turn under 1,500 ms HTTP delay after Replay/idle/Resume, exact byte forwarding and one generation per turn, batch capability renewal and unchanged unity output levels. Final UI confirmation passed10 tests (four-direction/late-permission2, Safari policy5, new toggle3); combined with the seven regressions this is **17 passing Chromium browser tests**. Exact deployment is recorded in the release handoff.

All browser microphone/provider boundaries are synthetic. This is actual local Chromium/Flask behavior, not physical iPad/Android acoustic verification or certification of real-provider latency. Existing real-provider 1–2-second acceptance remains unverified; this task does not claim a new latency result. No paid provider tests were run.

## Production asset verification limit

A read-only GET for the production entry asset from this executor was blocked before reaching the application: `curl https://app.kilasworks.id/static/kilas_live_translator.mjs` returned `CONNECT tunnel failed, response403` / HTTP000. No retry through another route or permission bypass was attempted. Local app/browser requests verify the versioned entry/new toggle module return200 and execute the new control. Render's exact deployed commit/build/LIVE/startup are verified separately. If production HTTP remains blocked, served production asset bytes/authenticated runtime UI must be reported unverified rather than equated with source/build verification.
