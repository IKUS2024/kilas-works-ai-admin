# Detect-language audio playback correction —2026-10-18

The owner confirmed that the reported Android playback failure followed selecting Detect language. Parent visually inspected the screenshot: translated text was visible, with a generic audio-load/connection error. This worker did not independently view that screenshot.

Read-only production evidence strongly correlates the issue with job218: Auto→English, Kilas Male, completed at02:08:37UTC with5251ms measured audio. Other nearby explicit-language turns also completed. No raw customer transcript or audio was fetched. Request-access logs were unavailable, so an exact request/text match is not claimed. These sessions have ended and their intentionally RAM-only audio is gone; it was not regenerated.

The defect was reproduced locally: the complete Auto turn and polling returned success, but its audio GET returned400 `invalid_language_pair`. The download route omitted the persisted voice marker when validating the selected Auto mode. This was a server validation-context bug, not evidence of a connectivity or codec failure.

The audio route now validates the persisted selected pair with its voice marker and the completed job's actual source/target direction. Owner, active session, completed turn, same-owner job and content-origin checks remain. Auto must point to its selected target; explicit mode permits only its selected language pair. Existing bytes are served; no provider lookup, generation or paid retry occurs. Missing RAM output for an otherwise authorized completed job returns410. Repeated GET/Range requests reuse the same artifact. End, ownership failure or forged direction cannot expose audio.

The player distinguishes invalid request, authentication, expired/missing artifact, nonaudio response, network fetch and decode/start failures. New messages are localized in all four UI languages. This adds no automatic download/replay loop; expired audio is reported honestly and never regenerated. Browser module versions were refreshed.

## Focused verification

- Before fix: completed Auto fixture audio GET400 reproduced. After fix: exact MP3 bytes200, repeated GET unchanged, Range206 with correct Content-Range. Foreign owner404; forged pair400; retired artifact410. One mocked synthesis per fixture, no real provider call.
-20 Python auto/whole-output/admission/ownership tests pass. Older whole/restore fixtures were aligned with the already-live v4 request and read-only model catalog; ordinary VoiceOver's v2 assertion remains.
-51 Node playback/recovery tests pass, including error classification, cancellation/late completion, context suspension, timeouts, sequential playback and explicit same-artifact refetch.
-Android-like Chromium with actual cached published v4 MP3: authenticated Auto audio GET200, real decode/playback and advancing audio clock, cancel/close cleanup, retained-artifact replay, next utterance playback and explicit audio_expired for the retired first URL. Two mocked synthesis returns; zero real provider calls. Physical Android remains untested.

Logs: /tmp/kilas-translator-auto-audio-before.log, /tmp/kilas-translator-auto-audio-after.log, /tmp/kilas-translator-auto-audio-python-final.log, /tmp/kilas-translator-auto-audio-node.log. Browser report: /tmp/kilas-translator-auto-audio-qa/verification.json. No billing, voice identity, consent, retention duration, sandbox setting or infrastructure changes. Main/deploy/LIVE and sanitized startup evidence are recorded in the release handoff. Authenticated production browser testing remains unavailable; this environment's public HTTP probe is CONNECT403 blocked.
