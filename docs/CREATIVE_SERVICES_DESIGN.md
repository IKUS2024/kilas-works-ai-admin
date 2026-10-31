---
name: Kilas Works Creative Services photo studio
description: Scoped implemented design record for the approved image-led Creative Services surface.
colors:
  paper: "#faf8f2"
  ink: "#20262a"
  muted: "#596167"
  orange: "#b83d12"
  action: "#c8460c"
  action-hover: "#a93608"
  dark: "#141e22"
  surface: "#fffefa"
  border: "#e1e2db"
  line: "#d8dddf"
  white: "#fff"
  inverse-muted: "#c8d1d0"
  inverse-focus: "#ffb591"
  field-border: "#bfc2c6"
  field-ink: "#202329"
  field-focus: "#bd4700"
typography:
  display:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "clamp(38px, 3.8vw, 58px)"
    fontWeight: 750
    lineHeight: 1.08
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "clamp(30px, 3.05vw, 43px)"
    fontWeight: 750
    lineHeight: 1.1
    letterSpacing: "-0.035em"
  title:
    fontFamily: "Manrope, system-ui, sans-serif"
    fontSize: "25px"
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
  image: "8px"
  mosaic: "10px"
  card: "12px"
  tag: "20px"
spacing:
  tight: "8px"
  card-inset: "10px"
  compact: "12px"
  service-gap: "18px"
  package-gap: "20px"
  medium: "24px"
  hero-gap: "32px"
  section-gap: "36px"
  desktop-gutter: "48px"
components:
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.white}"
    rounded: "{rounded.action}"
    padding: "12px 18px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.action}"
    padding: "12px 18px"
  service-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-inset}"
  package-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "25px"
  field:
    backgroundColor: "{colors.white}"
    textColor: "{colors.field-ink}"
    rounded: "{rounded.action}"
    padding: "9px 10px"
---

# Design System: Creative Services photo studio

## Overview

**Creative North Star: "Kilas Creative Studio"**

This record describes the implemented, user-approved composition: warm paper, closely tracked Manrope, orange actions, rounded photographic crops and a dark portfolio band. The generated service images are visibly disclosed illustrations. This applies only to `creative-services-site/` and its deterministic Client Hub copy; root `DESIGN.md`, `PRODUCT.md`, Assist, Finance and other application screens retain their existing authority.

Source authority is the cascade in `creative-services-site/index.html`: `assets/editorial.css`, then `assets/brief.css`, then `assets/studio-photo.css`. Frontmatter records reused values after those overrides. The October 31 approval supersedes the former no-new-raster rule for this surface only. See the [direction contract](../.impeccable/surfaces/creative-services-studio.md) and [release checkpoint](KILAS_CREATIVE_STUDIO_20261031.md).

**Key Characteristics:**

- Two-line headline beside a three-region image mosaic on desktop.
- Two visual service choices and six complete package cards.
- Warm paper, quiet borders and an inverse portfolio/footer band.
- Bilingual content and an editable enquiry with explicit WhatsApp opening.

## Colors

### Primary

Action orange fills the consultation and prepare-message controls; its deeper hover color provides feedback. Editorial orange remains the headline accent, service hover emphasis, feature checks and general keyboard outline. These roles are distinct in the current cascade.

### Neutral

Paper is the canvas and sticky-header background. Ink carries headings; muted carries explanation. Surface and border distinguish service/package cards; line separates quieter content. Dark grounds the portfolio and footer with surface/white text, inverse-muted explanation and inverse-focus outlines. Fields retain dedicated stroke, ink and focus colors.

**The Scoped Palette Rule.** Load this palette only with Creative Services and its generated copy; preserve shared application colors.

## Typography

Manrope is self-hosted with system sans fallbacks, variable weights (200–800) and `font-display: swap`. Inter is declared but is not the active body/display family. Existing font assets and licensing remain authoritative.

The desktop display, service-introduction headline, service title and body roles are recorded above. Hero description uses (17px/1.55) with a (36ch) measure. Service-card explanation uses (13px/1.55). Package titles retain (23px/650); prices use `clamp(25px, 2.4vw, 35px)` at (650) with tabular numerals. Portfolio/contact headings use (29px/700). Package details retain (14px).

At (1100px) and below the hero becomes `clamp(35px, 4.4vw, 48px)`; at (700px) it becomes `clamp(30px, 8.6vw, 42px)` with (1.1) line-height. Phone service titles become (21px), prices (34px), and form text (16px). Small disclosures and footer metadata are current implementation details, not a reusable body-text scale.

