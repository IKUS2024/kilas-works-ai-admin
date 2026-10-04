# Kilas Video storyboard-first extension

Checkpoint: 2026-10-04. Scoped implementation and local verification complete; production, CI, push and deployment verification pending. The independent Impeccable finish reviewer returned **ship** with no material fixes. That disposition approves the reviewed local build; it does not establish a production release.

## Resulting workflow

Kilas Video now develops an idea into a concept and storyboard before generating English video directions. Each scene has a title, purpose, frozen-frame image prompt and corresponding video prompt. The still-image phase describes a visible instant; the video phase uses the current approved storyboard frames to describe motion, camera progression, pacing and continuity. The current project, reference evidence, scene order/timing and connected-clips handoffs remain authoritative.

The open overall storyboard places each still-image prompt before its video disclosure. Users can copy an individual image or video prompt, all image prompts, all video prompts, the storyboard or the existing full package. Separate actions regenerate the storyboard or regenerate video directions from the locked current storyboard. Both retain an unsent revision draft. Existing single-video and connected-clips plans, production direction, Continuity Bible, numbered clips, master/platform exports, history and project management remain available. Historical plans lacking image prompts remain readable; their result explains storyboard regeneration, while video-only regeneration is disabled until frames exist.

Kilas produces plans and prompts. Final images and videos are created in the user's chosen external tools; no external rendering or tool continuity guarantee is implied.

## Design continuity

The scoped expression extends the existing white Kilas workbench recorded in root `DESIGN.md`: Manrope, charcoal text, neutral dividers, orange actions and selection. It reuses the composer-led primary column and supporting history/outline, native disclosures, neutral prompt surfaces and document reading hierarchy. The new hierarchy makes image-before-video explicit within each scene; it introduces no new aesthetic direction or composition selection.

Scoped secondary buttons remain white with charcoal text and neutral borders. Copy, regeneration and disclosure controls retain 44px minimum heights and visible focus; prompt text wraps within its existing scrollable neutral enclosure. At 600px and below, regeneration/export controls and scene headings stack. Request loading/disabled states and live status/error feedback remain in place. No new shipping raster was added; screenshots contain synthetic QA content and are evidence, not product assets.

Inspected presentation sources: `client-hub/templates/kilas_video/home.html`, `_result.html`, `_scene_prompts.html`, `client-hub/static/kilas_video.css` and `kilas_video.js`. The scoped direction is recorded in `.impeccable/surfaces/client-hub-templates-kilas-video-home-html.md`. Root `DESIGN.md`, `PRODUCT.md` and `.impeccable/design.json` were preserved by this documentation pass.

## Verified local evidence

- **Storyboard browser:** `client-hub/tests/test_kilas_video_storyboard_browser.py` passed at 320, 360, 390, 430, 768 and 1440px. Real DOM/clipboard checks compared individual image/video, all-image/all-video and complete-package payloads; confirmed different still and video content, locked-frame preservation during video regeneration, unsent draft retention, stored-version reload, English controls, no horizontal overflow and no page errors. Model responses and tenant data were synthetic.
- **Existing workflows:** single-video and connected-clips browser application checks reached PASS at eight widths. The first shell redirect reported exit 1 because PowerShell wrapped native stderr; clean process exit remains for CI confirmation. Logs are `%TEMP%/kilas-storyboard-browser.log` and `%TEMP%/kilas-storyboard-parts-browser.log`. These checks retain evidence for the incumbent plan/prompt workflows alongside the storyboard extension.
- **Contracts and localization:** 58 unique Video contract tests plus eight i18n tests passed locally, as reported by the implementation handoff. This count is unique contracts, not an assertion that repeated suite runs add independent coverage.
- **Independent finish review:** the reviewer checked all eight required current-build captures and returned ship, with no material fixes. The review confirmed image-before-video hierarchy within the incumbent visual world, mobile control stacking, native disclosures, 44px controls, focus and request-loading behavior. The report is a session handoff; no durable report file was supplied.
- **Scoped detector:** exit 0. Incidental font-size advisories and black-default suggestions from isolated Jinja fragments were evaluated separately from the assembled product; neither was canonized as a verified defect or new design rule.

The storyboard browser writes local captures under `%TEMP%/kilas-video-storyboard-browser/`: `full-{width}.png` and `scene-{width}.png` for the six widths above. Its subprocess log `%TEMP%/kilas-storyboard-new-browser.log` records PASS with exit 0. The eight required reviewer captures are `.impeccable/review/scene-{320,360,390,430,768,1440}.png` and `.impeccable/review/storyboard-full-{390,1440}.png`; this review folder is gitignored local evidence. These captures are not committed shipping assets. Local tests demonstrate synthetic application behavior; live-model prompt quality and external image/video output remain outside that evidence.

## Boundaries and remaining release evidence

This documentation pass writes only the scoped surface brief and this new status file. It does not change runtime code, global templates/CSS, Finance, production data or WhatsApp/payment configuration. Existing unrelated dirty files and documentation were preserved.

Pre-existing context drift remains reported without repair: `PRODUCT.md` and the latest master entries still describe an older Assist audit-only period, while root `DESIGN.md` records the owner's later pinned white customer-workspace brief. This authorized Video extension follows the incumbent customer implementation and the current task; its scene workflow is a surface expression, not a global prohibition or replacement identity.

Required release evidence still to append: candidate/merge commit, applicable CI results, approved release action, live service commit/status and production read-only verification. No deployment, successful CI or live verification is claimed at this checkpoint.
