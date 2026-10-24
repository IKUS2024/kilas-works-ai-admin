# Persistent Translator interpreter

The default Translator entry now uses one persistent Gemini 3.8 Live connection for the selected direction. Left selects Indonesian to English, right selects English to Indonesian. A tap starts continuous capture; provider VAD finishes sentences without pressing End. The opposite button stops microphone/playback immediately and waits for the old server End acknowledgement before a fresh fixed-direction setup. Double taps and late old callbacks cannot admit another session or play old audio.

The isolated server and browser adapters derive from the working AI Call lifecycle: bounded PCM queues, idempotent chunk acknowledgements, cursor polling, three-second cached authorization with one-second watchdog, provider checkpoint recovery without replay of uncertain PCM, and immediate explicit End. Existing Call implementation, settings, prompts, funding and state are unchanged. The adapter has strict interpreter-only instructions, no search/tools, separate original/translated captions and stock Kore audio. Prompt instructions reduce unwanted answering but are not a formal guarantee of model behavior.

Only Indonesian and English are offered in this initial interpreter surface. Classic Translator and its private voice/history paths remain available; the previous native pipeline remains at `/kilas-translator/live/gemini`. No claim is made that all classic languages or cloned voices work in this native interpreter.

Translator funding remains in its existing approved lifetime ledger. Each persistent envelope reserves the existing minimum and retains uncertain charges; renewal requires fresh capacity before time/input/output/turn limits. No AI Call account funding or exemption is used. Typed expired Translator records stop blocking admission without reducing their retained charges. No historical records, financial flags or credentials are changed.

Validation: actual authenticated Flask page/readiness/session/chunk/End routes, owner/member isolation, CSRF, prompt/settings rejection, duplicate PCM, captions/audio before End, multiple provider turns, checkpoint recovery, retained renewal and expiry; browser lifecycle regression; five real Chromium viewport tests using synthetic provider PCM through the shipped player/capture/session and rendered page. Browser tests verify nonzero 24kHz playback scheduled before End, both fixed directions, blocked double taps, serialized switching and stopped mic tracks. Existing AI Call and legacy pair-route regressions run separately.

No paid provider test is performed for this release. Physical Android microphone/speaker behavior and actual translation correctness/latency for this interpreter are not verified by mocked provider events. Provider protocol is checked against the current official Gemini 3.8 Live and session-management docs. Deployment and CI status must be reported from their terminal tool outcomes, not inferred from this document.

## Language setup refinement

The user confirmed PR149 works on their device. The speech engine remains unchanged. The setup page now selects A/B before Start; Start opens the prior blue-orb active surface without opening audio capture or a provider socket. The two speaker buttons then select A→B and B→A. End returns to setup with the language pair retained.

The catalog contains 99 distinct languages from the current official Live API capabilities table: https://ai.google.dev/gemini-api/docs/live-api/capabilities#supported-languages (checked 2026-10-24). Norwegian `nb` is an alias, not a separate entry. This table is more current than the initial 97-language launch announcement. These are documented options, not a claim that all pairs were physically tested or have equal translation quality. No additional provider tests or budget changes accompany this UI release.

## Minimal controls and visible admission failures

Removed the visible volume control, original/translated transcript sections and stock-voice explanatory copy at the user's request. Audio transport and stock voice configuration are unchanged. Start now reports missing consent or identical language choices instead of staying silently disabled. A rejected speaking attempt shows its concise status beside the orb and leaves configuration/End usable. No funding is added or borrowed.

Five viewport browser cases cover available and exhausted readiness, both direction buttons, serialized switching, no admission/microphone on exhausted funding, End and retained language choices. The attached MP4 was identified through Library metadata but had no directly readable content; no visual inspection of the recording is claimed.

### Active-screen lifecycle correction

The PR151 UI called the full End/navigation handler on every hidden-tab event. A browser regression reproduces the active screen returning to setup immediately after a synthetic visibility change, even before paid admission. Background/pagehide now stops capture, playback and pending admission without resetting the chosen pair or active screen; returning never auto-resumes a provider session. Only explicit End returns to setup. Active errors render once beside the orb instead of repeating below End. No transport, funding or eligibility changes.

The new screenshot's Library extraction reports the active orb, directional controls and duplicated allowance error. Pixel materialization failed (`download failed`); this is not direct visual inspection of the user's image. Local Chromium rendering and the visibility regression were inspected/tested at five viewports. Exhausted-budget attempts still make no admission or microphone request. No paid calls were made; the cumulative $17.40 ceiling remains unchanged.
