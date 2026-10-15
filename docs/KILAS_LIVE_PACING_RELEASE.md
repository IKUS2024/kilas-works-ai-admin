# Live Translator pacing adjustment

2026-10-15, following incremental translation release `a37ba701dd0f629530ded0ef8ca823404c2e576a`.
Owner reports rushed/robotic delivery and authorizes scoped deployment without
paid QA. The concrete adjustment is Live Translator request-local TTS speed
**1.0 → 0.93**; saved voices, Voice Over/upload behavior and model are unchanged.

Inspection found complete translated text passed verbatim to one whole TTS
request, with idiomatic sentence/question punctuation requested in translation,
no blanket SSML/audio tags, automatic text normalization and no forced browser
playbackRate/detune. Reconciliation keeps full final text. The v2 endpoint does
not support a language_code override, so adding one would not establish better
language/prosody control. No text rewrite, name/number substitution or inserted
pause is justified without inspecting/listening to the utterance.

Official provider documentation describes speed below 1.0 as slower delivery,
supports the speed control on TTS requests and says request voice_settings
override stored settings only for that request. Its pace guidance identifies
voice-reference pacing as another possible influence. These support a modest
0.93 pacing change for the reported rushed delivery; they do not diagnose or
prove a cure for robotic sound.

- [Provider pace guidance](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices)
- [Request-local settings and v2 language limitation](https://elevenlabs.io/docs/api-reference/text-to-speech/stream)
- [Voice-setting effects](https://elevenlabs.io/docs/api-reference/voices/settings/get)

Retain `eleven_multilingual_v2`, the same selected Kilas Male/Female provider
voice, stability 0.4, similarity 0.75, style 0, speaker boost false, normalization
auto and MP3 44.1k/128kbps. Raising stability can increase monotony; changing
style/boost adds computation, and arbitrary variation is not an evidence-based
repair. No reference re-cloning, model/voice switch, speed-up, normalizer bypass
or deprecated streaming optimization is introduced.

Slower output may last longer and delay the next listening phase. It does not
shorten post-speech translation/TTS processing. Existing generous audio duration
reservation ceilings, real MP3 measurement, actual-seconds debit, provider credit
checks, quota and cancellation remain unchanged. No extra TTS request or automatic
regeneration is added. Live outputs remain session RAM only. The older Live
compatibility fallback through ordinary audio_service is not rerouted to another
provider/model; the normal modern whole-TTS path uses this Live-only setting.

Offline verification extends existing whole-output tests to assert 0.93 for both
selected voices/directions, exact preservation of punctuation/numbers/repetition,
one complete MP3, measured billing, unchanged saved voices and unchanged ordinary
and personal Voice Over request payloads. Existing whole/segments/incremental,
core audio and session-retention regressions are run with external networking
blocked; startup logs expose only the fixed `tts_speed=0.93` value for release
verification.

No paid synthesis, new microphone capture or auditory A/B was run. The prior
recording's conditional 25 words/7.4 seconds (~203 wpm) is an energy/display
estimate supplied by the parent, not a verified transcript or naturalness rating.
No actual new duration, words/minute, accent/voice similarity, subjective prosody
or Android first-audible improvement is claimed. Robotic delivery remains an
unverified listening concern; this release addresses the documented pacing
control specifically.
