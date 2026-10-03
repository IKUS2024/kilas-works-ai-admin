---
name: Kilas Video scoped design extension
description: Planning and education within the existing Kilas customer workbench.
---

# Design System: Kilas Video scoped extension

## Overview

**Creative North Star: "The Quiet Professional Workbench"**

Video extends the incumbent white, Manrope, charcoal and orange customer workspace recorded in root `DESIGN.md`. It is a calm planning document and practical learning surface: users describe an idea, inspect a production plan, revise it and copy directions into their chosen tools. It introduces no replacement visual world or global token set.

Planning uses Operate mode; Belajar, Workflow and Tools use Read mode. Indonesian product copy distinguishes planning from video creation: the final video is made in an external tool. Root `DESIGN.md` remains the global authority; this document records only the implemented Video extension. Finance retains its separate type, layout and business behavior.

Evidence: `client-hub/templates/kilas_video/home.html`, `_result.html`, `_manage.html`, `client-hub/static/kilas_video.css`, `kilas_video.js`, the incumbent `kilas_premium.css`, `PRODUCT.md`, root `DESIGN.md`, and `docs/KILAS_VIDEO_V1_STATUS.md`. Existing local Chromium captures cover empty, result, copy-feedback, delete-dialog, Belajar, Workflow, Tools and provider-error states at widths spanning 320–1440px. These are synthetic local transport fixtures, not production generation evidence. Documentation sampled those supplied captures; no new browser, audit or detector run was performed.

**Key Characteristics:**

- White working canvas and a neutral navigation rail.
- Readable document hierarchy with thin horizontal dividers.
- Orange for meaningful action, selection, links and scene timing.
- Native disclosure, form and dialog semantics.
- Copy feedback and saved-plan actions available immediately after generation.

## Colors

Video uses the incumbent palette directly. Its local CSS repeats the existing values rather than creating independent palette tokens.

### Primary

Warm orange action fill (`#e96817`) and dark action text (`#22150c`) identify the submit action. Hover inherits the incumbent lighter orange (`#f27a2a`). Burnt orange text (`#bd4700`) marks selected tabs, links, active history, scene timing and the local focus outline. The selected peach surface (`#fff0e5`) indicates the current tab and product destination.

**The Deliberate Orange Rule.** Preserve the incumbent use of orange for meaningful actions and selection on a white working canvas.

### Neutral

White (`#fff`) carries forms and plan content. Charcoal (`#202329`) carries readable content; secondary gray (`#62666f`) supports guidance, metadata and statuses. The neutral rail surface (`#f7f7f6`) encloses prompt text and image previews. Thin divider gray (`#e4e5e7`), input gray (`#c7c9cd`) and secondary-control gray (`#d5d7da`) separate content and editable controls. Navigation gray (`#545963`) is declared locally; the inherited customer link cascade can render links orange, as seen in the supplied captures.

Error red (`#b42330`) accompanies explicit failure or delete-action text. Status words convey the state; color alone does not claim success.

## Typography

All Video text inherits the self-hosted Manrope variable family (200–800), with system sans fallbacks and `font-display: swap`. The effective incumbent heading hierarchy is page heading (30px, weight 700, line-height 1.2), section title (22px, weight 700, line-height 1.3), and subsection heading (18px, weight 700, line-height 1.4). Headings retain the shared tight tracking (`-.025em`). Storyboard scene headings use the local smaller role (16px); lesson summaries and tool names use 17px.

Plan paragraphs, lists and description values use 15px with line-height 1.7. Prompt blocks use the same proportional family (14px, line-height 1.75), preserve newlines and wrap long text. Labels are 14px and weight 600; metadata and guidance generally use 12–14px. Scene timing and plan metadata use tabular numerals. Editorial explanations use readable measures, generally 55–70ch.

The effective shared heading cascade wins over several lower-specificity local declarations: the rendered history title uses the shared section hierarchy, comparison labels use the shared subsection hierarchy, and the shared page-heading rule continues to apply on narrow screens. Their local 15px, 13px and 27px declarations are not new typography tokens for future surfaces.

