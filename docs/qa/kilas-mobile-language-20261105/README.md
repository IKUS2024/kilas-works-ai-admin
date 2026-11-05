# Mobile typography and Creative Services app language

Base: `09ebf5a6a5050323f6f0f87e506654414de5a94c` (current main at branch creation)

- Catalog mobile titles are 28px, card titles 21px, body 14px; existing three-card navigation and desktop layout retained
- Creative Services mobile contact labels are 14px and values 16px; form inputs remain 16px and touch controls remain accessible
- Creative Services and checkout follow `kilas_language` in id/en/es/zh; missing/invalid preference defaults to English, matching the app
- Creative Services language buttons POST the existing CSRF-protected /language endpoint, which sets the HttpOnly app preference cookie; an existing edited consultation draft is preserved on switching languages
- Checkout translates explicit interface copy, known catalog labels, image alt text, validation errors and JS statuses only; stored order titles, customer notes, filenames, bank details and amounts are preserved
- Decorative terminal heading/brand periods and the portfolio CSS period removed; ordinary sentence punctuation, address abbreviations, domains and monetary separators preserved
- No Subscription, shared locale engine, global CSS, Finance implementation, entitlement, bank configuration or production data changes

## Verification

- 28 tests and 67 subtests passed: test_creative_checkout.py, test_products_catalog.py, test_creative_services.py
- 64 page/language/viewport cases passed: Products, Creative Services, checkout and payment × id/en/es/zh × 360/393/430/1180
- 32 existing checkout/payment geometry cases passed, including full-scene 1859×846 images, contain fitting, compact heights and accessible controls
- Existing Creative Services studio browser regression passed at 320/360/393/820/1024/1440, preserving navigation, portfolio links, image proportions and editable drafts
- Generated site bundle: 61 files match maintained source byte for byte
- git diff --check passed

Screenshots use disposable synthetic data and intercepted external network requests. They demonstrate local rendering, not production deployment or real payment verification. Bank shown in synthetic payment geometry remains the pre-existing fixture value; the separate Subscription/Bank revision owns its update. No full-repository CI claim is made.

To rerun: install client-hub/requirements.txt and playwright, then set PYTHONPATH=client-hub:client-hub/tests. Run the three pytest files above, test_creative_locale_mobile_browser.py, test_creative_checkout_layout_browser.py and test_creative_studio_browser.py. Chromium is required.

## HttpOnly preference correction

The initial browser matrix used injected cookies and did not reproduce the real app preference's HttpOnly flag. Review identified that reading document.cookie could therefore lose an actual app-selected language. The app-served page now receives its language and existing CSRF token from the server in a JSON bootstrap, with Cache-Control private, no-store and Vary Cookie. It does not read or write the language cookie from JavaScript. Local controls save through the existing /language POST, preserving HttpOnly/SameSite and current edited drafts. The standalone static version retains only its own localStorage preference. Browser titles are translated in all four languages.

New test_creative_language_persistence_browser.py passes real /language POST for id/en/es/zh, HttpOnly invisibility to document.cookie, reload, catalog→Creative Services→checkout→Back, local-button changes to a different language, edited draft retention, and rejection of invalid CSRF without changing the saved language. The mobile matrix was also updated to use HttpOnly cookies. The 28 tests and 67 subtests pass again with server-bootstrap assertions replacing the old static-response equality assertion; assets still match the packaged source exactly.

## Exact release gate compatibility

The released-assets workflow now compares personalized app HTML with the maintained source using a shared strict contract. Only the single expected JSON bootstrap and its matching html lang are normalized; exact full-document comparison remains afterward. The contract validates precisely language/csrfToken fields, a supported language, a 64-character hexadecimal CSRF token, private/no-store caching, Vary Cookie and X-Frame-Options DENY. Static HTML remains byte-for-byte exact. Negative tests reject changed markup, an extra arbitrary script, malformed context and missing security headers.

The GET-only release smoke now initializes app language with an HttpOnly cookie and standalone language with its own localStorage preference, and expects the requested punctuation-free headings. Both --local-app and --local passed four ID/EN × 393/1440 cases with no writes, external sends or provider calls. These paths and the real HttpOnly persistence/mobile tests are now included in Creative Services CI. The existing checkout journey explicitly selects Indonesian for its Indonesian-copy assertions; all 30 real synthetic package/add-on journeys pass.
