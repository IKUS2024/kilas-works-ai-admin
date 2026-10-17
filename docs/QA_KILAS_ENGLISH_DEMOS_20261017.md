# Kilas English voice demos — 2026-10-17

Follow-up to restoration release `40545ce409e411fc0f6d4d6088525ab9a8a4bed8`. The parent browser operator completed exactly two approved ElevenLabs generations: Kilas Male job 212 (15:46:15–15:46:30 UTC) and Kilas Female job 213 (15:47:22–15:47:33 UTC). Both used `Hi, this is a sample of my voice.` (33 characters each), with script translation unchecked and no assistance. Publication made no provider calls.

Only those two outputs were materialized through read-only Render Postgres. Each query match required owner 9, the explicit job ID, COMPLETED status, voiceover mode, standard content origin, exact original script, and equality with the current corresponding saved source voice ID (male saved source 5; female source 7). Raw provider IDs, credentials and private original recordings were not retrieved. The jobs' target language is `auto`; their exact retained English script is the generation evidence. No independent speech transcription was performed.

| Alias | Job | Bytes | MP3 container duration | Browser/recorded audio duration | SHA-256 |
| --- | --- | ---: | ---: | ---: | --- |
| kilas-male | 212 | 43510 | 2.690612s | 2.64s | `8097fdcaa6fbb09d74712f71f27ab7658f3cfabd132bbe3628eabc7d67d59a27` |
| kilas-female | 213 | 41838 | 2.586122s | 2.56s | `1bcd49c3b9ea40f0a9b80222173e819d0d1f9230d8fa554b3e4b7ac99cd4dd74` |

Both files are 44.1kHz, mono, 128kbps MP3 and decode fully with ffmpeg without errors. Files live in `client-hub/kilas_ai/voice_samples/`; the server-only manifest binds the exact text, current voice identity SHA-256 and audio SHA-256. The existing alias routes and conditional preview controls require no UI/code change. Playback reads cached bytes, never inference or a private original. The three saved voices' count and full identity/name/original-preview fingerprint matched the pre-generation and pre-publication baseline.

Focused checks: two cached-route/security tests passed; actual shipped MP3s passed Chromium at 320/768/1440px (six alias/width cases), including exact response bytes, advancing playback, private/no-store headers, unchanged selected alias/script, stop/reset on voice/mode change, no JavaScript errors and no horizontal overflow. Local fixtures substitute synthetic voice identities in a temporary manifest while retaining the exact shipped MP3 bytes; production voice binding was independently checked by the restricted SQL match. All provider methods were blocked. Evidence: `/tmp/kilas-approved-samples-browser.py`, `/tmp/kilas-approved-samples-browser.log`, `/tmp/kilas-approved-samples-browser/verification.json`, `/tmp/kilas-approved-samples-unit.log`. A 320px screenshot was reviewed once.

The parent reports two provider submissions only, no retries/top-ups/voice creation. Published-rate estimate remains $0.00528 before tax for 66 characters; actual provider invoice charges are unavailable and are not claimed as measured. The final authorization allowed exactly those two generations. No additional generation is authorized by this publication checkpoint. Production authenticated preview playback and physical-device listening remain for the parent browser/user after deployment.

History cleanup was inspected only. Voice Over Recent provides open/edit/pagination but no normal job delete/archive/restore operation. The saved-voice Delete control instead calls provider DELETE and removes the saved voice/original preview, with no undo path. It is unsuitable for trial-history cleanup. No job, saved voice, original recording or production data was deleted.

Production preview routes after deployment:

- `/kilas-translator/voices/kilas-male/sample`
- `/kilas-translator/voices/kilas-female/sample`
