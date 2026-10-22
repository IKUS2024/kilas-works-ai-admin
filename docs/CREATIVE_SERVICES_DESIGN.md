---
name: Kilas Works Creative Services studio
description: Scoped editorial studio surface for event and social media services.
colors:
  ink: "#20262a"
  muted: "#596167"
  orange: "#b83d12"
  line: "#d8dddf"
  paper: "#fafaf8"
  action-text: "#fff"
  action-hover: "#37444b"
  inverse-muted: "#c6cdce"
  inverse-accent: "#ffb591"
  package-border: "#b4bdc0"
  field-border: "#bfc2c6"
  field-ink: "#202329"
  field-focus: "#bd4700"
typography:
  display:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "clamp(48px, 6.7vw, 92px)"
    fontWeight: 650
    lineHeight: 1.08
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "clamp(34px, 4.3vw, 58px)"
    fontWeight: 750
    lineHeight: 1.15
    letterSpacing: "-0.035em"
  body:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.65
rounded:
  action: "6px"
  field: "8px"
spacing:
  mobile-gutter: "20px"
  compact-gutter: "28px"
  desktop-gutter: "48px"
  column-gap: "36px"
  section: "64px"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.action-text}"
    rounded: "{rounded.action}"
    padding: "14px 22px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  package-action:
    textColor: "{colors.ink}"
    rounded: "{rounded.action}"
    padding: "12px 16px"
  field:
    backgroundColor: "{colors.action-text}"
    textColor: "{colors.field-ink}"
    rounded: "{rounded.field}"
    padding: "11px 12px"
---

# Design System: Creative Services studio

## Overview

**Creative North Star: "Kilas Creative Studio"**

This scoped source-derived record captures Manrope display typography, quiet off-white, charcoal text and burnt-orange emphasis. It applies only to `creative-services-site/` and its generated application copy. The root `DESIGN.md` remains authoritative for the customer workspace and Finance. Home, chat, VO, Translator, Credits and Finance retain their existing systems.

Sources: `creative-services-site/assets/editorial.css` and retained `assets/brief.css`. The approved composition and task-specific imagery restrictions remain in `.impeccable/surfaces/creative-services-studio.md`.

**Key Characteristics:**

- Large, closely tracked Manrope headings.
- Open ruled service and package comparisons.
- Quiet paper canvas with a charcoal portfolio band.
- Visible focus and explicit editable contact preparation.

## Colors

### Primary

Orange emphasizes the studio headline, service hover text and feature checks. Ink fills the main action with white text; action-hover supplies feedback.

### Neutral

Paper is the canvas; ink carries headings, muted carries explanation, and line separates sections. The portfolio band reverses paper against ink, with inverse-muted explanation and inverse-accent hover/focus. Package and field borders distinguish controls without enclosing every service in a card.

**The Scoped Palette Rule.** Studio colors apply only to this standalone surface and its generated copy; retain the workspace and Finance palettes.

## Typography

Manrope is self-hosted with system sans fallbacks, variable weights 200-800 and `font-display: swap`. The font is copied byte-for-byte from `client-hub/static/fonts`; its original license text is retained with LF line-ending normalization. Inter is declared but is not the active body/display family.

Display and headline roles are recorded above. Service titles use `clamp(30px, 3vw, 42px)` at 650; package titles use 23px/650. Prices use `clamp(25px, 2.6vw, 37px)` at 650 with tabular numerals. Intro copy uses 18px/1.6. General paragraph measure is 65ch, service descriptions 40ch. Metadata is 11-13px.

At 600px and below, display becomes `clamp(36px, 9vw, 52px)` with line-height 1.12; category headings and prices become 34px, service titles 32px, and intro copy 16px. The separately loaded brief stylesheet retains 15px field text.

## Layout

Content is centered at a maximum 1248px width with 48px gutters, reducing to 28px at 1000px and 20px at 600px. The opaque sticky header has a minimum height of 88px; phone navigation wraps with a 76px minimum. Anchor offsets account for actual header height.

Service rows use `1fr 1.25fr auto`, become two columns at 1000px and one at 600px. Packages and add-ons use three equal columns and become ruled single-column phone stacks. Contact uses two columns with an 80px gap, then 40px, then one column with a 32px gap. Brief fields stack at 480px. The phone footer separates its copyright line and Home link in a column with a 12px gap.

## Elevation & Depth

No card shadows are used. Rules, spacing and the inverse portfolio band establish hierarchy. The sticky header uses paper and a bottom rule without blur.

## Shapes

Actions and the logo presentation use the action radius; fields use the field radius. Packages remain open columns. Icons are inline stroked SVGs, normally 22px, with smaller navigation/check icons and larger portfolio arrows. Return arrows use SVG rather than font glyphs.

## Components

### Actions and service rows

The primary action has a 50px minimum height. Package actions have a 48px minimum height, outlined package-border, and invert to ink/white on hover. General keyboard focus is a 3px orange outline with 5px offset; the portfolio band uses inverse-accent. The phone hero action fills available width up to 360px.

Service rows are whole links. Hover accents title/action text and moves the arrow 3px right and 3px up over `.2s cubic-bezier(.16,1,.3,1)`. Reduced-motion preference disables transitions. Package choices align to column bottoms.

### Navigation and language

Header links have a 44px minimum height. ID/EN buttons expose `aria-pressed` and underline selection; height remains 44px while phone width reduces from 44px to 40px. The skip link appears on focus. Panel navigation moves focus into the active region and restores it to the service choice on return.

### Brief fields

The form is at most 560px wide with visible labels, white fields, field-border strokes, 44px minimum control height and vertically resizable textareas. Form focus uses a 2px field-focus outline with 3px offset. The editable message and explicit WhatsApp action retain user review before sending; visually disabled contact actions use opacity `.6`.

## Do's and Don'ts

- **Do** preserve the existing logo asset and identity.
- **Do** retain readable ruled comparisons and both service categories.
- **Do** preserve package wording, prices, ID/EN behavior and editable contact review.
- **Do** retain SVG arrows, keyboard focus and reduced-motion behavior.
- **Don't** apply the studio system to workspace or Finance screens.
- **Don't** present inherited third-party gallery images as Kilas Works portfolio evidence; link to the actual `@kilasworks` Instagram.
- **Don't** introduce synthetic photography or new raster assets into this redesign.