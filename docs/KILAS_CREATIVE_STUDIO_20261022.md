# Creative Services studio release — 2026-10-22

Scope: Creative Services visual redesign and portfolio destination only. Baseline `3327917a143f6a73d7cf311aadcf0e5cb833d2bd`.

The studio surface uses a typographic introduction, separate Event and Social Media service paths, open package comparisons, a direct Instagram portfolio destination, and the existing editable WhatsApp brief. All six package descriptions/prices and add-on facts were compared with baseline and preserved. The official Instagram URL is `https://instagram.com/kilasworks`, verified against `client-hub/repo.py` (`official_link_instagram`) and the existing brand landing page. No speculative portfolio imagery is added. Previously bundled gallery files remain available as static files, but the page no longer presents those third-party accounts as its portfolio.

Existing Home, chat, VO, Translator, Credits and Finance implementation files are unchanged. No credentials, prices, provider configuration, payment behavior or database changes. No actual WhatsApp send or paid generation occurred.

## Validation before publishing
- Creative Services server tests: 5 passed. Windows local MIME registry lacks `.woff2`; the local test launcher registered the standard MIME for this run. CI validates the same unchanged assertion natively on Linux.
- Experience tests: 6 passed, including ownership and exact draft handoff.
- Creative Studio browser: 1440/1024/820/390/320 px; ID/EN, packages, browser history, edited draft preservation, empty message guard, zero overflow/page errors/external traffic/writes; no-JS event deep link passed.
- Existing Experience browser: 1440/820/390/320 px; synthetic chat-to-VO, Library ownership/filter/fallback, VO result, credits disabled, Creative brief all passed.
- Home browser regression: 1440/820/412/390/320 px; bottom composer, no starters, drafts/attachments, short empty/populated scrolling and visualViewport focus/blur behavior passed.
- Generated Render bundle: 24 files match source byte-for-byte.
- Astra low finish review: first review requested matching SVG back arrow and separated mobile footer. Both fixed; refreshed captures scored both resolved, disposition `ship` for those fixes.

Local captures and machine-readable reports are under sibling `creative-studio-qa`, `creative-regression-qa`, and `creative-home-regression-qa`. Actual device hardware testing, paid generation, real external messaging, and Finance feature testing are not claimed. Linux CI and exact Render/production evidence are recorded in the final external release report after publishing.
