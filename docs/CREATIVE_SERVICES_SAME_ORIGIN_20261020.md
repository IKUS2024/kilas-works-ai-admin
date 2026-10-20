# Creative Services — same-origin integration and sans typography

The owner requested clean sans typography throughout Creative Services, the existing first company-profile video as Event cover, and navigation that stays on `app.kilasworks.id`. This release is based on main `5c4db5949c0926d60698d81884c40d0dfb717eec`, preserving its Voice Over Home-return correction.

## Result

- App route: `/creative-services/`; `/creative-services` canonicalizes to that same-origin trailing-slash path. CSS, the font and images are served under `/creative-services/assets/…`, so relative URLs work for every hash-based package/portfolio view.
- Existing Creative/Kilas Services navigation links point to the internal route. The chat sidebar retains the existing `data-chat-navigation` draft guard. In-app Home return uses `/products/start`; the standalone fallback retains its normal absolute app Home link.
- Inter 4.1 is self-hosted as a normal variable sans face (SIL Open Font License retained). Headings use weights 650–700, body uses 400, prices use tabular numerals; display headings cap at 64px and reduce on phones. Instrument Serif, its italic face and Creative Services' Manrope copy are retired. Other modules' typography is unchanged. Color contrast, service cards, bounded portfolio categories and existing gallery content remain.
- The Event overview now uses `assets/portfolio/event-first-drive.jpg`, the thumbnail belonging to original **Video Acara 01**, Drive file `1_RhxZwkV-XnmrJ4ygHAtJ3rZRMqwJOA3`, labeled Company Profile as requested by the owner. All 7 Event and 6 Social video links, their category membership and gallery order remain unchanged. The red-clothed couple remains original Event Video 07; only the featured overview cover changes. No new image was generated or purchased.
- Initial/direct/repeated hash navigation accounts for the measured sticky header and the portfolio intro's height, including native browser hash restoration after font loading. This keeps the Portfolio heading and category navigation visible.

## One maintained source, generated deployment bundle

`creative-services-site/` remains the maintained source and the existing static site's publish directory. Render's Client Hub root is `client-hub`; files outside a service root are unavailable at build/runtime ([Render monorepo documentation](https://render.com/docs/monorepo-support)). Therefore `client-hub/creative-services-site/` is a generated, byte-identical deployment bundle, not a second manually edited site.

After changing the maintained source:

```sh
python scripts/package_creative_services.py
python scripts/package_creative_services.py --check
```

The deterministic manifest and `test_creative_services` compare every packaged file with its source. No Render root/build setting, DNS, new service, iframe or external redirect is required. Both existing services can deploy the same source commit; the static service remains the public fallback.

The new read-only handlers register on the existing `client` blueprint. Existing host, invalid-session, CSRF and Finance-session guards are unchanged; the page remains public like the former standalone marketing page. It reads no customer data and writes no ledger, model, payment, subscription or account state. Only GET/HEAD are served; `send_from_directory` bounds asset paths. Existing app security headers and conditional asset requests remain active.

## Evidence

Local evidence is in `/workspace/creative-sans-review/` (internal workspace artifacts, not owner download links).

- 36 responsive views at 1440/1280/1024/768/390/360, ID/EN × home/Event/Social, passed on the real app route with loaded Inter, normal/non-condensed headings, no horizontal overflow, nested assets, package actions, keyboard, reduced motion and font fallback.
- 30 category/locale/width states passed actual heading → description → matching media → action ownership checks, category bounds, original mapping, direct reload/repeated hash and sticky-header clearance. Screenshots were visually reviewed.
- 12 authenticated browser flows passed: app menu → same-origin Creative → language/package/gallery hashes → back Home/browser back. Anonymous Creative remains public; Home retains its existing login redirect. No external video or WhatsApp message was sent.
- 8 focused route/sidebar tests passed: exact packaged bytes, all assets/MIME/ETag, path traversal rejection, preserved invalid-session/host guards, Finance rows unchanged, four app UI locales and existing Finance CSRF/ownership behavior. Two focused native-handoff/Voice Over regressions also passed.
- The wider Home suite has 3 pre-existing label/language assertions; the wider Trading-host suite has 3 pre-existing label assertions. Running those suites on a clean worktree of main `5c4db594` reproduces the same six failures. Their assertions were not removed or weakened. A combined Trading invocation also double-initialized its fixture; that harness error was isolated from the focused route tests.
- No Finance, Chat/Call/Search, Translator or Voice Over implementation was changed. Shared navigation changes only the approved Services destination. No production data or configuration was mutated for QA. Tests use disposable SQLite accounts with provider calls blocked.

Release verification must record the pushed SHA and both existing service deploy IDs/statuses. Production pixels are verified separately by the parent; local screenshots do not establish production browser delivery.