## Layout

Video sits inside the incumbent customer shell: desktop navigation has a 240px rail and the wrapper uses its existing capped width and gutters. The local studio caps at 1180px, subject to the narrower enclosing wrapper. The planning workbench has a flexible main column, 220px history column and 40px gap. A thin left divider and 24px inner padding separate history. The heading has a 24px gap and 28px bottom margin; wrapping tabs have a divider, 12px bottom padding and 32px separation from the work area.

Planning starts with the idea textarea, optional controls in a disclosure, optional reference upload, scope explanation and primary submit. Empty-state examples follow a horizontal rule. Saved results remain in document flow below the composer, with a 36px top gap and 32px top padding. Plan sections use 28px separation and dividers; scenes use 24px vertical spacing. Concept and scene details use a label/value grid (100px plus a flexible value column). Supporting lists and lesson comparisons use two columns.

At 1100px and below, history moves below the main content with a top divider and its links use two columns. At 600px and below, the heading, submit row, plan header, section copy controls and tool rows stack; optional controls, supporting lists, comparisons and history links become one column. The details label column reduces to 76px and prompt padding to 16px. Tabs wrap naturally rather than forcing a horizontal scroll. History and long plan text allow word wrapping; prompt blocks wrap and scroll vertically within a 460px maximum height.

The existing shell switches to its mobile drawer at 760px, with a full-width wrapper and 20px horizontal gutters. Supplied 320px captures show this usable single-column form. More-specific incumbent wrapper declarations continue to govern narrow-screen gutters; the older 16px wrapper declaration at 360px is not a new Video layout commitment.

## Elevation & Depth

Video is flat by default. Thin dividers, neutral prompt enclosures and whitespace provide structure; there is no local decorative card-shadow system. The native delete dialog uses a white surface, thin divider border and translucent charcoal backdrop (`rgba(32,35,41,.3)`). Any shared dialog elevation remains inherited from the customer shell.

The plan has a short opacity arrival animation (250ms, ease-out), only when reduced motion is not requested. Shared customer controls retain short color transitions, and the incumbent reduced-motion override disables animation and transitions. Video does not add animated scrolling or an automatic completion focus transition.

## Shapes

Tabs inherit compact navigation corners (7px). Fields, secondary copy controls and reference images have gently rounded corners (8px); prompt enclosures and the delete dialog use the broader surface radius (12px). Image previews are contained thumbnails (88px square), preserving the complete reference inside a neutral enclosure. Pending reference removal uses a circular 36px control positioned at the thumbnail corner and an inline SVG cross with a filename-specific accessible label. Arrows in example and external-tool links are inline SVGs, hidden from assistive text.

## Components

### Composer and references

The idea field is a native required textarea with 3–2400 character bounds, a 136px minimum height, 16px padding and vertical resizing. Optional controls cover video type, platform, planned duration and destination tool, each initially following the idea. New plans accept optional JPG, PNG and WebP references through the native file picker; pending images show filenames and individual removal controls. Saved plans show their existing reference strip and hide the new-reference control.

Example rows insert an actual idea and focus the textarea. Successful generation changes the label to “Apa yang ingin kamu ubah?”, clears the input, uses a natural revision example and changes the primary action to “Perbarui rencana”. Completion does not refocus the composer or reopen the mobile keyboard.

### Buttons, focus and progress

Submit, new-plan and management buttons inherit the customer primary and secondary styles with a 44px minimum height. Local section copy buttons use white, a neutral border, 8px corners and 8px by 12px padding. Tabs, disclosures, example rows and history links keep generous interactive rows. Local keyboard focus uses a 3px orange outline with 3px offset. The reference removal control is the observed smaller exception; it is not a general touch-target rule.

Submitting blurs the idea field, disables submit and the picker, sets `aria-busy`, hides the previous error and announces “Menyusun konsep, storyboard, dan arahan produksi…” through a polite status region. Disabled Video controls use reduced opacity (.65) and a waiting cursor. Completion announces that the plan is saved and ready for copying or revision, then restores the controls.

