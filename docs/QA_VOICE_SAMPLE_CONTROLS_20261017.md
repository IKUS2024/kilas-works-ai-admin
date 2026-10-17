# Voice Over sample controls and Translator consent copy

Scoped follow-up to main `0a80b8e5a8777190e47c0bda65770e59ce3cd95e`.

Voice Over previously rendered Play Voice Sample, Replace Voice Sample, their saved-original-sample player and fallback/error text in the saved-voice section. Removed those elements and their JavaScript listeners. Add Voice opens the existing recorder/upload flow; Cancel returns focus to Add Voice. Saved selection, Add, Rename, Delete, new-recording playback/consent, generated-result playback/download, and all server voice/media endpoints and persisted bytes remain. Removing the controls does not issue any delete or provider request. The changed script URL is versioned so existing browsers receive matching markup and JavaScript.

Translator's classic live setup now removes only the inline Privacy Policy words/link, with complete permission/processing and streaming disclosure localized in Indonesian, English, Spanish and Chinese. The policy document `/privacy` and its existing link from Terms remain. No Translator microphone, audio, model, provider, Start/End or backend authorization code changed.

## Consent finding and remaining request

The current live-session schema stores owner, languages, voice, status and timestamps, but no versioned processing-consent record. Its POST Start route explicitly requires `consent=yes`; the browser's required checkbox supplies that value after user interaction. The policy link was never a condition of Start. Saved voice `consent_at` records relate to cloning and cannot establish consent for current speakers' microphone audio. Generic login, ownership of output voices, or an owner's statement about another speaker is not substituted for processing authorization.

The latest request to remove recurring checkbox interaction is not completed by this UI-only release. The smallest proposed extension is a clear first-use **Allow and start** action before microphone transmission, storing an authenticated, owner-scoped processing-scope/version/timestamp record. Later Start requests would be authorized from the current record, with renewed consent when processing scope/version changes and a way to withdraw it. This needs a separate consent workflow and additive persistence, not a hard-coded flag or hidden prechecked checkbox. No consent record or schema was fabricated here.

Checked current official provider terms on 2026-10-17: [ElevenLabs terms, section 4(g)](https://elevenlabs.io/terms-of-use) require necessary rights to submitted content; [OpenAI Services Agreement, sections 3.2 and 4.3](https://openai.com/policies/services-agreement/) cover necessary end-user consents and input permissions. Neither inspected section prescribes this exact checkbox or placement of an inline policy link. These findings support preserving genuine authorization; they do not establish a jurisdiction-specific legal conclusion.

## Focused validation

- 27 Python tests pass: existing personal-voice/upload lifecycle, private original media preservation, saved selection/generation, add/rename/delete, owner/CSRF boundaries, failure/idempotency, and the live Start consent gate. One older upload test changed a session user ID without establishing that user's authenticated session; it now uses the existing authentication helper so it exercises the intended ownership denial rather than auth redirection.
- 11 Node upload/controller tests pass with the removed DOM nodes absent, including cancellation, stale inspection/microphone callbacks, explicit cloning consent, idempotent failed Add Voice preserving the selected existing voice, and no replacement ID submitted.
- Local actual Chromium classic Translator setup checks pass at 360/1440 pixels across all four locales: checkbox initially unchecked/required; unchecked Start admits no session or microphone; explicit check permits Start and End with no policy request or popup. Media and admission are synthetic; no paid IO.
- Existing real Chromium Voice Over checks use a fake microphone and synthetic providers, preserving recording review, consent, saved selection, add/cancel focus, failed Add retaining the existing voice, rename/delete, Indonesian/English generation and MP3 download. Saved original audio is retained and still served by private endpoints, although its normal sample controls/player are removed.

No physical-device, voice resemblance or production provider/audio claim is made. Authenticated production UI acceptance is required after deployment. No paid generation, production voice/data mutation, credentials, schema, Finance, Group, pricing, Call or Creative Services change.
