---
name: Kilas AI six-reference surfaces
description: The implemented white and peach AI workspace, with a separate dark voice-call state.
colors:
  canvas: "#fff"
  ink: "#111b2b"
  muted: "#747c8e"
  accent: "#ed5105"
  orange-start: "#ff841d"
  orange-end: "#f45100"
  peach-atmosphere: "#fff4eb"
  peach-selected: "#fff1e6"
  selected-border: "#ff650c"
  divider: "#e5e5e9"
  field-border: "#d4d7df"
  quiet-surface: "#faf9f8"
  focus: "#f17023"
  call-canvas: "#09131c"
  call-surface: "#0e1c28"
  call-field: "#152534"
  call-ink: "#f8fbff"
  call-muted: "#bad1e5"
  call-identity: "#ffdfb7"
  call-end: "#ff202c"
typography:
  welcome:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "clamp(28px, 3.6vw, 42px)"
    fontWeight: 800
    lineHeight: 1.25
    letterSpacing: "-0.035em"
  wordmark:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: "-0.04em"
  voice-title:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 800
    letterSpacing: "-0.035em"
  translator-title:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "32px"
    fontWeight: 800
  feature-label:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 500
    lineHeight: 1.3
  script:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "17px"
    lineHeight: 1.6
  primary-label:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 700
  call-title:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "34px"
    fontWeight: 750
    letterSpacing: "-0.025em"
rounded:
  field: "12px"
  feature: "14px"
  selector: "16px"
  drawer: "18px"
  call-settings: "20px"
  translator: "24px"
  composer: "32px"
  capsule: "40px"
  circle: "50%"
spacing:
  compact: "8px"
  row: "10px"
  control-gap: "12px"
  paired-gap: "14px"
  control: "16px"
  section: "20px"
  heading-gap: "22px"
  drawer-gutter: "24px"
  panel: "28px"
  desktop-header-gutter: "32px"
components:
  feature-tab:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.feature-label}"
    rounded: "{rounded.feature}"
    padding: "12px 8px"
    height: "56px"
  feature-tab-selected:
    backgroundColor: "{colors.peach-selected}"
    textColor: "#ee5105"
  model-selector:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.selector}"
    padding: "12px 16px"
    height: "58px"
  composer:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    rounded: "{rounded.composer}"
    padding: "8px"
  translator-action:
    backgroundColor: "linear-gradient(115deg,#ff841d,#f45100)"
    textColor: "#fff"
    typography: "{typography.primary-label}"
    rounded: "{rounded.selector}"
    height: "62px"
    width: "100%"
  script-field:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.script}"
    rounded: "{rounded.field}"
    padding: "16px 16px 40px"
    height: "150px"
  call-settings:
    backgroundColor: "{colors.call-surface}"
    textColor: "{colors.call-ink}"
    rounded: "{rounded.call-settings}"
    padding: "22px"
  call-end:
    backgroundColor: "{colors.call-end}"
    textColor: "#fff"
    rounded: "{rounded.circle}"
    size: "70px"
---

# Design System: Kilas AI six-reference surfaces

## Overview

**Creative North Star: "The Kilas Reference Workspace"**

This records the implemented six-image direction approved for AI Chat, its drawer, AI Call, live Translator and Voice Over. White working surfaces, peach accents, generous rounded controls and the existing black/orange Kilas identity follow the supplied references. AI Call switches to a dedicated dark viewport; the surrounding product remains light.

The source of visual authority is [the six-reference contract](KILAS_SIX_REFERENCE_IMPLEMENTATION.md), the current `client-hub/static/kilas_reference_ui.css`, participating templates and their existing handlers. This guide describes the finished correction batch, including the centered closed-drawer canvas, full narrow labels, Call header/status capsule and compact Voice Over spacing. It does not imply a deployment or final reviewer verdict.

**Key Characteristics:**

