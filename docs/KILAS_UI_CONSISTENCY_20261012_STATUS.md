# Kilas UI consistency — 12 October 2026

## Scope and source

User-authorized refinement of existing white Manrope/orange UI: shared AI Chat / Translator / Voice Over / Finance navigation, chat typography/composer layout, informational profile email, Finance-only full Account editor without sidebar, Finance sidebar presentation, compact Live Translator setup and mobile Voice Over setup. No new product capability.

Isolated worktree `ui-consistency-20261012`, based on remote main `1565016fb928a3299a694302c07a861c6087eee2`. Original checkout and separate audio/Trading work were preserved.

## Implemented

- One shared task navigation stylesheet/component: 44px controls, matching icons/type/active state; narrow screens use a single horizontally scrolling row without widening the page or breaking words. Translator availability still uses existing owner authorization; Finance receives the same read-only availability projection.
- Exclude the Assist-specific CSS/JS layer from AI and Audio routes. It had been overriding Audio control typography. Assist routes retain their existing layer.
- Chat inherits Manrope; user messages remain right-aligned and AI replies left-aligned with content-sized bubbles. Accepted submissions clear/collapse the composer before response streaming completes. Existing mobile blur/fine-pointer focus behavior is preserved; compact keyboard layout hides the redundant chat header.
- Profile email is informational text. Subscription, App Language and Logout remain. Subscription points to the existing Finance Account entry explicitly; no duplicate AI profile editor is introduced.
- Account retains Personal/Business/Security forms and Finance return destination; all direct/hinted/hash entries render without a sidebar. Finance pages retain their sidebar and shared task navigation.
- Live Translator language/voice/consent/Start controls are grouped compactly. Unchanged truthful provider/processing notice moves into an accessible privacy disclosure. Duplicate `kw-main` ID removed.
- Voice Over heading/voice-choice cards are compact. Its redundant single-mode tab is hidden; the existing internal hook remains so saved-voice/edit/recording behavior is preserved. Two-mode audio tab switching remains available when configured.

## Verification before release

- Impeccable context + polish/audit/craft-floor guidance used on the scoped UI. One manual detector scan completed, exit 0. It emitted 194 findings across complete existing files, mostly token/type/radius/color advisories. The stale DESIGN sidecar and unset build path were reported, not repaired. Jinja stylesheet URLs are not resolved by the detector; its Account dark-color/contrast reports do not represent the rendered light-theme screenshots. The existing orb and unrelated legacy declarations were preserved. This is not a claim of a clean whole-app audit.
- New disposable Flask + Chromium acceptance: 60 route/viewport captures at **360×800, 390×844, 768×1024, 1024×768, 1440×900, 844×390**. PASS: Home, saved Chat, profile text, simulated keyboard viewport, Voice Over, Live Translator, Finance dashboard/settings, Account direct/hinted/hash loads and refresh; page overflow, 44px controls, icons/alignment, horizontal task scrolling, active states, voice selectors, privacy/consent and accepted-draft shrink/focus. No provider calls.
- Home browser PASS at 320/390/1440: mocked chat/stream/Stop, attachments/draft guards, copy, history/reload/back-forward, native task handoff, Account tabs/no sidebar and Subscription entry.
- Shared sidebar browser PASS at 320/390/1440: normal/Agent chat, saved attachments/history, draft cancellation, drawer close methods, audio handoff.
- Revisions browser PASS at 320/390/820/1440: history/new/back-forward/library/profile and synthetic dictation/cancel/error.
- Live Translator browser PASS at 320/360/390/430/820/1440: synthetic microphone, >=3-second silence, both language directions, voice, resume, feedback prevention, End and permission/error gates. These are mocks, not new real speech/provider QA.
- Unit checks: Audio + Live Translator **68 PASS**; Revisions **7 PASS**; focused Home UI **14 PASS**. JavaScript syntax and `git diff --check` PASS.
- Windows-specific legacy fixture limitations: Finance fixtures initially cannot unlink an open SQLite database; the separate content-project fixture requires a Linux `/tmp` disposable path. No production code was changed to bypass these guards. Full Linux CI is the release gate for those checks. No whole-repository test suite was requested/run.
- A test-process-only Windows adapter closed the disposable SQLite connection before reset. Finance invoice editor **18 PASS**; final Finance stylesheet/UI checks **13 PASS**. The first stylesheet test detected late-loaded task CSS on 17 routes; fixed by loading Finance task styles in `<head>` and avoiding body stylesheet duplication. Ledger/invoice behavior did not require any change.
- Current-baseline copy/form preservation **3 PASS** using a test-only Windows temporary-directory equivalent for disposable content tables. Historical fixture reads now explicitly use UTF-8. Account/profile/security and subscription purchase forms match the pre-change release; intentionally removed AI account navigation is tested separately. Already-hidden Audio balance UI was not reintroduced.
- CI caught an accepted-stream error losing its draft after the new early composer collapse. Both chat clients now restore only their cleared draft on error/Stop without overwriting subsequent text. Canonical chat Chromium acceptance PASS at 320/390/820/1180/1440, including HTTP rejection, SSE error + DONE, empty DONE, retry, persistence and keyboard viewport behavior. Existing error assertions were retained.
- Unified browser acceptance now waits for Kirim to become ready after streaming/refresh, rather than treating the newly early-cleared draft as completion. Global UI acceptance explicitly checks Account has no sidebar and a Finance return link; other routes still require Home navigation.
- The Trading CI Services-link assertion also fails on the untouched pre-change release `1565016fb928a3299a694302c07a861c6087eee2`, reproduced with that source in a disposable temporary directory and only that single assertion test. It is a pre-existing navigation expectation, not a Trading/UI regression introduced here. No Trading file or behavior was changed to satisfy it.
- Screenshots and local reports: `%TEMP%/kilas-ui-consistency-20261012/`, `%TEMP%/kilas-home-review/`, `%TEMP%/kilas-sidebar-review/`, `%TEMP%/kilas-revisions-browser/`, `%TEMP%/kilas-live-translator-browser/`. CI uploads the new consistency captures with the Global UI responsive artifact.

## Release checkpoint

Source commit/push, Linux CI and targeted Client Hub deployment pending at this checkpoint. Do not deploy AI Admin, run migrations or change environment flags for this UI release. No models/providers/keys, pricing/quota/billing logic, speech/translation/TTS mechanics, silence timing, Finance calculations/ledger, schema, Trading source or customer data changed.

Authenticated production visual QA is blocked by the official Computer Use URL-verification rejection on Windows: it could not determine the current browser URL confidently enough to enforce policy. No alternate browser transport, cookies/session extraction or security bypass was attempted. Local disposable-browser evidence is distinct from production evidence. After release, verify Render LIVE/source SHA, public health/static assets and error logs independently; do not claim authenticated production visual QA passed until access is safely restored.
