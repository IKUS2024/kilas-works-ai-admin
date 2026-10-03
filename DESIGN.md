---
name: Kilas Works customer workspace
description: A quiet professional workbench for actual conversations, files and business tasks.
colors:
  canvas: "#fff"
  neutral-rail: "#f7f7f6"
  charcoal: "#202329"
  secondary-text: "#62666f"
  accent-text: "#bd4700"
  finance-accent-text: "#a43c00"
  action-fill: "#e96817"
  action-hover: "#f27a2a"
  action-text: "#22150c"
  selected: "#fff0e5"
  selected-border: "#edc9ae"
  divider: "#e4e5e7"
  input-border: "#c7c9cd"
  control-border: "#d5d7da"
  navigation-text: "#545963"
  neutral-hover: "#ececeb"
  user-surface: "#f5f5f4"
  success: "#20704a"
  error: "#b42330"
  warning: "#805a06"
  finance-surface: "#f7f7f6"
typography:
  headline:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.025em"
  section:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.025em"
  body:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.6
  response:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.75
  navigation:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.4
  finance-body:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  navigation: "7px"
  control: "8px"
  surface: "12px"
  composer: "14px"
spacing:
  sm: "8px"
  control: "12px"
  md: "16px"
  compact-section: "20px"
  section: "24px"
  lg: "32px"
  column-gap: "40px"
  desktop-gutter: "48px"
components:
  button-primary:
    backgroundColor: "{colors.action-fill}"
    textColor: "{colors.action-text}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
    textColor: "{colors.action-text}"
  button-secondary:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  input:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.control}"
  navigation-item:
    textColor: "{colors.navigation-text}"
    typography: "{typography.navigation}"
    rounded: "{rounded.navigation}"
    padding: "10px 12px"
  navigation-item-current:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.accent-text}"
  card:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.surface}"
  composer:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.composer}"
  user-message:
    backgroundColor: "{colors.user-surface}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.surface}"
    padding: "12px 16px"
---

# Design System: Kilas Works customer workspace

## Overview

**Creative North Star: "The Quiet Professional Workbench"**

The customer workspace feels calm, precise and trustworthy. White working surfaces, a neutral navigation rail and charcoal text let actual conversations, files and business tasks lead. Kilas orange carries identity and meaningful actions. The premium character comes from hierarchy, readable measures and consistent controls.

This records the implemented white workspace in `client-hub/static/kilas_premium.css`, its scoped Finance presentation layer and the current customer templates. The owner's 2026-10-03 pinned brief replaces the historical dark customer direction and the audit-only visual restrictions in PRODUCT.md. Existing capabilities and permissions remain product truth. The theme is opt-in through `kilas-light`; Assist and admin keep their existing visual systems. Finance now shares Manrope and the neutral workbench surface through a scoped presentation layer. Its established financial workflows and overall shell geometry remain; presentation adds readable controls and safe metric-text wrapping.

**Key Characteristics:**

- White working surfaces and neutral navigation.
- Manrope typography with a compact Finance body role.
- Deliberate orange identity, actions and selection states.
- Document-style assistant replies and compact persistent files.
- Task-led content with restrained borders and elevation.

## Colors

### Primary

Action fill identifies the main action; action text supplies its dark readable foreground. Accent text marks links, brand detail and focus. The selected tint and selected border mark active customer navigation, account tabs and subscription states. The hover fill provides immediate button feedback.

Finance accent text is the darker scoped orange used by Finance's existing orange and accent variables for readable text on its existing selected surfaces. Customer accent text remains the main customer orange.

**The Deliberate Orange Rule.** Use orange for identity, meaningful actions, links and selection; keep the main working canvas white.

### Neutral

Canvas is the main surface. Neutral rail differentiates navigation and supporting sections. Charcoal carries content, with secondary text for explanation and metadata. Divider separates sections; input and control borders distinguish editable fields and secondary actions. Navigation text and neutral hover support quiet rail interactions. User surface separates the user's message from document-style replies. Finance surface is a scoped compatibility color for existing Finance shells, fields and table headers.

Success, error and warning are semantic status colors. Preserve real status text as well as color; these tokens never imply that an operation completed.

## Typography

Manrope is self-hosted as a variable face (weights 200–800), with `font-display: swap` and system sans fallbacks. The customer body uses the body token; document replies use the response token. Page headings use headline, ordinary sections use title and section, and navigation uses its own compact role. Metadata is typically smaller (12–13px), the composer and authentication fields larger (16px), and the customer wordmark heavier (800).

The implemented display range is contextual: Home's task question spans `clamp(28px, 3.4vw, 40px)`, authentication spans `clamp(26px, 3vw, 36px)`, and the chat welcome spans `clamp(26px, 3vw, 36px)` at weight 650. These are surface expressions rather than a universal hero style. Subscription titles retain their observed size (32px).

**The Finance Density Rule.** Finance uses the compact finance-body role with Manrope; preserve its established task hierarchy rather than applying the customer heading ramp wholesale.

## Layout

Desktop customer navigation occupies a fixed rail (240px). The main wrapper starts beside it, uses a capped width (1160px) and generous gutters (42px vertical, 48px horizontal). Home content caps at 1040px. Sections share an observed spacing rhythm represented in the frontmatter, while specific shells keep their own geometry.