- White/peach AI workspace with deliberate orange actions and selection.
- Existing Kilas logo asset and self-hosted Manrope.
- Header and overlay drawer at every width; centered work without a reserved rail.
- Separate setup and running compositions for Translator and Call.
- Actual scripts, histories, account state and controls remain authoritative.

Scope is the AI reference stylesheet and surfaces that load it. Body-level workspace overrides require the reference header; the Call dialog has its own ID scope. Finance, Assist, admin and Creative Services retain their existing systems. The root design frontmatter and global sidecar tokens are preserved. The existing sidecar schema already supports `extensions.scopedSurfaces`; its `kilas-ai-reference` entry extends this document with scoped metadata, shadows, motion, breakpoints and component previews.

Historical context is intentionally retained: `PRODUCT.md` still describes its original audit-only authorization, and the earlier AI drawer/Audio briefs describe prior compositions. The owner's six-image direction supersedes those compositions for these named surfaces. This is not a rewrite of product capabilities or a global theme migration. The existing root sidecar timestamp and its stale hint are preserved; the new scope has its own date. The unrelated unset build-path context warning is also unchanged.

## Colors

### Primary

Orange carries actionable emphasis: the reference accent marks identity and focus-related detail, while the warm gradient runs from orange-start to orange-end on light-surface primary actions. Selected tabs use peach-selected with selected-border and an orange label. Call Start has its observed endpoint variation (`#ff5700`) in the scoped sidecar. Voice selections retain their local pale peach fill and orange border.

### Neutral

Canvas and ink carry the working surface and main text. Muted supports explanation, estimates and helper copy. Divider and field-border distinguish tabs, selectors and editable fields. Quiet-surface groups drawer products/history and secondary tools. Peach-atmosphere supplies the soft background circles and selected voice surface.

Call uses call-canvas, a slightly lifted call-surface, call-field, call-ink and call-muted. The identity disk uses call-identity, with translucent warm rings; the destructive call-ending control uses call-end. These colors belong to the Call state and do not replace the light workspace palette.

**The Scoped Reference Rule.** Apply these tokens only to the named AI reference surfaces; preserve Finance and the other existing product themes.

## Typography

Manrope remains the display and body family, with system sans fallbacks and the existing self-hosted variable font. Welcome and section titles are strong and tightly tracked; the frontmatter records their desktop roles. The Kilas wordmark remains text beside its orange Works segment, while the black/orange identity is the existing `kilas-new-chat-logo-lossless.webp`, not an approximation or generated replacement.

The desktop welcome uses its clamp; at 760px and below it is fixed at 30px. Translator setup titles reduce to 28px, while active Translator keeps a 32px title. Voice Over reduces from 34px to 30px. Header wordmark size reduces from 30px to 26px, then 23px at 390px and below; the compact chat header uses 22px. Tabs use 16px desktop, 14px mobile and 12px at the narrowest breakpoint. Model labels wrap in full rather than ellipsizing. The script stays readable at 17px with its recorded line height; helper text has its existing compact scale.

Call's desktop heading reduces to 30px on mobile and 28px at 360px and below. Short-height layouts further reduce the heading and identity illustration to preserve usable controls. Labels, estimates, statuses and content retain their distinct hierarchy rather than inheriting one global heading scale.

## Layout

The desktop header is 88px high with 32px horizontal gutters. Its hamburger, KilasWorks link and profile sit across the full viewport. Main content is centered: general wrap caps at 1100px, chat at 1040px, the chat interior at 880px, paired model controls at 760px, and feature/audio surfaces at 900px. A closed drawer reserves no horizontal rail space. The drawer overlays at `min(76vw,370px)`, limited to `calc(100vw - 44px)`, with 28px/24px padding and viewport-height scrolling.

Chat follows the visible viewport using the existing viewport-height variable: models first, centered greeting/logo in flexible remaining space, then three feature tabs and the bottom composer. The ordinary page and conversation scroll behavior remain in their existing handlers. Desktop models share a row; at 360px and below they stack as full-width controls. The three feature labels remain complete, with icons above labels and at least 62px row height at that width.

