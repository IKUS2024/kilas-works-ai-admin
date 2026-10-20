# VoiceOver alternate takes — implementation and local evidence

Source baseline: `87622dac5a644da161e27a95d9edadcd9018c3a9`. Scoped user request: a concise action on completed VoiceOver for another tone/delivery take, plus reliability. Deployment is handled separately by the parent; this record does not assert LIVE status.

Completed new VoiceOver results expose **Buat versi lain / Generate another version**, with a short normal Audio billing note. Each click creates a separate result using the exact stored spoken text, original editable script, target language, voice ID and display name. Edited current-form text, voice and language cannot change the source take. Original output remains playable/downloadable and a new result links back to its source. Existing history lists both.

## Supported provider control

Official ElevenLabs documentation retrieved by web search on 2026-10-20:
- https://elevenlabs.io/docs/overview/capabilities/text-to-speech/eleven-v4
- https://elevenlabs.io/docs/eleven-creative/playground/text-to-speech
- https://elevenlabs.io/docs/api-reference/voices/settings/update

The v4 documentation describes Stability and Similarity, lower stability allowing more expressive/varied delivery, and no Style/Speed sliders for v4. Alternate requests use `eleven_v4`, stability `0.35` (or `0.65` when the source alternate used `0.35`), similarity `0.75`. No tags, rewritten words, invented style parameter, model downgrade, or guarantee of a particular audible difference. Original initial-generation defaults remain unchanged; an alternate of an existing curated v2 take uses v4 with the same voice ID. No paid provider calls were made; acoustic variation is not empirically certified.

## Persistence and reliability

Additive migration 0110 stores bounded exact spoken text, source job ID, delivery stability and personal-voice provenance on standalone new VoiceOver jobs only. No legacy text backfill or session transcript retention. Existing old results without an exact spoken-text snapshot retain edit/download controls but do not offer the alternate action, because historical translated speech cannot be reconstructed exactly from the original editable script.

Owner/status/source checks, locked current personal-voice ownership, normal existing balance reservation/settlement and one-active-operation checks apply. Source relationship is part of alternate fingerprints; original fingerprints remain unchanged. Duplicate/concurrent operations reuse the same job and cannot repeat provider dispatch. Ambiguous browser failures retain the operation key in session storage across reload; only another explicit click retries lookup/submission with that same key. No automatic POST or generation retry. Failed results stay failed under that key.

JSON fetches, including body reads, have bounded timeouts; controls recover after errors. Status polling remains read-only. Failed audio playback offers a read-only Reload audio action. The JS asset version was bumped.

## Validation

- 7 focused backend tests: exact translated snapshot, original retention and separate downloadable output, normal charging, stability alternation, tampered/current inputs ignored, duplicate and concurrent key reuse, cross-source conflict, owner/CSRF rejection, legacy hiding, failure/poll no retry, zero balance, removed personal voice, exact supported provider payload.
- Browser mocked backend checks at 390, 768 and 1440 px: localized button, no overflow/JS errors, changed draft ignored, double-click single POST, server-accepted request with lost response followed by reload and same-key retry producing one provider dispatch, read-only audio retry. A headers-resolved/body-stalled mock verifies abort releases controls. Report: `docs/qa/voiceover-alternate-20261020/verification.json`. Screenshots: `/tmp/kilas-voice-alternate-review/alternate-{390,768,1440}.png`.
- Parent independently ran 98 existing Audio/history/video-script/personal-voice tests and 21 Translator progressive/language/contracts tests in separate processes, all passing. A combined process caused two fixture-state contract failures from shared synthetic STT reservations; separate runs passed without product changes.
- Native PostgreSQL migration fixtures now include 0110, idempotent second application, unchanged legacy fields and null new legacy metadata. No local disposable PostgreSQL was available, so native execution is not claimed.
- `node --check` and `git diff --check` pass. No Finance, Chat or Creative runtime behavior, quotas, credentials, paid calls or deployment changes.
