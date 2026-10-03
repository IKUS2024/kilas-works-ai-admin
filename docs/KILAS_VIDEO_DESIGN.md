---
name: Kilas Video V2 scoped design extension
description: One editorial production workspace within the existing Kilas customer workbench.
---

# Design System: Kilas Video scoped extension

## Overview

**Creative North Star: "The Quiet Professional Workbench"**

Video V2 extends the incumbent white, Manrope, charcoal and orange customer workspace recorded in root `DESIGN.md`. The pinned direction is one editorial production workspace: users describe an idea, inspect the latest brief and storyboard, revise the same project and copy production prompts into their chosen tools. It introduces no replacement visual world or global token set.

The workspace uses Operate mode. Indonesian explanations lead into English production prompts. The central document contains the active project and composer above its latest plan; desktop support navigation contains the outline, project history and management. V2 removes the former Plan/Belajar/Workflow/Tools tab presentation. Root `DESIGN.md` remains the global authority; this document records only the implemented Video extension. Finance retains its separate type, layout and business behavior.

Evidence: `client-hub/templates/kilas_video/home.html`, `_result.html`, `_manage.html`, `client-hub/static/kilas_video.css`, `kilas_video.js`, the incumbent shell, `video_brief.py`, `video_routes.py`, `video_adapters.py`, `PRODUCT.md`, root `DESIGN.md`, and `docs/KILAS_VIDEO_V2_SURFACE.md`. Supplied local Chromium evidence in `.impeccable/review/video-v2/` includes full-page replacement-chain and scrolled copy-state captures at 320, 360, 390, 430, 768, 820, 1024 and 1440px. This documentation pass sampled full-page replacement-chain captures at 320/1440px and scrolled copy-state captures at 320/1024/1440px, and checked the complete capture inventory. These are synthetic local fixtures, not production generation or live AI-quality evidence. No new browser, audit or detector run was performed. No shipping raster assets were added; synthetic reference images remain QA data.

**Key Characteristics:**

- White working canvas and a neutral navigation rail.
- One active project, composer and latest plan with thin horizontal dividers.
- Stronger creative-direction hierarchy and a distinct Master Prompt enclosure.
- Orange for meaningful action, selection, links and scene timing.
- Native disclosure, form and dialog semantics.
- Copy feedback and saved-plan actions available immediately after generation.

## Colors

Video uses the incumbent palette directly. Its local CSS repeats the existing values rather than creating independent palette tokens.

### Primary

Warm orange action fill (`#e96817`) and dark action text (`#22150c`) identify the submit action. Hover inherits the incumbent lighter orange (`#f27a2a`). Burnt orange text (`#bd4700`) marks revision context, links, active history, scene timing and the local focus outline. The selected peach surface (`#fff0e5`) indicates the current product destination and text selection.

**The Deliberate Orange Rule.** Preserve the incumbent use of orange for meaningful actions and selection on a white working canvas.

### Neutral

White (`#fff`) carries forms and plan content. Charcoal (`#202329`) carries readable content; secondary gray (`#62666f`) supports guidance, metadata and statuses. The neutral rail surface (`#f7f7f6`) encloses prompt text and image previews. Thin divider gray (`#e4e5e7`), input gray (`#c7c9cd`) and secondary-control gray (`#d5d7da`) separate content and editable controls. Navigation gray (`#545963`) is declared locally; the inherited customer link cascade can render links orange, as seen in the supplied captures.

Error red (`#b42330`) accompanies explicit failure or delete-action text. Status words convey the state; color alone does not claim success.

## Typography

All Video text inherits the self-hosted Manrope variable family (200–800), with system sans fallbacks and `font-display: swap`. The effective page heading remains 30px, weight 700 and line-height 1.2. The active project heading declares 28px, reducing to 24px at 600px; the result title uses 24px. Plan section headings use 22px, reducing to 20px at 600px. Headings retain the shared tight tracking (`-.025em`). Storyboard scene headings use 16px; production-list headings use 15px. Creative-direction story text uses 18px and line-height 1.75, reducing to 16px on narrow screens.

Plan paragraphs, lists and description values use 15px with line-height 1.7 and a 72ch maximum measure; the story uses 68ch. Prompt blocks use the same proportional family, preserve newlines and wrap long text: platform prompts use 14px and the emphasized Master Prompt uses 15px, both with line-height 1.75. Labels are 14px and weight 600; metadata and guidance generally use 12–14px. Scene timing and plan metadata use tabular numerals.

The effective shared heading cascade wins over lower-specificity local declarations: history and outline headings use the shared section hierarchy, and the shared page-heading rule continues to apply on narrow screens. The ineffective local 15px and 27px declarations are not new typography tokens for future surfaces.

## Layout

