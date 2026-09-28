# Kilas Assist — initial Impeccable UI audit

Date: 2026-09-28 WIB. Source: main `c0d27c2dabb99d1c68448524f0407f77440f5eab`.
Scope: technical UI audit, no implementation. Kilas Finance excluded.

## Implementation integrity verdict
Partial pass: the product has coherent Assist navigation, real contact/request terminology, explicit empty states and progressive disclosure. Repeated small functional text, inaccessible controls and refresh behavior still weaken the implementation. This is not evidence that a visual redesign is needed.

## Evidence and limits
- Read current source and latest release checkpoint, not historical phase requirements.
- Existing authorized owner session: Home, Latih Kilas, Lead list, Jobs and Inbox inspected in live Chrome at 1363×936. Jobs screenshot inspected; DOM/computed styles checked. No form submitted, message sent, connection launched, contact detail opened or Finance page visited. Contact-detail GET was deliberately avoided because the checkpoint documents lazy data repair there; its findings are source-only.
- Home, Jobs and Inbox measured without document-level horizontal overflow at the observed desktop width. This is not a mobile test.
- Bundled deterministic detector scanned seven Assist templates/partials; seven raw warnings in `docs/qa/kilas-impeccable-detector.json`. Static Jinja fragments do not resolve inheritance or every CSS cascade; line 0 is a detector limitation. Findings are triaged below, not blindly treated as defects.
- Shared `base.html` and `kilas_ui.css` were read for Assist rules only. No Finance analysis or recommendations. No whole-repository scan.
- No physical-device/touch, mobile viewport, zoom, screen-reader or complete keyboard journey verification. No latency, Core Web Vitals or server-load measurements. No WCAG certification or full production-health claim.

## Provisional audit health score
Scores are code-review estimates bounded by the evidence above, not accessibility or performance certification.

| Dimension | Score / 4 | Evidence |
| --- | --- | --- |
| Accessibility | 2 | Existing focus/skip link and named forms; missing Inbox and contact-profile labels |
| Performance | 2 | Hidden-tab/concurrency guards; frequent full-page polling and fragment replacement |
| Responsive design | 2 | Existing breakpoints; 32px pagination targets and very small mobile text; mobile untested |
| Theming | 2 | Existing variables mixed with local literal colors; no new theme requirement |
| Implementation integrity | 2 | Coherent product structure; repeated functional microtext and missing state semantics |
| **Total** | **10 / 20** | **Acceptable under Impeccable's rubric; targeted improvements needed** |

## Prioritized findings
8 grouped findings: P0 0, P1 2, P2 6, P3 0. No blocking task failure was demonstrated in this read-only sample.

### A1 — P1: Inbox filter has no accessible name
- Location: `client-hub/templates/inbox.html:62-68`.
- Live DOM: mode SELECT has zero labels and no aria-label; search INPUT also has no explicit label and relies on its placeholder.
- Impact: screen-reader/voice users cannot reliably identify the mode selector. Option text alone is not a control name.
- Standard: WCAG 4.1.2 for selector; explicit visible search labeling is also recommended.
- Recommendation: associate localized labels with each control; preserve field names and GET behavior. `$impeccable harden` scoped to Inbox filters.

### A2 — P1: Contact profile labels are not associated with controls
- Location: `client-hub/templates/customer_detail.html:43-46`.
- Source: four sibling label/input or textarea pairs have no `for`/matching `id`, wrapping label or aria-label. Placeholder text is generic for optional fields.
- Impact: assistive technology loses field purpose; clicking the visible label does not focus its input.
- Standard: WCAG 1.3.1 / 4.1.2. Source-verified; not exercised against private contact data.
- Recommendation: add matching IDs and labels without changing stored fields or validation. `$impeccable harden` scoped to contact profile.

### A3 — P2: Important text is too small
- Locations: `jobs.html:6-9`, `inbox.html:13-19`, Assist-only rules in `static/kilas_ui.css:101-110`.
- Detector reports 9px Job status, 10px action label, 10px Live/delivery text and 10–11px body metadata. Live Jobs computed styles confirm 9px status and 10px action label. Mobile Assist status/flow copy includes 9px source declarations.
- Impact: operational status is harder to scan, especially on phones or at reduced vision.
- Standard: usability finding; WCAG does not define a blanket minimum font size. Not automatically a contrast violation.
- Recommendation: increase only functional Assist text and re-check wrapping. `$impeccable typeset`.