## Layout

Content is centered at maximum width (1280px), with desktop gutters (48px), then (28px) at the inherited (1000px) breakpoint. Phone gutters are (20px) at (700px), then (16px) below (359px). The desktop sticky header is a four-column grid with minimum height (76px).

Desktop hero columns use `.9fr 1.25fr` and a (32px) gap. The mosaic uses `1.25fr .9fr`, two rows, an (8px) gap and height (346px); its first image spans both rows. At (1100px) hero columns equalize and mosaic height becomes (320px). Phones stack copy above the mosaic, with height (214px), then (190px) below (359px).

Service introduction, portfolio and consultation use `.8fr 1.7fr` columns with a (36px) gap, tightened at (1100px). Service choices form two cards; at (700px) each becomes an image/text row with a (104px) image column, then (82px) below (359px). Packages use three columns with (20px) gaps and (25px) padding; phone cards stack with (22px) padding and (16px) gaps. Influencer add-ons retain a separate ruled comparison.

Consultation has three form columns above (1100px), two below, and initially collapsed message review. Opening review spans the grid. JavaScript enables mobile menu disclosure; without JavaScript navigation remains visible and the unused menu button stays hidden. The existing navigation script adjusts anchor offsets against the header.

## Elevation & Depth

No card shadows are used. Rounded image crops, off-white cards, fine borders, spacing and the inverse band provide depth. The header uses opaque paper and a bottom rule. Service images scale to (1.035) on hover over (.45s) with `cubic-bezier(.16,1,.3,1)`; arrows retain a short diagonal translation. Reduced motion removes transitions and image enlargement.

## Shapes

Cards and category images share the card radius; mosaic images use a tighter curve. Image inserts, actions and fields use smaller radii recorded above. Outlined package pills are informational. Icons/arrows are inline stroked SVG; the review chevron uses CSS borders.

## Components

### Actions and cards

Primary actions are orange/white. Outline actions retain transparent paper and ink, then invert to ink/white on hover. Package choices use orange borders and deeper-orange text, filling orange on hover. Desktop primary controls have minimum height (48px); mobile hero actions use (43px). General focus is a (3px) editorial-orange outline with (5px) offset; dark sections use inverse-focus. Field focus uses a (2px) outline with (3px) offset.

Each service card is a complete link combining image, title, explanation, package tags and arrow. Package cards retain full prices, outputs, feature lists and bottom-aligned choices. Hover imagery and arrow motion supplement text and visible keyboard focus.

### Illustration mosaic and portfolio

Two supplied illustrations are reused through `object-fit: cover` crops: event production and food-content filming on a phone. Responsive WebP sources cover (640/960/1536px) widths. Explicit dimensions reserve space; the main hero image is eager/high-priority, while later service/category/portfolio images are lazy. Meaningful images have ID/EN alt text; redundant crops use empty alt text.

**The Illustration Evidence Rule.** Retain visible illustration disclosures and the real `https://instagram.com/kilasworks` portfolio link. Generated images do not establish completed client work. The approved composition reference remains a design input, never a shipped background or page screenshot.

### Navigation and editable enquiry

Keep the existing identity, skip link and Home return. ID/EN controls expose `aria-pressed` and underline selection. Menu and panel navigation retain expanded state and focus handling. Category anchors preserve direct navigation.

Date, location and needs fields prepare a draft. Native details review contains an editable textarea; preparation/package choice reveals it. Only the explicit WhatsApp action opens WhatsApp, where the customer still decides to send. Disabled contact state remains differentiated. No automatic message sending is introduced.

## Do's and Don'ts

- **Do** preserve the existing identity, Manrope, warm paper and orange action hierarchy on this surface.
- **Do** retain both services, all six package facts/prices, Influencer add-ons and ID/EN wording.
- **Do** retain illustration disclosures, meaningful bilingual alt text and responsive local assets.
- **Do** preserve visible keyboard focus, reduced motion and editable message review.
- **Don't** apply this scoped system to Assist, Finance or shared application templates.
- **Don't** present generated or archived third-party images as Kilas Works client portfolio evidence.
- **Don't** ship the supplied composition reference as a page asset or background.
- **Don't** turn draft preparation into automatic WhatsApp sending.

Not canonized: decorative numbered section marks and small metadata/disclosures remain in the composition; they are not promoted into reusable heading/body guidance. This documentation pass makes no UI repairs or accessibility certification.
