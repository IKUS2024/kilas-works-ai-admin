# Kilas Video connected clips design record

Recorded 2026-10-03 after the scoped Impeccable finish reviewer returned **ship**. This documents an ordinary extension of the existing Video surface. It is not a global design-system revision, accessibility certification, release approval or deployment record.

## Direction and scope

The owner's supplied multipart brief calls for an operational video-planning workbench: compose a brief, choose single video or connected clips, inspect the shared creative identity and timed handoffs, then copy English production prompts into an external tool. Existing useful single-video planning remains visible. Kilas prepares plans and prompts; it does not render or submit the resulting video to another service.

The incumbent white professional workspace remains the visual authority. `DESIGN.md` and `.impeccable/design.json` are preserved. This extension does not introduce durable global tokens, a replacement visual world or a shared CSS rewrite. Finance, Assist and unrelated product behavior are outside this design record.

## Verified incumbent matches

| Established system | Implementation evidence |
| --- | --- |
| White surfaces, charcoal content, secondary gray text and neutral dividers | `client-hub/static/kilas_video.css`: `.video-studio`, fields, `.video-plan`, `.video-section`, `.video-history` and `.video-part` retain `#202329`, `#62666f`, white and `#e4e5e7`. |
| Existing Manrope hierarchy | Video inherits the customer typography documented in `DESIGN.md`; the Video stylesheet uses inherited control fonts, compact metadata, 15px document text and established heading sizes. No new font is introduced. |
| Deliberate orange for meaningful state and focus | The Video stylesheet retains `#bd4700` for accent text, caret, radio selection and a 3px focus-visible outline. Main submit uses the existing `.btn` component. |
| Content before chrome | Parts use spacing and horizontal divider borders; the shared Bible is a definition list, and prompts use existing neutral surfaces with wrapping text. No decorative dashboard or generated illustration is added. |
| Readable controls | `.video-mode-choices label`, fields, summaries, submit and result-copy buttons have a 44px minimum height. Individual part copy is a labeled button, distinct from the prompt disclosure. |

These are observations of the scoped source, not detector recommendations or a new token catalog.

## Responsive and control hierarchy

`client-hub/templates/kilas_video/home.html` places active project identity and the composer before the result in document order. Single/multi mode is a native radio fieldset. Multi mode exposes total seconds, auto or fixed 5/10/15-second strategy, an announced split preview and the eight-clip limit. Optional format/tool fields remain under a disclosure. Generation has explicit busy, status and error states.

The desktop workbench retains a flexible content column, 220px supporting rail and 40px gap within the 1180px cap. The 1100px rule stacks history below the plan; at 1000px the outline is hidden and the rail is no longer sticky. At 600px controls and detail columns stack, section headers and their copy actions become vertical, definition-list labels narrow to 76px, and prompt padding reduces. Long titles and content wrap. This retains composer-first mobile order without forcing the keyboard open after generation.

`_result.html` presents creative direction before `_parts.html`. Multipart output then presents the Continuity Bible, linked clip flow and separate numbered parts with time ranges, purpose, scene, concrete starting/ending states, shot direction, audio/script guidance and avoid lists. Each part offers its own master-prompt copy action and separate master/platform disclosures. Bible, all-parts and full-plan exports remain available. Overall storyboard and full prompt packages default closed for multipart plans; single plans retain their expanded treatment.

`client-hub/static/kilas_video.js` selects copy payloads by their individual keys, reports success/failure through an announced status and offers manual selection when clipboard copy fails. Successful revisions replace the result and update active title/version, composer state, outline visibility and history from the server response. Source inspection verifies this presentation behavior; backend revision correctness needs its own regression evidence.

Control labels use the existing four-language UI system (Indonesian, English, Spanish and Chinese). Generated English production prompts remain content rather than UI strings. Tool guidance stays generic and does not advertise proprietary syntax or guaranteed external-tool support.

## Evidence and limits

The independent finish reviewer reported inspection of 24 required captures across 320, 360, 390, 430, 768, 820, 1024 and 1440px, with disposition **ship** and no material fixes requested. That review is attributed evidence; this documentation pass inspected the templates, CSS, JavaScript, incumbent `PRODUCT.md`/`DESIGN.md`, existing surface contract, current checkpoint and owner's attached request.

Synthetic provider content and screenshots establish layout and interaction behavior. They do not establish live-model creative quality, external rendering quality, continuity in an actual generated video, or production deployment. The eight-part ceiling is explicit in UI/JavaScript and `video_parts.py`; `video_director.py` retains the current 75-second synchronous deadline. Detailed plans are bounded by those limits.

No shipping rasters were added by this extension. User-uploaded reference previews remain product content, while synthetic screenshot/reference fixtures are QA evidence; neither is a new brand asset requiring canonization.

## Preserved system and historical drift

`PRODUCT.md` still records the September Assist installation/audit-only authorization and undecided visual direction. Root `DESIGN.md` already identifies that historical drift and records the owner's October white customer workspace direction. The current attached Video request expressly authorizes scoped implementation and Impeccable polish. This documentation does not repair or replace `PRODUCT.md`, the root design record, its sidecar, shared styles or status documents. Any release decision and production verification must be reported separately by the release owner.
