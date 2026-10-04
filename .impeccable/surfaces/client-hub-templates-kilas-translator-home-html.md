---
version: 1
slug: "client-hub-templates-kilas-translator-home-html"
primary_target: "client-hub/templates/kilas_translator/home.html"
related_targets: ["client-hub/templates/kilas_translator/_balance.html", "client-hub/templates/kilas_translator/_result.html", "client-hub/templates/kilas_translator/invoice.html", "client-hub/static/kilas_audio.css", "client-hub/static/kilas_audio.js"]
---

## Direction contract

THESIS: Translate existing speech or create a voice over in one practical audio workspace, with one shared prepaid balance measured in seconds.
OWN-WORLD: Ordinary extension of the incumbent white Kilas workbench: Manrope, charcoal content, neutral borders and deliberate orange actions and selections. Root DESIGN.md and .impeccable/design.json remain authoritative and preserved.
MODE: Operate.
STORY: Choose Translate or Voice Over; upload audio/video or write a script and choose a voice; inspect required duration or the voice estimate/reservation; submit once; revisit the persisted job; preview and download its MP3. Buy shared Audio seconds through the existing bank-transfer/admin-verification flow when needed.
FIRST VIEWPORT: Product promise, shared available-seconds balance, precisely two mode tabs and the active input. Actual job status and result appear before the tabs when reopening a job. Desktop history supports the work; narrower layouts put it below the primary workflow.
FORM: Code-led extension of the current product world, following the owner's specified two-tab utility. No concept tournament, decision comps or decorative imagery. Native controls, minimum 44px ordinary control heights, restrained borders, honest operational status and persistent history.
FINISH: Independent finish review and documentation are required. No shipping raster was added; screenshot/media fixtures are synthetic QA evidence.

## Implemented expression

The surface caps its working area at 1100px. A flexible primary column and 240px history column share a 40px gap; at 1100px and below history moves beneath the primary workflow. At 600px and below the heading, fields, voice choices and purchase packs stack. Between 601px and 900px packs use individual horizontal rows; price strings remain unbroken. Headings use 30px/22px, reducing the page heading to 28px on smaller screens; form fields use 16px Manrope. Tab, radio and current-history states retain the existing orange selection vocabulary.

White field overrides are scoped to this Audio surface. The native file-selector button uses readable charcoal text and a neutral fill, retaining browser file-input semantics. Arrow keys, Home and End navigate the two tabs. Native radio choices, audio controls, visible labels, focus outlines, live progress and alert text convey real state. History has owner-scoped links, status, duration and a UTC date/time with a semantic time element. The implementation mixes Indonesian utility copy with the requested English mode labels and some result actions; this is a surface fact, not a new global localization rule.

The balance exposes available and reserved seconds. Estimates are distinguished from actual final usage. Missing-provider and zero-balance states disable processing and explain why. A successful result exposes a native MP3 player, download action and recorded charge; a failed result explains that balance was not deducted and the paid submission will not be retried automatically.

## Review and documentation boundary

Independent reviewer disposition reported by the build thread: **ship**, at the verdict-pass scope of three fixes scored resolved: readable native file selector, unbroken tablet pack prices, and explicit UTC history timestamps. This records that scoped verdict; it is not an independent whole-surface or live-provider certification. Seven-width synthetic browser acceptance and release limitations are recorded in docs/KILAS_TRANSLATOR_V1_STATUS.md.

Documentation compared PRODUCT.md, DESIGN.md, reference/document.md, current Audio templates/styles/script and audio_provider/service/store/routes/media/schema implementations. Current translate-768.png and result-390.png were inspected and show readable native file controls, intact tablet prices and UTC history date/time. The current source contains those resolved changes. The required latest packet comprises translate-320/360/390/430/768/1024/1440.png, voiceover-390.png, result-390.png, paywall-360.png and invoice-430.png under .impeccable/review; auxiliary pricing captures precede the fixes. This extension adds no global palette, typography, component or imagery rule. DESIGN.md and .impeccable/design.json were preserved.

Not canonized or repaired: PRODUCT.md retains the historical Assist-only audit authorization and undecided visual direction, while the incumbent DESIGN.md records the later white-workbench brief. That pre-existing context drift is reported without changing product/system files. Real provider quality, authenticated live operation, CI and deployment remain separate evidence boundaries.
