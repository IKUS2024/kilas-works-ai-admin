# Kilas Audio v4 + Dubbing v2 release

2026-10-05 ? focused release in progress.

## Scope
Only Voice Over / Suara Saya and Translator / Dubbing. No schema migration, billing/pricing change, Finance, Video, AI, navigation, or other product change. Existing unrelated working-tree edits are excluded.

## Verified production capabilities
Existing ElevenLabs account: Creator. Subscription limit 129,660 credits; initial observed usage 35. Production API returns eleven_v4 with TTS support after granting Models read on the same key. Dubbing v2 project read succeeds. No purchase, new account, or key rotation.

## Implementation
Personal voice TTS uses eleven_v4 and the server-owned saved clone ID; no alternate voice/model retry. Stability 0.5 and similarity_boost 0.75 are documented provider defaults. Curated stock voices retain their existing model. Recording guidance recommends 60-120 seconds of quiet, one-speaker, natural speech; short samples remain permitted. Existing replacement persists the old clone until new creation succeeds.

New Translator jobs POST once to /v1/dubbing/project with model_id=dubbing_v2 and a target_language. No watermark/discount option. Queued/preparing/processing states stay pending. Speaker-substitution warnings fail safely. Existing v1 submissions retain read-only compatibility.

The v2 signed FLAC output is downloaded with no API key, an HTTPS host allowlist, no redirects, and bounded size/time. MP4 source is retained in the existing source_content field until final mux; original video stream is copied, translated audio encoded to AAC, and playable/downloadable MP4 stored in the existing result field. Failed video sources and job history are preserved. Successful transient source cleanup and idempotent charging remain. Audio-only results remain MP3.

## Focused evidence
- Audio unit/provider/media/security tests: 40 PASS.
- Personal voice tests: 9 PASS.
- Personal voice browser: 320/360/390/430/768/1024/1440 PASS; microphone, consent, replacement/persistence, ID/EN generation, download, no overflow.
- Audio browser: 320/360/390/430/768/1024 PASS in the combined run; 1440 PASS after correcting the same WAV fixture. Invalid trailing-zero WAV fixture corrected to valid RIFF JUNK padding; no media time-limit change.
- Real MP4 mux, private MP4 response/download, source cleanup, v2 warnings/source preservation, signed output security, FLAC-to-MP3 and duplicate-completion tests pass.

## Production QA
Pending deployment and real v4 Indonesian/English generations using one saved clone, one short Dubbing v2 video, playback/download/history verification. New clean owner recording and subjective listening comparison still pending user input. Do not claim improved resemblance/no watermark until actual listening evidence.

## Primary references
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/eleven-v4.md
- https://elevenlabs.io/docs/api-reference/voices/settings/get-default.md
- https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/instant-voice-cloning
- https://elevenlabs.io/docs/api-reference/dubbing/create-project.md
- https://elevenlabs.io/docs/api-reference/dubbing/language-targets/list-language-targets.md
- https://elevenlabs.io/docs/overview/capabilities/dubbing
