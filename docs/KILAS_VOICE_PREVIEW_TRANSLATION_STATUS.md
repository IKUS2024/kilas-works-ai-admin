# Voice Over private preview and script translation

2026-10-05 focused release. Baseline main/production 09d9ca4b1513020117d2686e1d905dd5d2460d6e.

Only Voice Over/Suara Saya is changed. Dubbing/Translator processing, Video, Finance, AI, Services, integrations, billing and navigation are untouched. Shared Audio files contain only Voice Over additions; existing Dubbing code remains unchanged.

A short private MP3 (up to 15 seconds) is normalized locally from the actual owner recording, before clone creation. It is stored atomically with the successful clone ID in one nullable preview_content column on kilas_audio_personal_voices (additive migration 0085). Old clones without previews remain usable with a clear missing-preview notice. Replacement failure keeps old ID and preview. Authenticated owner-only preview returns private/no-store and no private provider IDs. No raw recordings in logs; full source sample is transient.

Optional translation is OFF by default. Existing Kilas OpenAI gpt-6-luna text adapter performs a faithful translation and source-language detection. Editable preview does not call ElevenLabs. Only explicit Generate submits the edited text through the unchanged eleven_v4 personal TTS path and saved clone ID. Original script stays intact. Source and target labels use existing Audio job fields; no job schema change. UI invalidates stale previews, disables duplicate preview requests, and guards generation until translated text is ready.

Focused personal voice tests: 13 PASS, including legacy clone, private preview ownership/cache policy, failure preservation, optional translation no TTS/Dubbing, edited script generation, original text OFF and duplicate generation. Browser preview/optional translation/edited text/microphone/replacement checks PASS at 320/360/390/430/768/1024/1440; final 390 process exit 0 after scoped estimator adjustment. Owner real recording is prepared in the signed-in production browser with consent (nine seconds, short samples remain allowed); preserve that tab until deployment and successful save.

Release pending commit/push, targeted 0085 migration, Client Hub-only deploy and real production QA. Do not claim production preview/replacement/translation success until verified.

## Production QA ? 2026-10-05
Initial deployment dep-db1qkjrncjis73bv6750 LIVE on 7c80e5c9e156c0a71dee1970285eb2899bc2b19e. Targeted 0085 applied only nullable personal preview_content BYTEA; no row rewrite/reset. Existing legacy clone without preview remained usable. Owner consented real recording was saved exactly once after deployment; private original sample is playable and persists on refresh/new browser context. Initial save was rejected by expired CSRF before provider IO; refreshed form token without discarding the recording, then succeeded. No duplicate clone generation.

Production jobs 15 (Indonesian original), 16 (English original), 17 (Indonesian -> English, manually edited text) completed; all MP3 playback/download/refresh PASS. Real translated preview: Hello, today I'm in Bali. Source id, target en. Original Indonesian text remained intact; translation preview created no Audio job. Edited final text: Hello, today I am in Bali. Welcome to my journey. History shows source -> target for translated voice. Three paid TTS calls total. Mobile 320/360/390/430 PASS, no overflow, primary control >=44px.

Scoped CI focused and browser jobs PASS. PostgreSQL fixture failed because it excluded 0083/0084 bootstrap but included 0085 before its table existed. Corrected fixture to apply voice-preview migration after personal-voice migration, with BYTEA preview and failed-replacement preservation assertions. Added only 0085 to the existing Audio release helper allowlist. This is a test/release-order correction, not a production feature change. Final CI/deployment confirmation pending.
