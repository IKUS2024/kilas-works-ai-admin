Translator tap-to-process — 4 November 2026

Baseline: remote main fde83545c5315eee35730f1ef4968f6f082113ca, including the live scoped image diagnostic sink fix (#198). Scope: the current Google interpreter and its own controls/security registration. No Finance implementation, schema, funding, provider/model/voice, language registry, payment, or hosting configuration changes.

Behavior:
- Tap a direction card to start listening. Tap the same card again to stop microphone tracks immediately, flush final worklet PCM, drain acknowledged uploads, and submit one ordered activityEnd. There is no hold gesture or silence-detection wait. Both directions and all existing manual language settings remain.
- Tap mode explicitly disables provider automatic VAD and sends activityStart after setup, before input. An optional strict `turn_mode: tap` setting preserves existing continuous-mode clients. Protocol reference: https://ai.google.dev/gemini-api/docs/live-api/capabilities#disable-automatic-vad .
- The new authenticated/CSRF-protected Finish endpoint verifies the final upload cursor and queues an idempotent boundary behind PCM. Finish retains output; End cancels. Invalid cursor, wrong tenant, missing CSRF and duplicate input are fenced.
- Processing ignores duplicate taps. Playback drains before the session closes and returns to ready, retaining captions. A new direction cancels the prior turn; End/backgrounding fences late callbacks. A second tap before usable microphone PCM cancels preparation without paid admission.
- A 30-second response-stall watchdog is refreshed by output frames and cleared at turn completion; it does not cut off queued playback. Uncertain Finish/provider transport is never automatically replayed or re-admitted. Manual provider disconnection asks for a new turn rather than reconstructing an uncertain activity boundary; existing continuous-mode resumption remains.
- Four UI locales explain the tap action and expose a Stop and translate accessible label. Missing/unreadable microphone, interrupted voice transport, and incomplete audio upload have actionable recovery. Source/translation captions remain literal text with their own content language, independent of App Language.

Local verification (no paid provider IO):
- Interpreter backend 17 tests PASS, including all 9,702 supported ordered language pairs, strict tap settings, ordered PCM/Finish, Finish idempotence, CSRF/tenant/member checks and preserved continuous resumption.
- Interpreter/capture/player/PCM/API Node 86 tests PASS. New tests cover repeated stop, final PCM before Finish, permission-pending cancellation, late Finish/End, bounded no-output recovery, failure without retries and another direction after error.
- Existing hardened Chromium matrix: EN/ID/ES/ZH at 360/393/768/1440 px, 16 cases PASS. Synthetic microphone and mocked relay; consent, locale/pair persistence, safe captions, auth/audio/network errors, actual contrast and mobile overflow checks retained.
- New actual Chromium → authenticated Flask → Call/PCM queue → synthetic wire tests: 320/393/768/1440 px PASS. Both directions, setup/activityStart/PCM/activityEnd ordering, ten repeated taps producing one boundary, output audio/text and stopped tracks, permission denial without admission, provider failure/retry and direction cancellation. These tests do not intercept interpreter endpoints.
- Existing interpreter Chromium tests updated for explicit Finish, including languages, swap, equal-language recovery, unavailable readiness, pagehide, audio preparation and responsive layouts.
- Preserved-product checks: UI i18n Python 14 + Node 4, Copilot 30 + dependability 11 + locale 8, Finance onboarding shell 4, Translator language/Voice Over edit 14 PASS.
- Reports/screenshots: /tmp/kilas-interpreter-hardened/verification.json and /tmp/kilas-interpreter-tap/verification.json. CI uploads both browser evidence directories.

Limits:
- Microphone input is an oscillator, provider output is synthetic. This is not proof of physical microphone capture, acoustic quality, live Gemini interpretation, iOS/Android hardware or linguistic accuracy across 99 languages.
- Original Library screenshot libfile_220c31f74ac881919c539d5af0fdccb5 could not be downloaded by this executor: current bundled materialization helper returned `download failed` on initial attempt and one supported retry. No extra route or invented URL was used. Parent independently materialized and inspected its real pixels; implementation preserves the existing two-card layout. This executor inspected its own rendered mobile pixels.
- Exact CI, merged commit, Render LIVE identity and accessible production QA are recorded in the release handoff, not certified by this pre-release document.
