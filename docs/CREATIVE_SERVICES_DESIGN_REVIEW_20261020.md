# Creative Services editorial redesign — local review, 20 October 2026

Implemented on `design/creative-services-editorial-20261020`, based on remote main `31a14993151ba781b48791da898960142ae8e0e4`. **Not pushed, merged or deployed. Parent review/release authorization is still required.**

## Result and design decisions

The former opening presented two nearly identical text cards, a generic sans heading, and almost no visible work. The event portfolio had no visual preview on the overview. The new composition gives actual work a substantial place in the first viewport and makes the service choice distinct.

- Self-hosted **Instrument Serif** regular/italic supplies the editorial display voice; **Manrope** supplies modern body text, readable price numerals and controls. Both include SIL Open Font License files. Georgia/Times and Arial/system sans provide fallbacks; `font-display: swap` preserves usable text during loading.
- Warm paper, existing Kilas burnt orange, and deliberate charcoal sections preserve the brand. Existing logo, name, company identity and actual portfolio imagery remain. No generated images, invented testimonials or new sales claims.
- Hero uses the existing event video cover plus an existing social production still. It links to the same two portfolio collections. The two original service choices use contrasting surfaces and larger editorial titles.
- Prices and outputs form the first reading layer of each package; inclusions and the existing CTA follow. Social package rows share a CSS subgrid on desktop, preventing Premium's shorter summary from shifting the outputs. Tablet uses two-column comparison rows; mobile uses stacked cards.
- Overview portfolio previews now lead with a wedding frame and a strip of real social content. Detail retains the original One More Take account screenshot and all thirteen original external video destinations. Event collection uses one cinematic opening frame plus six thumbnails for complete desktop/tablet rows. All original video thumbnail images remain visible without cropping except the cinematic overview/feature treatments; original videos remain at their existing destinations.
- Closing consultation section uses charcoal to create a clear change of rhythm. The approved WhatsApp message flow is retained. Mobile keeps Services and Portfolio navigation visible. SVG symbols avoid font missing-glyph artifacts.

All 128 existing bilingual text pairs, six package prices, three add-on prices, six package identifiers/WhatsApp URLs, and thirteen portfolio URLs were compared with main and preserved. The only behavior-script change updates the accessible region label to the currently visible page heading. Detail headings now use h1. Extracted logo, favicon and social account preview are byte-preserved originals; moving them from data URLs enables caching. Application source changes are confined to `creative-services-site`; the other additions are this review and a scoped browser QA script. AI Chat/Call, Finance, Translator, server code and shared app CSS were not edited.

## Verified target — read-only Render inspection

| Field | Verified value |
| --- | --- |
| Service | `kilasworks-creative-services` |
| ID | `srv-db96d5vf3r2c73a9io00` |
| Type | `static_site` |
| Repository / branch | `IKUS2024/kilas-works-ai-admin` / `main` |
| Build / publish | `true` / `creative-services-site` |
| URL | https://kilasworks-creative-services.onrender.com/ |
| Auto-deploy | Off |
| Current live deploy | `dep-dbb5l5e7bikc73d5kdvg` |
| Current live source | `ba2622fab38a63cedcc521e559d5ad113a67bc82` |

Dashboard: https://dashboard.render.com/static/srv-db96d5vf3r2c73a9io00 . The Client Hub is a different web service (`srv-da7ti2psrm7s73dh9i2g`) and is not the deployment target. No Render mutations, hosting changes or DNS operations were performed. The supplied `app.kilasworks.id` link destination was not reconfigured. Historical `kilasworks.id` canonical metadata is retained; its DNS/hosting target has not been independently verified or changed.

## Browser and content validation

Real headless Chromium screenshots and checks, not static layout inference:

- **36 responsive views passed:** 1440, 1280, 1024, 768, 390 and 360px × home/event/social × Indonesian/English. Document and individual main-content bounds show no horizontal overflow. All visible images decoded and both font families loaded. No page errors or failing local resource responses.
- Each of the six sizes exercised both service cards, service returns, portfolio collection navigation, logo and header destinations. All 13 portfolio links retain their original HTTPS destination and external-tab behavior.
- All six actual package click handlers exercised with external navigation prevented; selected-package status and contact WhatsApp payload matched. No WhatsApp message was sent or external video played.
- The existing source has **zero modals/dialogs**. The supported interaction is hash-based service detail plus direct external video links; no unnecessary modal was introduced.
- **12 accessibility states passed:** all three views × both languages at 1440/360. Computed visible DOM text contrast minimum **4.77:1**; one visible h1; header navigation/language and package controls at least 44px high. Keyboard skip-to-content, service focus outline, reduced motion and a blocked-font 360px fallback render passed. This is a focused check, not a full accessibility certification.
- Baseline screenshot source has index blob `a3bf825983575285508b5504ed581db9dc940832`, identical to the live Render deployment's source and current main. These are **local baseline renders**, not successfully fetched production browser pixels.
- Inspected desktop, tablet and phone screenshots. One refinement batch corrected SVG glyphs, package row alignment, mobile nav targets, active heading labels and complete event gallery rows. Final captures reset scroll to the document origin so hash navigation does not displace the sticky header in full-page evidence.
- `git diff --check` passed. No backend/full-repository tests were run for this isolated static presentation change.

Evidence directory in the execution environment: `/workspace/creative-review/`:

- `index.html`: before/after review gallery, six viewport choices, home/event/social and language controls.
- `before/`: 18 baseline full-page PNGs; `after/`: 36 final full-page PNGs plus keyboard/fallback evidence.
- `results.json`, `accessibility-results.json`, `content-results.json`: machine-readable evidence.
- `creative-services-review.zip`: portable gallery, screenshots, current static site, patch and check results.

Local preview server: `http://127.0.0.1:8765/`. It is a workspace-local process, not a publicly deployed preview. To restart:

```sh
python -m http.server 8765 --bind 127.0.0.1 --directory creative-services-site
```

Reproduce responsive/interaction checks (Playwright and Chromium must be available in the test environment; no application dependency was added):

```sh
OUTPUT_DIR=/tmp/creative-services-qa node scripts/qa/creative_services_visual.cjs
```

## Remaining limitations / release gate

**Live browser inspection denied by network proxy:** opening `https://kilasworks-creative-services.onrender.com/` failed with `ERR_TUNNEL_CONNECTION_FAILED`; curl received CONNECT HTTP 403 and the web reader also could not access it. Render metadata reads succeeded. Therefore public serving/caching, real third-party video availability and actual WhatsApp delivery are not certified by this local QA. No bypass or hosting change was attempted. Local implementation, screenshots, responsive navigation and payload checks are complete.

**Release is intentionally pending parent review.** Do not push, trigger a deploy, repoint DNS or use Client Hub to publish this candidate before the parent authorizes release.

Font provenance: [Instrument Serif source](https://github.com/google/fonts/tree/main/ofl/instrumentserif), with the retrieved OFL text retained locally. Manrope was copied from the repository's existing licensed `client-hub/static/fonts` asset into this isolated static site's own assets; its original file was not modified.
