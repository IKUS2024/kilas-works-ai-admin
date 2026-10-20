# Stable first render across Chat, Translator and Voice Over — 2026-10-20

Baseline main/live: 4c2166724d85a34868f1c37dfc6efb8593b085e8. Preserve selector
localization, AI Call 078d5d1e and Finance 0f33bb4e.

Verified causes:
- Critical shell/sidebar, navigation, picker and component CSS remained in body.
  Delaying kilas_home.css 1000 ms reproduced a first contentful paint at 164 ms
  with header/main shell only (main height 80 px, no navigation or form). Content
  appeared later. A screenshot with that asset held confirms the partial UI.
- Native language selects were replaced with custom controls after JavaScript
  loaded. Delaying picker JS reproduced form height 402 -> 396 px on mobile.
- Manrope used font-display:swap and was discovered through CSS. Delayed-font
  baseline CLS was 0.00225; the font family/design itself does not need changing.

Fix:
- Move these existing styles into head, retaining their cascade order, and guard
  original component links to avoid duplicate body loads. Existing standalone
  templates keep their fallback links. Opt-in shell/font changes exclude Finance.
- Preload the existing local Manrope font on the opt-in Kilas shell; no font,
  font-display or design changes, timer gate, page hiding or client navigation
  interception.
- Render language picker wrappers/buttons/selected labels on the server. The
  existing script attaches behavior to those controls. Native select values,
  required fields, disabled languages and native display codes are retained.
  No-JavaScript CSS exposes the original native selects. Applies to classic,
  native and upload Translator; Voice Over content stays intact.

Validation, no paid inference/audio/microphone:
- New initial-render contracts: 3/3 PASS, including all CSS in head once, SSR
  controls/native values and Finance exclusion. Native Translator is included.
- New Chromium matrix: 144/144 PASS, 320/390/820/1440 px, cold CSS delay, warm
  HTTP-cache loads (without routing interception), delayed picker JS and font.
  Actual links/Voice Over handoff, two cycles of all six directions, direct URLs,
  reload/back/forward, model names, locale, consent and no-JS fallback checked.
  Zero incomplete painted frames, overflow, microphone calls or page errors;
  one geometry variant per navigation; maximum CLS 0.000518.
- Existing picker browser: 8/8 PASS, classic 83/native 76 languages, four locales,
  keyboard/search, form values, consent and mobile/tablet/desktop layout.
- Existing model initial-render suite: 14/14 PASS; audio navigation Node: 3/3 PASS.
- Home suite: 15/18 PASS. Classic Translator suite: 47/49 PASS. All five failures
  reproduce with baseline templates unchanged: historical language/menu/privacy
  expectations and pre-existing response-field changes. No new failure introduced;
  do not report those full suites as green.
- Finance account stylesheet order compared against baseline: exactly unchanged.
  No Finance source, billing/security/provider/model logic or engine adapter edits.

Reproduction: run tests/test_kilas_first_render.py and
 tests/kilas_first_render_browser.py with the existing offline fixtures. Run
 tests/kilas_first_render_visual_browser.py for baseline/fixed screenshots; it
 pins the baseline template revision and makes no production requests.

Artifacts: /tmp/kilas-first-render-browser/verification.json, visual-proof.json,
 baseline-partial.png and fixed-before-hydration.png. The fixed form is already
 x=20,y=283,width=350,height=396 before picker script, identical after hydration.
 Parent owns production browser confirmation because this environment's proxy
 previously denied direct production HTTP. Release proof records exact SHA/LIVE.
