# Voice Over original sample playback — 2026-10-17

Baseline: `83b8807325e2cb03abbca85aaa60036d3f23508f`, branch `call-preserve-input-tail-20261017`. Implementation and local QA only; parent execution owns commit, push and deployment.

## Changes

- Restored **Play Voice Sample** in My Voice. It streams the selected saved voice's existing original-recording preview through the retained owner-scoped API, with no provider call or balance requirement. The player appears after clicking; changing saved voice/mode, opening recording, management actions and page exit stop/reset playback. Missing historical samples leave playback unavailable without additional explanatory copy.
- Add Voice, Rename, Delete, selection, consent and generation remain intact. Replace Voice Sample remains absent. No voice identity or stored sample is updated by playback.
- Removed only the rendered WAV explanation paragraph from the completed result. MP3/WAV actions, real PCM conversion, actionable errors and consent remain intact.
- Prepared cached English Kilas Voice demos via `/kilas-translator/voices/<alias>/sample`. A server-only manifest binds the exact English text, SHA-256 of the current source voice ID, and MP3 SHA-256. Unknown aliases, missing assets, changed identities/text and corrupt assets return 404. Private originals and owner job history are never reused. No generation endpoint or automatic provider call was added.
- The committed manifest is empty. No demo control is rendered until a matching asset exists. Existing production generation language rules are unchanged.

## Verification

All external generation was mocked or blocked. Disposable local SQLite fixtures only; no production QA writes.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests /tmp/kilas-call-venv/bin/python -m unittest test_kilas_audio test_kilas_personal_voice test_kilas_voice_upload
node --test client-hub/tests/test_kilas_voice_upload.mjs
KILAS_QA_CHROMIUM=/usr/bin/chromium KILAS_QA_WIDTHS=320,360,390,768,1440 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests:/opt/codex/runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/site-packages /tmp/kilas-call-venv/bin/python client-hub/tests/test_kilas_personal_voice_browser.py
git diff --check
```

- Python: **80 passed**, including exact original preview bytes, unchanged saved rows, owner/anonymous isolation, private/no-store headers, no playback provider call, unchanged voice IDs, generation language behavior, fail-closed English assets, no-balance playback, and real WAV conversion without recharging.
- Node: **13 passed**, including playback reset, legacy missing preview, retry and stale playback rejection handling alongside existing upload/recorder cases.
- Chromium: **five widths passed** (320/360/390/768/1440), exact original bytes and advancing `currentTime`, microphone/consent/reload, ID/EN generation/download, Add/Rename/Delete and no overflow or JavaScript errors. A synthetic cached branded demo also passed exact-byte response, advancing playback, stop on mode change and zero provider calls. An earlier run also passed all seven original widths including 430 and 1024.
- Completed results rendered in Indonesian, English, Spanish and Chinese with MP3/WAV links retained and the WAV explanation absent.
- Logs: `/tmp/kilas-original-sample-full-tests.log`, `/tmp/kilas-original-sample-final-browser.log`; screenshots: `/tmp/kilas-personal-voice-browser/`.
- Chromium uses synthetic microphone/audio and mocked generation. Physical-device sound, real voice similarity and production playback remain for live verification. Local byte/row assertions establish preservation; parent execution holds production read-only fingerprints for post-release comparison.

## English demo still pending separate paid authorization

Parent read-only production inspection found no existing matching English demo for either current branded source. No paid generation was performed. The existing $2 authorization covered chat-model QA only.

- Voices: **Kilas Male** and **Kilas Female**, using their existing source identities (two requests total, no recreation/replacement).
- Exact text per voice: `Hi, this is a sample of my voice.` — **33 characters** each, **66 total**.
- [Official ElevenLabs API pricing](https://elevenlabs.io/pricing/api), checked by parent execution, lists $0.08/1,000 characters for v4 and Multilingual v2: estimated **$0.00528 total before tax**. Proposed bounded authorization: **at most $0.01 total**, two single requests, no automatic retries; account-specific minimums/taxes can differ.
- After authorization, use the existing secure server provider environment and `audio_provider.speech(SAMPLE_TEXT, branded.resolve(alias)['id'], 'en', personal=True)` once per alias (current `eleven_v4` adapter), validate MP3/duration, then publish `kilas-male.mp3` / `kilas-female.mp3` plus manifest entries containing `text`, `voice_sha256`, `audio_sha256` under `client-hub/kilas_ai/voice_samples/`. Keep raw provider IDs and credentials server-side. Local provider credentials were unavailable; no credential retrieval or new runtime generation API was attempted.