Video sits inside the incumbent customer shell: desktop navigation has a 240px rail and the wrapper uses its existing capped width and gutters. The local studio caps at 1180px, subject to the narrower enclosing wrapper. The workbench has a flexible document, 220px support column and 40px gap. A thin left divider and 24px inner padding separate outline, history and management. The support column sticks 24px from the viewport top. The page heading has a 24px gap and 28px bottom margin; the active project header has a divider, 20px bottom padding and 24px following space.

Planning starts with the idea textarea, optional controls in a disclosure, optional reference upload, scope explanation and primary submit. Empty-state examples follow a horizontal rule. Saved results remain in document flow below the composer, with a 36px top gap and 32px top padding. Plan sections use 28px separation and dividers; scenes use 24px vertical spacing. Concept and scene details use a label/value grid (100px plus a flexible value column). Production supporting lists use two columns.

At 1100px and below, history moves below the document with a top divider and its links use two columns. At 1000px and below, support navigation becomes nonsticky and the outline is hidden. The intermediate 1001–1100px range retains the outline and sticky positioning in the stacked support section. At 600px and below, the heading, submit row, plan header and section copy controls stack; optional controls, production lists and history links become one column. The details label column reduces to 76px and ordinary prompt padding to 16px. Long text wraps; ordinary prompt blocks scroll vertically within a 460px maximum height. Master Prompt uses a neutral enclosure with 28px padding and a white inner text surface capped at 640px; outer padding becomes 20px vertically and 16px horizontally on narrow screens. Mobile places composer first, then the plan and prompts, then history and management.

The existing shell switches to its mobile drawer at 760px, with a full-width wrapper and 20px horizontal gutters. Supplied 320px captures show this usable single-column form. More-specific incumbent wrapper declarations continue to govern narrow-screen gutters; the older 16px wrapper declaration at 360px is not a new Video layout commitment.

## Elevation & Depth

Video is flat by default. Thin dividers, neutral prompt enclosures and whitespace provide structure; Master Prompt emphasis uses a neutral outer enclosure and white inner text surface. There is no local decorative card-shadow system. The native delete dialog uses a white surface, thin divider border and translucent charcoal backdrop (`rgba(32,35,41,.3)`). Any shared dialog elevation remains inherited from the customer shell.

The plan has a short opacity arrival animation (250ms, ease-out), only when reduced motion is not requested. Shared customer controls retain short color transitions, and the incumbent reduced-motion override disables animation and transitions. Video does not add animated scrolling or an automatic completion focus transition.

## Shapes

Shared navigation retains compact corners (7px). Fields, copy controls, reference images and inner Master Prompt text have gently rounded corners (8px); prompt enclosures and the delete dialog use the broader surface radius (12px). Image previews are contained thumbnails (88px square), preserving the complete reference inside a neutral enclosure. Pending reference removal uses a circular 36px control, increasing to 44px at 600px and below, with an inline SVG cross and filename-specific accessible label. Example arrows are inline SVGs hidden from assistive text.

## Components

### Composer and references

The idea field is a native required textarea with 3–2400 character bounds, a 136px minimum height, 16px padding and vertical resizing. Optional controls cover video type, platform, planned duration and destination tool, each initially following the idea. New plans accept optional JPG, PNG and WebP references through the native file picker; pending images show filenames and individual removal controls. Saved plans show their active reference strip when the canonical brief allows it and hide the new-reference control.

Example rows insert an actual idea and focus the textarea. Successful generation updates the active project title/version, reveals “Revisi rencana aktif”, changes the label to “Ubah atau sempurnakan rencana”, clears the input, uses a natural revision example and changes the action to “Perbarui rencana”. Completion does not refocus the composer or reopen the mobile keyboard. “Rencana baru” starts a separate workspace.

### Buttons, focus and progress

Submit, new-plan and management buttons inherit the customer primary and secondary styles with a 44px minimum height. Local section copy buttons use white, a neutral border, 8px corners and 8px by 12px padding. Disclosures, example rows and history links keep generous interactive rows. Local keyboard focus uses a 3px orange outline with 3px offset. The reference removal control is the observed smaller exception; it is not a general touch-target rule.

Submitting blurs the idea field, disables submit and the picker, sets `aria-busy`, hides the previous error and announces that creative direction, storyboard and production prompts are being assembled and reviewed through a polite status region. Disabled controls use reduced opacity (.65) and a waiting cursor. Completion announces the saved plan, then restores the controls. Section copy actions also have a 44px minimum height.

### Plan and copying

The result is an article with title, version/duration/aspect/tool metadata and active reference thumbnails. Creative direction leads into storyboard and production directions. Scenes show timing and available visual/action/camera/light/environment/audio/continuity/text details. Production lists cover shot list, B-roll, continuity, preservation and failure prevention. Script, closing text and CTA appear when present. Master Prompt, destination prompt and external production guidance complete the document. The desktop outline links to creative direction, storyboard, production and Master Prompt.

