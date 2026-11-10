# Kilas Adult Female

Adds `kilas-adult-female` as a third built-in Voice Over choice. Existing Kilas Male and Kilas Female identities, order, and demos stay unchanged. No personal voice is created, replaced, renamed, or deleted.

## Source and publication verification

The authenticated Voice Over UI identified the requested `wanita dewasa` saved voice as ID 10. One authorized generation created job 379 with the exact existing demo sentence, `Hi, this is a sample of my voice.` (33 characters). No retry or new clone was submitted.

A read-only production query matched all of: job 379, owner 9, saved voice 10 named `wanita dewasa`, current source voice identity, COMPLETED status, voiceover mode, standard content origin, and the exact original script. Consent was recorded for the saved source. The result's hash and byte length match the downloaded MP3. No source recording or credential was retrieved.

- Current source voice SHA-256: `9c5d950f67566059500417ab5c3c434b17088ba6b767842bdd4a9a88253f7bb2`
- Result SHA-256: `d4397702b38eb7de7515ae4d509c6f87216a44d6a4404b1024ceb6dc9e5960bd`
- Result size: 46,018 bytes.
- MP3: 44.1 kHz mono, 128 kbps, container duration 2.847347 seconds.
- Application duration: 2,800 ms; account seconds charged: zero. Provider invoice cost was not measured.
- Full ffmpeg decode succeeded without errors.

The demo is a cached immutable asset bound to both the source identity hash and audio hash. Playback has no inference/provider call. Missing or changed source identities fail closed. The request handler accepts only explicitly configured branded aliases, not arbitrary saved voices. Private/no-store and authentication checks remain intact.

## Verification

Four added regressions cover exact additive catalog binding, generation/editor alias round-trip, missing-source failure without stock fallback, and published asset/cached-route authentication, hashes, unchanged balance, and identity-change rejection. All provider generation in tests is mocked; local test execution blocks external network connections.

Deployment and production playback verification are performed by the combined release owner after integration.

Local results: 79 tests passed across `test_kilas_personal_voice`, `test_kilas_audio`, and `test_kilas_voice_edit`, run together with external networking blocked. All three shipped MP3 hashes match their manifest entries. `git diff --check` passed. The additional historical `test_kilas_ai_revisions` suite has one `test_navigation_profile_and_private_library` failure on both this candidate and pristine main `8cbbb7ee`; its other six tests pass. That baseline issue is not changed here. Live browser playback of the new catalog choice remains for the release owner after deployment.
