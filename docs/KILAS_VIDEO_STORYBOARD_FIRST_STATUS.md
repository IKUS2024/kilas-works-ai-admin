# Kilas Video storyboard-first extension

Checkpoint: 2026-10-04. Scoped implementation, local verification, CI and initial Client Hub deployment complete. **Authenticated live-model production QA remains pending reauthentication.** The independent Impeccable finish reviewer returned **ship** with no material fixes; that verdict covers the reviewed local UI, not unexecuted production scenarios.

## Release evidence and resume point

Application commit on main: `b2a0d4f7846a9a9058f0e89883e93a391b8beec4`, `Generate storyboard image prompts before Video directions`. All six workflows passed on this exact SHA: Video `37185361676` (focused, browser and native PostgreSQL), AI Focused `37185361703`, Global UI `37185361706`, Autonomous Agent `37185361699`, Chat Quality `37185361689`, Automation `37185361741`. CI confirms clean browser process exits, including both incumbent Video browser matrices and the new storyboard browser; the earlier Windows shell redirect distinction below is historical local-harness evidence.

Only existing `kilas-works-client-hub` (`srv-da7ti2psrm7s73dh9i2g`) was deployed, `dep-db0vv3gu01pc73c6md40`, **LIVE** at `2026-10-04T07:26:57Z`, exact application SHA confirmed by Render. `/healthz` returned 200. Publicly served Video CSS and JS matched the committed Git blobs exactly (CSS SHA256 `c162bdbfaa0f4c9cc26b80aec99a3424880539c287a5628a4b02f0c4a7784d74`; JS `dfeae701ee72e86dd3f70b43344634a52254d92e65bbea1e7657a8b0858b897e`). Initial comparison with Windows working-copy bytes differed only by CRLF; no application code mismatch. Render error/critical application logs through `2026-10-04T07:27:50Z` returned no entries. No AI Admin/Cron deploy, migration, resource/config change or data reset.

Final release diff reviewed: 21 scoped files, including Video generation/JSON boundaries, templates/assets, additive Video labels, focused tests/workflow and scoped documentation. No Finance, Assist, Chat runtime, WhatsApp, billing or schema code changes. Pre-existing unrelated dirty files remain preserved and excluded.

The controlled verification session expired. The existing dedicated browser is alive at loopback CDP port 9333 and its login page was brought forward. An asynchronous sign-in request is pending; the session still redirected `/kilas-ai/video` to `/login` at the last check. Do not fabricate credentials, bypass authentication or call authenticated production QA passed. No new synthetic production project has yet been created by this task.

Prepared resume harness: `%TEMP%/kilas-storyboard-production-qa.py` (not yet executed). It uses the authorized browser session in memory, never saves credentials, and creates only two safe synthetic Video projects: a coffee single plan and two-part skincare UGC with an artificial green-bottle reference. Pending scenarios: actual model Indonesian-to-English prompt quality, per-scene/bulk clipboard, locked video regeneration, storyboard regeneration, multipart identity/exact handoff, style patch, history/reload, 320/360/390/430/768/1024/1440 responsive UI, existing Home/Settings/AI chat, Finance stylesheet-baseline comparison, and Render logs afterward. Results go to `%TEMP%/kilas-storyboard-production-qa/`. Continue those checks after the user signs in; fix and retest a real regression before claiming complete QA.

This checkpoint follow-up contains documentation only. If deployed to align main and production, application code is identical to the six-workflow-tested release above; no new model call is implied by that deployment. The latest deployment ID/SHA must be confirmed with Render before reporting final release alignment.

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

Remaining evidence: authenticated real-model production scenarios above, resulting output quality, and post-QA log review. Current successful deployment and public asset/health verification are recorded separately from those pending checks.