### A4 — P2: Compact pagination targets shrink to 32px
- Location: `templates/_client_compact_style.html:17-19`.
- Source: 34px controls become 32px high/min-width below 520px, with 6px gaps. These anchors do not inherit the generic button minimum height.
- Impact: adjacent page controls are less comfortable to tap. Not observed in the current short list.
- Standard: below Impeccable's 44px usability target / WCAG 2.5.5 AAA target, not by itself a WCAG 2.2 AA failure (AA minimum is 24px with exceptions).
- Recommendation: Assist-scoped hit areas of at least 44px; verify narrow layouts. `$impeccable adapt`.

### A5 — P2: Inbox polls full page at 1.2-second intervals
- Location: `templates/inbox.html:290-324,381`.
- Source: every eligible tick fetches current full page with no-store and parses it into DOM, despite needing only conversation/thread fragments. Up to roughly 50 requests/minute per continuously visible tab when responses are fast; concurrency guard can lower this.
- Impact: unnecessary traffic, server work and DOM parsing. No measured navigation-delay attribution is claimed.
- Positive guardrails: pauses while hidden, prevents overlap, compares HTML and preserves open analyses / near-bottom scrolling.
- Recommendation: profile first, then consider conditional/fragment fetch and adaptive polling while retaining delivery semantics. `$impeccable optimize`; any endpoint change requires a separately authorized implementation task.

### A6 — P2: Refresh can replace a focused element
- Locations: `customer_detail.html:57-75`; `inbox.html:307-323`.
- Source: contact context is unconditionally replaced every successful 20-second refresh unless follow-up editor is open; Inbox replaces changed lists/threads. No active-element preservation is present in these branches.
- Impact: focused links/disclosures in replaced subtrees may disappear and keyboard position may be lost. This is a source-demonstrated risk, not a reproduced live focus-loss incident.
- Recommendation: preserve keyed nodes/focus, defer focused-subtree replacement, avoid unchanged replacement. Keep the existing follow-up-editor guard. `$impeccable harden`.

### A7 — P2: Selected contact stage is communicated through styling only
- Location: `customers.html:15-19`; selected pagination at `customers.html:64-67`.
- Source/live stage links lack aria-current; active state is only button class. Pagination similarly uses an active class without current-page semantics.
- Impact: nonvisual users have less direct confirmation of the selected filter/page; stage is indirectly available in the page count copy.
- Recommendation: add appropriate `aria-current` to current links; keep ordinary link behavior rather than inventing tab-widget keyboard rules. `$impeccable harden`.

### A8 — P2: Assist tokens are spread across shared and local styles
- Locations: `base.html:8-11`, `static/kilas_ui.css:2,48-83`, `customer_detail.html:7-17`, `_client_compact_style.html:5-6`.
- Source: root and kw-app variables overlap, while local status/surface colors are literal values.
- Impact: future tweaks can diverge or spill into Finance because shared styles serve both workspaces.
- Recommendation: record and scope existing Assist values before any token extraction. Preserve current appearance and keep shared/Finance rules untouched. `$impeccable extract` only after explicit implementation authorization.

## Detector triage
Seven raw findings collapse into A3, not seven additional defects. Jobs sizes were verified live; Inbox metadata sizes are confirmed in source, but populated delivery states were not observed in this session. The detector did not detect missing form-label associations or focus risks, which came from manual review. Static absence of warnings on other templates is not a pass. Generic preferences against system fonts, dark surfaces or existing card patterns are not grounds to override the user's preservation constraint. No false-positive suppression was added for the Assist warnings.

## Preserve these strengths
- Existing Assist-specific Home / Inbox / Customers / Jobs / More navigation.
- Indonesian document language, skip navigation and visible focus rules.
- Labeled training textarea/file input, optional collapsed answer preview and independent confirmation.
- Clear Lead empty-state explanation and concrete-action Jobs copy.
- Existing human review before follow-up, tenant boundaries, payment authority and production connection gates.
- Customer Insight remains inside contact detail. Current Selesai status is part of the latest implementation and is not reverted by this audit.

## Recommended later sequence — not executed
1. `$impeccable harden` Assist form labels and current-state semantics (A1, A2, A7).
2. `$impeccable harden` refresh focus behavior (A6).
3. `$impeccable typeset` functional status text, then `$impeccable adapt` mobile targets (A3, A4).
4. `$impeccable optimize` measured Inbox refresh cost (A5).
5. `$impeccable extract` narrowly scoped existing Assist tokens (A8), only if it can avoid Finance/shared changes.
6. `$impeccable polish` Assist, followed by a bounded audit and desktop/mobile/keyboard verification.

All recommendations remain unimplemented. No production deployment, database migration or data reset is needed for this audit.
