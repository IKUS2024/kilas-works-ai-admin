# Kilas Works asset and task experience — 2026-10-22

Authorized scope: Library, Home starters, explicit Chat → Voice Over drafts, Voice Over presentation, Creative Services brief, and honest credits preview. Baseline main and production: `7349b55efdceda1f9200cd379c3a36f6cf382f34`. Work proceeds on main in an isolated clean checkout; unrelated test artifacts in the previous checkout are preserved.

## Implementation

- Read-only Library metadata projection across existing attachments, generated work files, audio results, and video plans. Newest first, server search/type filters and 24-item pagination expose older records; original owner-scoped open/download handlers remain authoritative. Numeric image filenames use their chat title without renaming source files. Missing images have a fallback; long titles wrap and clamp with full names available. No source record is copied, deleted, migrated or reassigned.
- Four concise localized Home starters populate a draft or open Voice Over. They do not submit a chat or invoke a provider. Existing model selection and chat transports remain unchanged.
- Suitable prose answers expose an explicit Voice Over draft action. A selection inside the answer takes precedence; otherwise the exact original response is transferred. No trimming, truncation, translation or automatic generation. Over 4,000 characters requires a shorter selection. CSRF and existing role/account checks remain; return URLs are restricted to local chat routes.
- Voice Over shows the latest completed, owned, non-live/non-learning result with a native player and existing downloads. History dates are formatted locally and retain human script titles. The editable script has an honest approximate duration range based on words/CJK characters, including a visible edited translation when applicable. This is not a quota, charge or provider duration promise. Existing spoken/translated-script editing and saved voice identity remain unchanged.
- Creative Services package selection leads to a date/location/needs brief. Prepare message builds an editable draft. Only the explicit WhatsApp link opens WhatsApp; nothing sends automatically. Existing phone, package prices, portfolio and business copy stay intact. No invented service area, delivery promise, testimonial or metrics. The maintained source and Render-root bundle match byte for byte; packager paths are portable across Windows/Linux.
- Credits remains an inactive design preview, with explicit transaction/balance disclaimers and a disabled payment control. No billing implementation or rates added.

## Validation

All providers mocked; local browser external traffic blocked. Windows QA uses real Flask, SQLite, media processing and Chromium, UTF-8 mode, and a test-only import shim that rejects unrelated Linux sandbox execution.

- New task/asset suite: 5 tests pass, covering owner isolation, foreign media denial, literal search, pagination beyond the old visible limit, no record duplication/deletion, exact draft/CSRF/no-provider behavior, latest result isolation and four app languages.
- Audio: 52 pass; audio history: 4 pass; saved voices: 19 pass; audio video-script: 23 pass; exact spoken edit: 4 pass; selected Chat models: 20 pass; UI localization: 14 pass.
- Node dictation/recording/navigation/localization: 21 pass. New JavaScript syntax checks pass.
- New Chromium task paths pass at 320, 390, 820 and 1440px: starters retain an existing draft, synthetic chat, exact/selected-text VO handoff, return/back/forward, voice choice, duration display, Library filter/back and failed-preview fallback, disabled payments, editable WhatsApp message. No audio-generation request is made. Batched visual review and a bounded correction pass cover long names and a compact latest-result panel.
- Creative Services bundle check: all 22 files match source. Focused Creative tests retain auth/host/traversal and Finance-session state checks.
- Existing Home suite: 5 of 18 fail identically on unmodified main (old billing/account/UI wording and Windows WebP MIME mapping). Legacy Chat: 5 of 8 fail identically on main; legacy attachments: 2 of 6 fail identically on main, after current model-selection changes. Creative Services has the same pre-existing Windows WOFF2 MIME failure; its bundle-path portability failure is corrected. No assertions are removed to make these green.
- The four-test standalone Finance boundary fixture cannot run on this Windows host because its SQLite reset unlinks an open database (`WinError 32`); reproduced identically on baseline. Finance source/templates/styles/routes/schema have no changed paths. Linux CI is added for focused experience, audio/model, Creative Services and boundary checks before deployment.

## Deliberate limits

No paid AI generation, real WhatsApp send, payment, credentials, production data write, migration, provider/streaming architecture change, AI Call or Translator latency claim. Functional AI Call/live Translator transport testing is outside this release. General speaking-style presets are deferred: current alternative-delivery support switches TTS model, while this task requires preserving existing models/voices. Existing supported “generate another version” behavior stays intact. No fake style controls or credit estimates are added.

Deployment is not established by this document or by a push. Record the exact published commit, Render deploy ID/terminal live status, authenticated affected-page checks and any remaining CI limitations in the final release evidence.