### Plan and copying

The result is an article with a title, duration/aspect/tool metadata, reference thumbnails, concept and objective/hook details. Script appears only when present. Storyboard scenes show numbered headings, planned timing and concrete visual/action/camera/light/audio/text details. Supporting lists, closing text, master prompt, destination prompt and usage guidance appear as relevant.

Users can copy everything, script, storyboard, master prompt or platform prompt. Successful copy immediately appends “· Tersalin” to the clicked button and announces “Tersalin. Siap ditempel ke tool pilihanmu.” Previous button feedback resets when another copy action starts. Clipboard failure marks the clicked action “· Belum tersalin” and provides manual-copy guidance. The primary mechanism is the secure-context Clipboard API, with a textarea fallback. Prompt text remains visible and selectable.

### History and management

“Rencana kamu” lists owner plans, highlights the current item, shows “Belum selesai” when appropriate and provides previous/next pagination when available. The empty history message explains when plans appear. After an AJAX generation or revision, the result and management partial are both inserted immediately, the current project/version and URL are updated, and the latest title moves to the top of history without duplicating the current link.

“Kelola rencana” contains a required name field (60 character maximum), save-name and duplicate forms, and a delete trigger. Deletion opens a native modal dialog with “Batal” and “Hapus rencana”; its explanation accurately says the plan will be hidden from history. The confirmation submits the explicit delete value. These management forms use their existing server-backed behavior; they are not described as AJAX actions.

### Errors

Generation errors appear beside the composer in a `role="alert"` region with error text; progress clears and controls become usable again. Existing rendered plan content is replaced only after a successful response, preserving the prior visible plan on failure. User guidance supports trying again; the connection fallback directs the user to check history before retrying. The supplied error captures demonstrate localized recovery copy with the entered idea retained.

On a parsed server failure, the client renews the operation key for retry. When the response identifies an owned saved project, it retains that project's ID, version and URL, clears transient image previews and hides the upload control. Retrying uses the same project and its saved references rather than uploading them again. Provider-failure guidance explains that the idea and previous plan remain in history; transport failures still direct the user to check history before retrying. This recovery behavior changes no visual styling.

### Education and tool destinations

Belajar contains 19 native lesson disclosures, with the first open, practical explanation, weak/better comparisons and the reason the better direction helps. Workflow presents product, UGC and cinematic steps as ordered lists, with a route back to start a plan. Tools groups the six official destinations into clip creation and final editing; each row contains a conservative description and an accessible official-site link opening in a new tab with `noopener noreferrer`. The text explicitly explains that Kilas is not connected to these tools and that their own access and feature conditions apply.

## Do's and Don'ts

- Do inherit the incumbent customer palette, Manrope hierarchy and shell geometry.
- Do keep generated directions readable, selectable and divided into practical sections.
- Do preserve local copy feedback, immediate fresh-plan management and explicit error recovery.
- Do retain native disclosure/dialog semantics, visible focus and reduced-motion behavior.
- Don't imply that Video renders, publishes or connects to external tools.
- Don't extend Video styling into Finance, Assist, admin or shared global templates.
- Don't promote ineffective local CSS declarations or isolated small controls into global rules.

Not canonized or repaired: PRODUCT.md still records the earlier Assist audit-only authorization and undecided aesthetic; root DESIGN.md already identifies that historical drift as superseded by the pinned October customer brief. Root DESIGN.md also describes smaller wrapper gutters at 360px that more-specific incumbent shell rules override in the captured Video view. The local/shared heading and link cascade differences above are documented as current inheritance, not reasons for a global repair. No global system, sidecar, product context or UI source was changed by this documentation pass.

Review disposition supplied by the final reviewer: **ship**, with all three material fixes resolved (local copy feedback, immediate AJAX-generation management, inline SVG icons). This documents that disposition and the final source; it does not claim deployment, production generation or accessibility certification.
