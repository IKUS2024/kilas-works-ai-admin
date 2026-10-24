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

### Operator-funded production admission

`KILAS_TRANSLATOR_FUNDING_MODE=operator` explicitly authorizes authenticated enabled users to use the existing server Gemini integration without the historical trial-balance check. Default `trial` preserves previous behavior; unknown values fail closed. No Google budget, credential, package, AI Call allowance or historical operation is changed. Automated provider QA stays disabled.

Prospective envelopes use the separate `operator-interpreter-v1` campaign and operator price provenance, outside the historical `gml-%` trial sum. The legacy campaign schema requires positive numeric fields; here they pin the existing per-envelope estimate ($0.25), not a cumulative cap. Readiness reports `funding=operator` and `remaining_micro_usd=null`, never fabricated supplier credit. Dispatched estimates remain UNKNOWN on End/renewal, not represented as verified invoices. Source feature enablement and operator campaign blocking remain enforced. CSRF, disabled-account checks, tenant ownership, global concurrency, logical-start rate limits, input/output bounds and End fencing remain intact.

Offline route tests admit owner/member despite exhausted trial history, retain that history byte-for-byte in inspected fields, renew and End operator envelopes, prove no trial double counting and no Call funding calls, and retain concurrency/rate/tenant/CSRF guards. Provider quota/billing JSON errors expose only sanitized categories. No live provider request is part of deployment verification.

### Locale, preferences and focused UI refinement

Removed the legacy Other languages / clone navigation from the interpreter page; legacy data/routes and Voice Over are untouched. Language labels use Intl.DisplayNames in the current application locale (English is the existing application fallback). Source/target remain Indonesian/English initially; explicit changes persist per authenticated account in browser storage, validated against the supported catalog. Consent and audio never persist. Start/End labels are translated. The orb, two direction buttons and separate setup remain, with focused responsive spacing and reduced-motion support.

Official catalog rechecked 2026-10-24: https://ai.google.dev/gemini-api/docs/live-api/capabilities#supported-languages lists 99 languages. The catalog uses the canonical Norwegian `no` rather than counting alias `nb` as a 100th language. Every advertised language is validated in both source and target prompt positions offline. This is not live acoustic verification of 99 languages.

A pending AudioContext.resume previously had no deadline and could leave both direction controls disabled indefinitely. A 3.5-second bounded failure now ends cleanup and restores controls; no automatic microphone admission follows. Browser regression simulates this suspension, reload preferences, background cleanup, serialized direction switching, repeated taps and denied readiness across five viewports. Existing transport recovery/End interruption tests remain. No paid provider QA.

Both user JPEG references were resolved through Library. Consumer-local materialization failed with `library file transfer failed: download failed` for each; pixels were unavailable. Extracted descriptions confirm setup/orb/direction/legacy link, but do not constitute visual inspection. Locally generated mobile/desktop Chromium screenshots were inspected instead.

### Full language names and Kilas identity

Applied the repository Impeccable polish/craft guidance with PRODUCT/DESIGN context. The context launcher could not create its engine cache under /home/agent; followed the documented manual-context fallback rather than claiming engine execution. Reused the genuine kilas-new-chat-logo-lossless.webp already shipped in AI Call/chat; no invented mark or new font dependency. Identity border/pulse and live status preserve connection/listening/speaking feedback, respecting reduced motion. Mobile language fields now stack at full width, directional names wrap on separate lines, typography/spacing follow the existing workspace.

The supplied third screenshot extraction shows raw tk/cy/fy/wo/yo options. Intl.DisplayNames can return the input code for unsupported locales; the previous UI accepted that as a display name. Now use fallback:none plus code rejection and per-option exception handling, retaining the canonical full catalog name when localization is unavailable. Browser fixtures explicitly emulate this behavior for all five reported codes. Prompt now requires the entire spoken content without summarizing, shortening, abbreviating or omitting details, without adding content. This instruction is not a guarantee of perfect model fidelity.

The three exact user JPEG identities resolved but supported consumer-local materialization failed with download failed. Pixel inspection was unavailable; extracted descriptions only were used. Local mobile/setup/desktop screenshots were inspected. No provider calls, credentials, funding or unrelated module changes.

### Distinct-language selection

Each native select disables the opposite selected language, both in initial HTML defaults and after browser initialization/change/swap/restore. Programmatic equal change events revert the changed selector to its last valid value, preserving the opposite choice. Stale equal saved pairs preserve the saved source and choose a deterministic different target (previous valid target, then English/Indonesian/catalog fallback), persist the repaired pair and display a short localized correction notice. Existing Start and backend equality rejection remain defense in depth.

Five Chromium viewport flows test both selector directions, disabled native option attributes, forced equal change events, swap twice, stale equal restoration and valid reload persistence, followed by existing speech lifecycle fixtures. Actual POST routes reject direct equal source/target settings before provider admission. No paid provider calls. The supplied JPEG resolved through Library but consumer-local supported download failed; only its extracted description (Indonesian/Indonesian) was available, not pixels.
