# Copilot App Language — 2026-10-28

Scope: interface localization only, retaining the approved composition, capture lifecycle, reply/translation policy, models, budget and data. No new setting, language choice, credential or schema.

## Root cause and correction

App Language already uses `kilas_language`, an explicit one-year HttpOnly/SameSite cookie written by the existing CSRF-protected `/language` form. Default is English, independent of browser Accept-Language; invalid cookie values fall back to English. Server `ui_t` uses `ui_en.json` overrides for EN and `ui.json` for other choices; missing keys fall back to the original source string. Client `KilasUI.t` receives only registered UI keys from `client.json` and uses the same request locale.

The profile used that path, but Copilot template/JS literals and sidebar session labels bypassed it. SSE statuses were also hardcoded Indonesian and skipped the normal streamed-response localization hook. Several existing tool strings had translations but were missing from the client registry: notably Record Script, which therefore stayed English in an Indonesian page.

- Route Copilot static/accessible/control copy and dynamic statuses/errors/result/history/copy labels through the existing i18n helpers. Preserve internal state/style codes and both microphone handlers.
- Translate only SSE `status.text` inside the request-scoped writer. The background provider thread needs no request locale. Deltas, transcript, reply, translation values, user-derived titles and error codes remain untouched.
- Localize target-language display names without modifying language codes, autodetection, selected model/target or primary reply language. The model policy and its policy fingerprint are unchanged from PR175.
- Localize sidebar session/history labels and dialogs; preserve arbitrary titles and data even when their text matches a UI key.
- Fix classic Translator Start/Stop/End and older audio action labels. Register omitted dynamic tool copy, including Record Script. Keep Translator/Voice Over free of the global left rail.

Proper product names intentionally remain: Kilas Works, Conversation Copilot, Copilot, Translator, Voice Over, Finance and approved voice aliases. Actual conversation/script/history content is not UI and can naturally be in a different language.

## Coverage and limits

Existing App Language choices remain EN, ID, ES and ZH. Every explicit new Copilot JS key is registered and has all four catalog values with matching interpolation fields. Backend core-page checks cover all four; end-to-end visual/interaction QA covers EN and ID. Scoped template inventory has 201 literal UI keys and no missing EN mapping. Tool JS inventory has 257 literal UI keys; all have client registrations and EN mappings, and English-source literals have ID mappings.

Added ES/ZH core tool/chrome labels where absent. Advanced/legacy tool templates still have 52 literal keys without explicit ES/ZH values in this scoped inventory; source-string fallback remains. This is not a claim that all application pages, dynamic legacy variants, or all ES/ZH helper/error copy are fully translated. Browser-native file/audio controls follow browser/OS language. No machine translator runs over page text or user content.

## Verification

- Existing Copilot contracts: 30 tests; new locale contracts: 8; existing i18n contracts: 14; JS i18n: 4; SSE/WAV contracts. Provider generation mocked.
- EN and ID at 360/393/1440: actual Apply POST, HttpOnly locale persistence, reload/new/existing sessions, tab navigation and back/forward, closed/open profile/sidebar, new-session/history labels, no tool left rail, permission denial, listening/processing/completion, cancel and copy/copy failure, translated history, exact unmodified content and no horizontal overflow.
- Applying App Language while listening stops the old capture, performs no provider request, and does not rearm the microphone on the new page. Ephemeral capture is not preserved across navigation; existing defaults remain.
- Primary model prompt/content and target code are identical across UI locales in provider-contract tests. Localized fill-yourself slots remain answer-language content, not UI-locale substitutions.
- Pixel inspection caught Record Script still missing from the ID client map; its registration is now asserted. Full-page screenshots return to scroll origin and blur focus so offscreen fixed accessibility links do not appear as screenshot overlays; the skip link remains intact.
- Read-only production smoke waits for matching Copilot/classic Translator assets, checks health/auth redirects, then reads the public login UI catalog under EN/ID preference cookies. No login submission, paid API request, microphone request or production-data mutation.

Representative screenshots and locale-report.json use the existing copilot-synthetic-browser artifact. Synthetic tool accounts are deliberately unfunded and lack production audio keys/voices; unavailable-service labels in screenshots are fixture state, not production enablement changes. Physical mic/call/Safari and paid model/audio acceptance remain NOT RUN.