Users can copy everything, script, storyboard, master prompt or platform prompt. Successful copy immediately appends “· Tersalin” to the clicked button and announces “Tersalin. Siap ditempel ke tool pilihanmu.” Previous button feedback resets when another copy action starts. Clipboard failure marks the clicked action “· Belum tersalin” and provides manual-copy guidance. The primary mechanism is the secure-context Clipboard API, with a textarea fallback. Prompt text remains visible and selectable.

### History and management

“Rencana kamu” lists owner plans, highlights the current item, shows “Belum selesai” when appropriate and provides previous/next pagination when available. The empty history message explains when plans appear. After an AJAX generation or revision, the result and management partial are both inserted immediately, the current project/version and URL are updated, and the latest title moves to the top of history without duplicating the current link.

“Kelola rencana” contains a required name field (60 character maximum), save-name and duplicate forms, and a delete trigger. Deletion opens a native modal dialog with “Batal” and “Hapus rencana”; its explanation accurately says the plan will be hidden from history. The confirmation submits the explicit delete value. These management forms use their existing server-backed behavior; they are not described as AJAX actions.

### Errors

Generation errors appear beside the composer in a `role="alert"` region with error text; progress clears and controls become usable again. Existing rendered plan content is replaced only after a successful response, preserving the prior visible plan on failure. User guidance supports trying again; the connection fallback directs the user to check history before retrying. The supplied error captures demonstrate localized recovery copy with the entered idea retained.

On a parsed server failure, the client renews the operation key for retry. When the response identifies an owned saved project, it retains that project's ID, version and URL, clears transient image previews and hides the upload control. Retrying uses the same project and its saved references rather than uploading them again. Provider-failure guidance explains that the idea and previous plan remain in history; transport failures still direct the user to check history before retrying. This recovery behavior changes no visual styling.

### Canonical revision states and old-plan compatibility

The visible document represents the latest saved plan for the same project. Style, scene, format and patch instructions build from the active semantic brief. Core subject/product replacement starts a new working brief while preserving neutral delivery constraints; explicit preservation requests retain selected fields. Location or talent replacement updates that field. Core and attribute replacement paths omit prior generated fragments from generation context. Stored revision kinds include NEW, PATCH, STYLE_CHANGE, SCENE_CHANGE, FORMAT_CHANGE, REPLACE_CORE and PRESERVE_AND_REPLACE; these internal names do not become extra UI controls.

Replacement updates the working title and current deliverables, including storyboard, directions and copy payload. References appear only when the canonical brief permits their use. The supplied replacement-chain capture shows the active food plan at version 3; it is synthetic state evidence, not proof of live provider quality. A stale-tab revision conflict asks the user to reopen the plan.

Earlier stored plans remain readable and copyable through the same workspace. Missing `master_prompt` triggers the explicit older-plan note asking for revision to obtain production directions and English prompts. The legacy formatter assembles fallback prompt text from saved fields; the interface omits the English badge for that text. Optional V2 fields appear only when present. Revision can produce the current format without a separate migration screen. Former `area=learn`, `area=workflow` and `area=tools` links redirect to the single workspace; those educational tabs are no longer presented.

Destination prompts use conservative instruction formatting without proprietary integration claims. The closing guidance states that duration is planned, clips may need assembling externally, and Kilas does not render or send video to other services.

## Do's and Don'ts

- Do inherit the incumbent customer palette, Manrope hierarchy and shell geometry.
- Do keep generated directions readable, selectable and divided into practical sections.
- Do preserve consistent current title/version/revision state, local copy feedback, immediate management and explicit error recovery.
- Do retain readable and copyable old-plan fallback with accurate language labels.
- Do retain native disclosure/dialog semantics, visible focus and reduced-motion behavior.
- Don't imply that Video renders, publishes or connects to external tools.
- Don't extend Video styling into Finance, Assist, admin or shared global templates.
- Don't promote ineffective local CSS declarations or isolated small controls into global rules.

Not canonized or repaired: PRODUCT.md still records the earlier Assist audit-only authorization and undecided aesthetic; root DESIGN.md already identifies that historical drift as superseded by the pinned October customer brief. Root DESIGN.md also describes smaller wrapper gutters at 360px that more-specific incumbent shell rules override in the captured Video view. The local/shared heading and link cascade differences above are documented as current inheritance, not reasons for a global repair. No global system, sidecar, product context or UI source was changed by this documentation pass.

The V1 finish disposition does not certify V2. The V2 final reviewer owns its release verdict. This documentation records current source and supplied local evidence; it makes no deployment, production-provider quality or accessibility-certification claim. No shipping raster assets were added by V2 or this documentation pass.