At 760px and below the header is 82px high with 20px gutters. At 390px and below header gutters reduce to 12px and content to 14px. Existing keyboard/magnification compact mode reduces the chat header to 44px, uses 8px content gutters, and keeps secondary controls in its options panel. Its optional hint is hidden to preserve the working area.

Translator setup uses a centered 760px panel with 28px padding and a vertical language pair separated by Swap. Active Translator removes that panel enclosure, centers the identity orbit and presents opposing direction cards with a full-width End action. Mobile active padding is 10px/4px. It remains within the current light reference page, retaining feature navigation and header.

Voice Over uses a single primary working column and two voice-choice cards. At 360px and below the choices and Record/AI Assist tools stack. The script field is 150px tall and vertically resizable. The final correction removes excess selector/sample/editor spacing: script-workspace top gap is 8px and sample bottom gap is 8px. History starts closed and opens intentionally through the History control.

AI Call is a native modal dialog positioned to the visible viewport. Running Call has five rows: header chrome, title/status, a scrollable body, the status capsule and footer actions; setup hides the capsule and uses four rows. Body/footer cap at 560px. The outer dialog clips overflow, keeping the brand, title, real status capsule and controls in place; only the body scrolls, with 12px bottom clearance and 24px scroll padding. The existing script moves the capsule to a direct dialog child before the footer. At 600px and below the dialog uses 20px horizontal padding. At 360px and below its settings/labels tighten while selects remain at least 48px. Between 441px and 740px viewport height the active identity compresses to 140px, with tighter summary/name spacing. Short-height breakpoints at 620px and 440px further adapt or hide artwork and condense fields while retaining the header and call actions. Taller mobile viewports use the 164px running identity. The 1000px desktop rule adjusts setup spacing only.

## Elevation & Depth

The light surface uses thin borders and soft warm shadows rather than heavy panels. The drawer has a side shadow and a translucent blurred backdrop; model selectors, tabs and composer have light ambient shadows. The translator setup panel and active identity use similarly restrained depth. The scoped sidecar records their exact values. Call uses darker tonal layers, outlined circles and concentric warm identity rings rather than white cards.

Drawer motion is `.2s ease`. The existing ordinary control state transitions remain inherited where applicable. Reduced-motion preference disables animations and transitions throughout the reference workspace and Call. No new raster art, animation asset or external font dependency is introduced.

## Shapes

Use the recorded radii by component: fields are compact rounded rectangles, selectors and primary Translator actions broader, setup panels broader still. The composer is a soft capsule with round attachment, Send and Call affordances. The drawer has rounded right corners only. Translator directions have 18px corners; Call settings use their separate radius and the status capsule uses capsule corners. Identity disks and audio actions are circular. Native selects, radios and checkboxes preserve their semantics.

## Components

### Header, drawer and profile

The hamburger opens the existing drawer at desktop and mobile sizes. New chat uses a prominent peach row; Library and Products use peach icon tiles. Products expands through native details, and saved chats retain their real links, title actions, pagination and empty state. Profile remains available in the header, drawer and Call chrome. Existing drawer focus management, Escape/backdrop close and return focus stay in the shared handler. The reference design does not restore a permanently occupied desktop rail.

### Models, tabs and composer

Text and image model selectors retain the existing menu selection and provider marks. Feature navigation exposes AI Chat, Translator and Voice Over with active-state semantics. The chat composer keeps the existing attachments, Send, Stop, keyboard behavior and Call launch, with the new capsule enclosure and orange circular Send action. Full labels remain available at 320px. Focus uses the recorded two-pixel focus color with a three-pixel offset on light surfaces; ordinary controls retain their existing minimum 44px target convention.

### AI Call dialog

Setup shows the original logo, title, guidance, mode/persona controls, language-learning fields or roleplay scenario when relevant, and explicit Roast consent. Opening the dialog does not begin a call; Start does. A busy chat or unmet consent keeps Start disabled. Setup is represented by the existing runtime state `ended`; running states include connecting, reconnecting, listening and speaking.