At 1100px and below, the customer wrapper reduces padding (32px). At 760px and below, the rail becomes an off-canvas drawer (`min(85vw, 310px)`), the main wrapper fills the viewport, and gutters become 28px vertical and 20px horizontal. At 360px and below, they reduce to 24px and 16px. Home's two supporting columns stack on mobile. Authentication moves from a two-column composition to a single readable column.

AI chat keeps history in the same rail as product navigation. The conversation uses a centered document column (760px) and a composer wrapper capped at 808px. The conversation scrolls within the shell while the composer remains below it. Connection content caps at 680px. Existing Finance geometry and responsive breakpoints remain specific to Finance.

**The Actual Work Rule.** Build hierarchy around the real task, conversation, connection or account state; do not populate decorative dashboards with synthetic metrics.

## Elevation & Depth

Customer content is mostly flat. Neutral surface differences and thin dividers supply structure. Cards have no customer-theme shadow. Menus and dialogs use the shared floating shadow (`0 12px 32px #20232912`); the composer uses a softer local shadow (`0 4px 14px #20232908`). Customer dialog backdrops use a translucent charcoal veil (`#20232966`). Finance retains its own existing layered components and scoped compatibility shadows; the flat customer treatment is not a mandate to restructure them.

Color and border transitions are brief (`.15s ease`); the mobile rail slides with `.18s ease`. The theme disables transitions and animations for reduced-motion preferences.

**The Content Before Chrome Rule.** Let spacing, borders and tonal surfaces organize ordinary content; reserve the customer floating shadow for menus and dialogs.

## Shapes

Controls use gently rounded corners, surfaces use a slightly broader radius, and the composer has its own soft enclosure. Navigation corners stay compact. The frontmatter records the reused radii. Borders remain thin and neutral. File previews retain their existing compact geometry and download affordances; no universal pill treatment is applied.

## Components

### Buttons

Primary customer actions use orange fill, dark text, a control radius and strong labels (14px, weight 700). Their padding is recorded above and their minimum touch height is 44px. Hover changes the fill; secondary actions use white, charcoal text and a control border, with neutral-rail hover. Disabled controls retain their labels with reduced opacity (.55). Authentication submits retain their existing full-width treatment and larger height (50px).

Account edit, logout and email-change actions retain their compact labels (13px) and minimum touch height (44px).

### Inputs / Fields

Customer fields use white backgrounds, visible neutral borders and charcoal text. Placeholders use secondary text, and the caret uses accent text. Authentication fields retain their observed inner spacing (12px 48px) and minimum height (50px); ordinary fields preserve their component-specific dimensions. Focus uses an orange outline (2px) offset from the control (3px). Native field semantics remain intact.

### Cards / Containers

Customer cards use white, divider borders and the surface radius with no shadow. Connections are separated by horizontal rules and generous spacing rather than summary dashboards. Existing account and subscription surfaces retain their established fields and handlers. Dialogs use viewport limits (`calc(100vw - 32px)` and `calc(100dvh - 32px)`) and the shared floating shadow.

### Navigation

Product navigation uses compact labels, a 44px minimum row height and neutral hover. Current customer product navigation uses selected tint with accent text; current chat-history items use neutral hover with charcoal text. These states are deliberately distinct. Home leads to Kilas AI, existing Finance and external Kilas Services; Connections and Settings expose actual account destinations. AI preferences and history remain reachable within the AI rail.

### Language preference

The shared language form offers Bahasa Indonesia, English, Español and 中文 (`id`, `en`, `es`, `zh`). A visible label, native select and explicit Apply action use 44px minimum touch heights, neutral borders and the existing orange focus outline. Selection applies on submission and persists in the `kilas_language` cookie for one year. UI controls use the selected language; user names, customer text and generated content retain their original language.

Finance places language and Home controls in its desktop sidebar and exposes a compact return row on mobile at 760px and below. Home returns to the same product start page across the customer navigation and Finance shells.

### Conversation and files

Assistant messages render as readable documents with Markdown headings, tables, code and sources. User messages use user surface, surface corners and comfortable inner spacing. The bottom composer uses a composer radius, input border, a subtle shadow and orange send action. Its textarea remains readable (16px) and the existing attachment, Stop and keyboard behavior is preserved. Files persist beside their originating message with existing private download links; pending files keep individual removal controls.

## Do's and Don'ts

### Do:

- Do use the opt-in customer theme and its recorded tokens for new customer surfaces.
- Do lead with the actual task and readable content.
- Do retain visible focus, meaningful labels and real status text.
- Do use the compact Finance body role while preserving its overall geometry and financial behavior.
- Do preserve persistent file links, chat history and existing permissions.

### Don't:

- Don't return the customer workspace to a dark primary background.
- Don't add synthetic metrics, decorative AI art or unrequested mode controls.
- Don't use the customer theme to restyle Assist or admin globally.
- Don't treat orange as the background for the whole workspace.

Not canonized: PRODUCT.md's audit-only authorization and undecided palette are historical drift superseded by the pinned October brief, not a new product restriction. The recorded system does not claim accessibility certification or deployment verification.
