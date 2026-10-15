# App Language — implementation and release review

Base and remote main verified: `7828a886ff907d31864399d3959b2ae013df6cc4`.
The local implementation was completed without commit/push/deploy. The owner
subsequently approved release with “pantau sampai live” at 2026-10-15 17:05:25 UTC
after the assistant explicitly asked permission to deploy this language fix.
Release now follows the existing main/Client Hub workflow. Live status and exact
commit evidence are recorded separately after deployment, not assumed here.

## Behavior

- English is the default with no preference or an invalid language cookie.
  Browser Accept-Language does not override that default. Explicit `id`, `en`,
  `es` and `zh` selections keep the existing one-year cookie, CSRF checks,
  redirect validation, HttpOnly and SameSite behavior.
- Existing translations remain in `ui.json`; `ui_en.json` adds English coverage
  for newer application copy. The client allowlist contains only text used by
  scripts, including known server activity/error messages. It does not include
  unrelated catalog or internal configuration copy.
- Explicit UI labels, instructions, accessible names, dialogs, loading states,
  recovery errors, pagination and audio status labels use the selected locale.
  Changed application assets/imports carry a new version so refresh does not
  combine cached Indonesian scripts with updated English templates.
- Only known UI response fields are translated: error responses, failed-turn
  errors, and the audio status endpoint's status label. Downloads, streamed
  responses, successful content JSON, nested content and all script/transcript/
  translated-text/language/voice/credit values are preserved. Four numeric UI
  error formats retain the exact limits and balance values.
- Stored conversation/project/voice names and user or generated content are
  deliberately preserved, even if their text happens to equal a UI catalog key.
  Live Translator keeps its `id`/`en` defaults, distinct-language validation,
  voice IDs, 2000 ms silence endpoint and existing playback/cancellation rules.
- No provider/model/voice selection, credit/quota rules, billing, Finance logic,
  database schema, session authority or retired Learning entry is changed.
  The notification worker's empty-body fallback uses the language-neutral brand;
  supplied notification content is preserved.

## Coverage and checks

- 13 Python test modules passed locally: UI i18n, English rendering, Audio,
  audio history, personal voice, Home, unified AI, cost/quality, historical
  Learning, Learning retirement, incremental Translator, whole-utterance
  Translator, and standalone Finance baseline.
- UI i18n: 13 tests for English default, valid/invalid selections, persistence,
  safe redirects/interpolation, catalog consistency, numeric errors, protected
  response fields and untouched successful/downloaded JSON.
- English rendering: 6 tests with real Flask/Jinja and disposable SQLite data.
  Home/Chat, Subscription, Library, Voice Over, Translator and Account are
  checked twice; saved voice names, project/script content, history paging and
  source/target/voice settings are checked independently.
- All 318 JavaScript tests passed, including historical Learning and Translator
  lifecycle regressions. Eight new UI tests include four DOM cases using real
  Flask markup and mocked IO at 390/1440 widths. They check English pending/error
  recovery, End's accessible name, history status and preservation of draft and
  voice values during pagination. DOM emulation provides no CSS-layout proof.
- Ruff E9/F passed on changed Python files. Changed Python/JavaScript syntax,
  all 235 Jinja templates, and `git diff --check` passed.
- Historical Indonesian audio copy checks and browser fixtures now explicitly select Indonesian;
  default-English assertions live in the new suites. Existing expectations for
  default English and script-embedded catalogs were corrected. A stale Node VM
  fixture now supplies the Event/dispatchEvent primitives the existing script
  already uses. No business assertion was removed. CI confirmed the old browser fixtures were
  receiving correct English values (“Processing”, “uses 3s of balance”) while
  expecting Indonesian without selecting a locale. Their existing Indonesian
  UI scenarios now explicitly send `kilas_language=id`; the new dedicated
  suite continues to test the no-preference English default. No browser was
  launched manually for this fixture correction.

## Limits and release gate

The local QA launched no browser, captured no microphone, called no paid API
and wrote no production data. A dedicated browser-free App Language CI workflow
runs the locale/Flask and eight mocked UI regressions on the release commit. No new
subscriptions, keys or permissions were requested. Real Android playback and
visual layout are not verified by these mocks.

The active customer workspace was audited. Protected Finance implementation,
legacy Assist/admin screens and separate legal/source documents were not
rewritten. Existing Spanish/Chinese choices and translations remain; the new
supplement is English coverage, not a claim of complete Spanish/Chinese copy.
Existing saved titles/content may appropriately remain Indonesian.

Reference `libfile_57d446585fc08191b58265aab0022701` resolved to
`1000332902.jpg` (221254 bytes). The current supported helper failed once to
materialize it; no pixels were viewed and no alternate download was attempted.

Runtime logs and fixtures are in `/workspace/app-language-audit/`.
The review patch and machine-readable evidence are outside the repository at
`/workspace/app-language-local-review.patch` and
`/workspace/app-language-local-evidence.json`. The explicit release approval has now been received. The release evidence
file records the final commit, CI, deploy result and actual verification limits.

The existing Finance dashboard copy suite also selected no locale while asserting
Indonesian labels (22 copy-only failures under the new English default). Its
disposable test client now explicitly selects Indonesian. An added default-
English test clears that preference, checks the English UI and compares the
exact financial summary values across locales. No Finance implementation or
financial assertion was changed.