Running Call shows centered identity rings, chosen mode/persona, actual status and the status capsule. The capsule mirrors the live status but is decorative to assistive technology to avoid duplicate announcements; it stays in its own pinned row above the controls rather than scrolling with the identity. Mute disables captured tracks, Hold suppresses input/output, Speaker controls output gain, and End keeps the existing cancellation handler. Their real `aria-pressed` states are preserved. Stop audio / Normal ends the current session and resets its mode. Close, Escape, page exit and hidden-tab cleanup end the session through the existing lifecycle; close restores launcher focus. Captions, source links, retry/error guidance and account/provider gates continue to reflect real session state.

### Translator

Setup retains native source/destination selectors, Swap and explicit microphone consent before Start. Language identity uses existing Indonesian/English flags where applicable; localized language names come from `Intl.DisplayNames` when available, and semantic selected values remain authoritative. The account-scoped preference saves only the language pair, never consent or audio, and prevents equal source/destination languages. Start reveals the direction choices; selecting a direction starts its session. Active mode presents two speaking directions with pressed-state selection, real listening/status feedback and End. Backgrounding stops capture while keeping the active screen until explicit End. The identity orbit and direction cards express the reference; no fake transcript or provider success is introduced.

### Voice Over

Voice choices expose the existing My Voice flow and ready-to-use Kilas Voice selector. Sample playback is available only for voices with a real sample. The My Voice shortcut selects the personal option and focuses saved voices. The fresh script editor is empty unless an explicit handoff or content draft supplies text; reopening a result keeps its existing job/result workflow. History opens intentionally and keeps existing owner-scoped pagination, status, downloads and result actions.

The script cap is **4,000 characters**, matching the existing backend and both original/translated textarea limits; a different reference-image number is not a new product limit. The counter uses `Intl.NumberFormat` with the document language. Paste is clipped to the actual textarea limit and dispatches the existing input event; denied clipboard access gives localized guidance and returns focus to the editor. Record Script, AI Assist, duration estimates and translation remain connected to their existing handlers. Estimates remain explicitly approximate; translation preserves the source and exposes an editable result for review. Provider/account state still controls Generate availability.

### Language and locale

UI labels use the existing `ui_t`, `KilasUI` and explicit-copy module helpers. UI language preferences (`id`, `en`, `es`, `zh`) remain separate from Call practice/explanation languages, Translator source/destination and voice script language. Call Connecting/Reconnecting dictionary entries retain the exact source punctuation, including ellipsis forms, so selected-language status does not fall back to Indonesian through a key mismatch. User content, scripts, generated replies, names and saved history are never passed through a blanket UI translation. Existing profile language controls, preference persistence, CSRF fields, account/tenant checks and consent gates remain unchanged by presentation. Localized long labels retain full text rather than being replaced with fixed English abbreviations.

## Do's and Don'ts

- Do keep the genuine existing Kilas identity and self-hosted Manrope.
- Do use the six-reference contract and current scoped CSS when extending these surfaces.
- Do preserve complete labels, visible focus, actual runtime state and the existing controls.
- Do keep UI locale separate from user content and media language settings.
- Do preserve the 4,000-character script cap, fresh entry and intentional history access.
- Don't apply this surface palette or geometry to Finance, Assist, admin or Creative Services.
- Don't replace real handlers, provider gates, consent or persistent histories with visual stand-ins.
- Don't infer successful provider audio, deployment or accessibility certification from synthetic captures.

Evidence: current local review captures under `.impeccable/review/` cover chat, drawer, Call setup/connecting, Translator setup/active and Voice Over at widths 1440, 820, 412, 390 and 320. This documentation pass inspected representative final captures and the current source. The original six PNGs remain in the sibling task `references/` directory. Final review, test and deployment outcomes belong to the release report; this guide records the implemented design only.
