# Selected model names on first paint

Follow-up to `45a70f2f92fe67c2ce2cccbcc0f737fd2abba53b`, after authenticated live acceptance of the simple Translator setup and Chat stylesheet fix. The remaining observed issue was generic selector headings appearing before the stored selected names.

## Cause and focused correction

`_model_selector.html` previously rendered only generic headings and a hidden provider icon. `kilas_chat_models.js` replaced these after its catalog GETs. The template now renders the selected names, provider icons, title and accessible heading from the existing owner-scoped selection data and local catalog names. The browser selector still performs its original account/model verification and submission guards; server-rendered names never authorize dispatch or replace that verification. No selector JavaScript or selection/routing endpoint behavior changes.

New unsent Home uses the current user's reserved account-default rows. Existing legacy threads and modern conversations use their own owned selection rows, preserving the original catalog endpoint semantics. A saved conversation without a snapshot does not inherit a newer account choice. Rendering does not create a selection, change preferences or query a provider.

When there is no saved choice, the server can use a complete, fresh in-memory account metadata cache to resolve the same default as the normal catalog. The new cache-only path uses the existing provider-key fingerprint and availability TTL rules, never refreshes metadata and never performs network IO. If no complete fresh cache exists, the template shows a localized **Loading models…** state instead of guessing an available default. The existing asynchronous catalog then determines availability/default normally.

Saved unavailable models retain their names and do not silently switch. A fresh cached unavailable status renders the existing warning immediately; otherwise availability is left for the normal account check. Added translations for the loading state and the existing saved Chat/image unavailable warnings, including the client whitelist so those warnings do not switch language during hydration. No prices, model IDs/options, API payloads, actual model checks, Finance, Group, Call, Translator, Voice Over or Creative Services implementation changes.

## Verification

- **41 focused Python tests pass**: initial HTML rendering plus inherited model preference regressions, Home/sidebar and simple Translator consent guards. Cases include exact stored names/icons without JavaScript, older thread/conversation choices versus later account defaults, no-snapshot scope behavior, unavailable names/warnings with no fallback or preference rewrite, cold-cache loading in all four app languages, cache-only defaults, changed-key cache rejection and foreign-chat denial. Provider GET transport is forbidden in the initial-render cases.
- **Eight real Chromium scenarios pass** at 360/1440px: new Home defaults, a legacy thread, a modern conversation and an unavailable saved image model. The tests hold the selector JavaScript response, verify names already exist in the rendered page, then hold catalog responses and verify those same names persist before verification completes. Each tested document records one distinct text value per selector, with no generic-heading phase. Existing JavaScript selection remains empty until its catalog verification completes.
- Browser reload, Chat/Translator navigation and Back/Forward retain the correct per-document scope. Stored account and existing-chat choices remain unchanged. Unavailable models keep their name and localized warning after hydration. Browser JavaScript errors and selector/generation POSTs are absent; the existing modern Work frontend's internal preferences POSTs are allowed in these isolated fixtures. No real microphone or paid/provider transport is used.
- Mobile Home and desktop saved-thread layouts were reviewed once. No new layout/style or navigation framework is introduced. Browser evidence is under `/tmp/kilas-model-initial-browser/verification.json`; logs `/tmp/kilas-initial-label-browser.log` and `/tmp/kilas-initial-label-final-python.log`.

## Actual limits

Feature switching remains native document navigation. The live observer's isolated white navigation frame is distinct from selector hydration and may remain; this patch makes no claim of eliminating browser navigation or all network latency. Cold users with neither a saved choice nor a complete fresh metadata cache see the explicit loading state until the normal catalog resolves. Initial rendering adds only local/DB/cache work, not provider calls or new availability assumptions. Authenticated production first-paint acceptance is required after deployment.
