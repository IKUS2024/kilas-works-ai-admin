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

## Production checkpoint ? 2026-10-05 12:47 UTC
- Initial audio code SHA: d2db89ef4ff26f3ef31511e133ee0bedad5a7842. Commit: Upgrade personal voice to Eleven v4 and Translator to Dubbing v2.
- Client Hub deploy dep-db1pki49v7es738lqh70 is LIVE on that SHA. Only Client Hub deployed; no migration or data reset.
- Audio CI run 37310921955: focused, browser, PostgreSQL all SUCCESS.
- Real production Indonesian job 10: completed; MP3 playback/download/refresh pass (5.44 seconds).
- Real production English job 11: completed; MP3 playback/download/refresh pass (4.16 seconds).
- Read-only PostgreSQL verification: both jobs use the same actual owner-saved personal voice. Private identifiers never displayed. No fallback exists in the v4 request path. Provider history-read is not authorized (401); no permission expansion was made for it.
- Real production Translator job 12: provider metadata confirms dubbing_v2, ready project and no speaker-substitution warnings. Target English result completed; MP4 playback/download/history/reopen/refresh PASS (6.76 seconds). Source Indonesian was explicitly selected.
- Actual output MP4 has exactly the same 169 decoded video-frame hashes as the source, confirming no added visible watermark or visual alteration. Audible watermark absence and subjective speaker similarity still require owner listening feedback. Creator paid no-watermark path used; no watermark removal/filtering.
- Production widths 320/360/390/430 PASS on completed voice and MP4 results; no overflow.
- ElevenLabs observed usage 35 -> 1153 = 1118 credits for these controlled generations. Internal QA account Audio balance charge is exempt (zero); provider usage is real, not a free fallback. Exactly two voice jobs and one dubbing project were submitted; read-only polling/reopens create no new paid jobs.
- Render error-level logs after deployment/QA: no matching errors.
- Automatic unrelated Autonomous Agent CI browser job failed in test_kilas_ai_unified_browser.py. Its product files are untouched; scoped Audio CI is entirely green. No out-of-scope fix made.
- Owner clean re-record is pending; existing saved clone is preserved. Three production result tabs (jobs 10,11,12) opened for owner listening. Final subjective similarity/improvement and audible-watermark assessment remain UNVERIFIED. Do not call task fully complete until this feedback and any needed clean recording QA are done.
- Verification artifacts: temporary kilas-audio-v4-v2-production/report.json, id.mp3, en.mp3, safe-speech.mp4, dubbed.mp4 and mobile screenshots; no secrets or private IDs in report.

Final scoped visual inspection found obsolete MP3-only Translator explanatory copy. Corrected it to distinguish video MP4 from audio MP3; the focused MP4 route/persistence regression test passes again. No extra paid generation is needed. Final copy-only Client Hub deployment pending.
