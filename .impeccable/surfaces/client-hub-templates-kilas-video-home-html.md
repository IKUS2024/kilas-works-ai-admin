---
version: 1
slug: "client-hub-templates-kilas-video-home-html"
primary_target: "client-hub/templates/kilas_video/home.html"
related_targets: ["client-hub/templates/kilas_video/_result.html","client-hub/templates/kilas_video/_scene_prompts.html","client-hub/templates/kilas_video/_parts.html","client-hub/static/kilas_video.css","client-hub/static/kilas_video.js"]
---

## Direction contract
THESIS: One creative production workspace, with the latest brief and prompt as the working deliverables.
OWN-WORLD: Existing white Kilas shell, Manrope, charcoal text, neutral dividers and controlled orange actions. No global theme replacement.
MODE: Operate. Compose, inspect continuity and timed handoffs, revise, and export production prompts.
STORY: Enter an idea, choose single video or connected clips and optional format/tool, review the concept and storyboard, copy each scene's English still-image prompt before its same-scene video prompt, inspect the shared Continuity Bible and separated numbered clips, revise the same project, and copy individual prompts or the full package. Regenerate the storyboard or generate video directions from the locked current storyboard.
FIRST VIEWPORT: Existing navigation left; active project and composer above the plan in the center; compact outline, project history and management right. Mobile shows composer first and history after the plan.
FORM: The owner's precisely specified editorial single-workspace layout; code-led, pinned brief, no open concept selection or seed required.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
Scope: Kilas Video only. Existing global DESIGN.md stays authoritative. No shipping rasters added; synthetic reference images are QA data.

## Connected-clips extension
Preserve the incumbent white/Manrope/charcoal/neutral-divider/orange workbench. Composer and mode controls lead; Continuity Bible precedes numbered, timed clips with concrete start/end handoffs. Individual master/platform prompt disclosures, 44px copy controls and Bible/all-parts/full-plan exports support deliberate use. Four-language controls do not translate generated English content. Maximum eight detailed clips and the current 75-second deadline remain explicit constraints. Do not imply video rendering or guaranteed external-tool continuity.

Scoped finish disposition: ship after the independent reviewer inspected 24 required captures at eight widths; synthetic evidence does not establish live-model quality or deployment. Extension record: `docs/KILAS_VIDEO_MULTIPART_DESIGN.md`. Preserve root `DESIGN.md` and `.impeccable/design.json`; pre-existing PRODUCT historical drift is reported without repair.

## Storyboard-first extension — 2026-10-04
The same Operate workspace now orders work as idea → concept/storyboard → per-scene English still-image prompt → same-scene English video prompt. The overall storyboard opens by default. Each numbered scene puts its purpose and visual direction ahead of an exposed image prompt; a native disclosure holds the corresponding video direction and copy control. Copy one image/video or all image/video prompts; full-plan and incumbent master/platform exports remain available. Separate storyboard and video regeneration actions retain the active project and an unsent revision draft. Video regeneration derives directions from the current locked scenes rather than changing their approved frames.

This extends the incumbent document hierarchy without a new palette, font, shell, imagery stance or global component rule. Prompt blocks keep neutral surfaces, inherited type and readable wrapping; secondary actions retain white/charcoal treatment, focus and 44px touch heights. At 600px and below, regeneration/export actions and scene headings stack. Existing single-video and connected-clips workflows remain available; historical plans without still prompts retain their readable result and explain how to add them.

Scoped finish disposition: **ship** after independent review of eight required current-build captures. Local synthetic browser checks passed with subprocess exit 0 at 320, 360, 390, 430, 768 and 1440px for per/all clipboard payloads, locked regeneration, unsent draft retention, reload persistence, English controls and no horizontal overflow. Legacy single-video and connected-clips application checks reached PASS at eight widths; their initial PowerShell redirect reported exit 1 from native stderr wrapping, with clean exit pending CI confirmation. 58 unique Video contracts and eight i18n tests passed. Detector exit 0; isolated-fragment default-background suggestions and incidental font-size advisories are not verified product defects. Full implementation/evidence boundary: `docs/KILAS_VIDEO_STORYBOARD_FIRST_STATUS.md`. Production, CI, push and deployment verification remain pending at this checkpoint. No new shipping raster or global design artifact change.
