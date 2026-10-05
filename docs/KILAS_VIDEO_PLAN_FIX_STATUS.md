# Kilas Video Plan recovery and clip workflow ? 2026-10-05

Scope: Video Plan only, continuing latest main 68f3294a6ab60bba3a9003d0f5f2c0fb16816191. Pre-existing unrelated working changes remain unstaged.

## Verified diagnosis
Production baseline Client Hub deploy dep-db16riid0e5s73ecv7f0 was LIVE at that SHA. Authenticated controlled 10-second/no-tool and 20-second/Auto Split/Google Flow generations both returned HTTP 200 (51.7s and 48.0s), projects 25 and 26. Those attempts did not reproduce the intermittent failure. Render logs independently recorded `Video provider timeout stage=0 elapsed_seconds=40.1` at 2026-10-05T02:56:51.87369339Z. The previous first-stage 40-second timeout and two sequential model requests were verified in source. Exact-key validation also rejected omitted optional supporting fields; that secondary resilience issue is verified by source/regression tests, not a claimed production schema incident.

## Fix
One compact complete storyboard-first inference replaces two sequential inference calls; timeout is bounded at 65 seconds within the existing 75-second route budget. Existing model policy, metering, safety, canonical brief, revision protection and locked-frame video regeneration remain. Missing optional strings/lists normalize without inventing facts; wrong types, required concept/prompts, English, timing, maximum eight clips, continuity and unsafe/stale content remain validated.

Each clip exposes reference-image then video prompts with exactly two copy-control types. Supporting direction remains readable without copy controls; later clips retain continuity guidance. Motion exports do not paste the full still-image prompt. Optional target tool, history, reference upload and management remain. Loading prevents duplicate submits. Failure has Coba Lagi and persists failed idea/settings in existing private options JSON; prior successful plan/version and references remain. Processing conflicts do not show generation failure. No schema or migration change.

## Local evidence
65 unique focused Video contracts passed (base22, V2 15, connected15, storyboard6, recovery7; unittest imported base tests repeat in several runs). Eight i18n checks passed. Three real-browser suites, mocked provider transport and disposable owners, exited0: single and connected plans at 320/360/390/430/768/820/1024/1440; storyboard at 320/360/390/430/768/1440. Exact prompt clipboard, only image/video copy controls, upload/remove, revision/replacement, locked regeneration, Retry, processing409, history/reload, no JS errors and no horizontal overflow passed. Impeccable scoped detector exit0 advisory only. Independent finish reviewer inspected12 valid full/scene captures and returned ship for scoped UI; live-model behavior is outside that verdict. Pre-existing design-sidecar/buildPath drift reported without repair. No new shipping raster.

## Release checkpoint
CI, push, production deployment and post-fix authenticated generation remain pending here. Deployment target is ONLY kilas-works-client-hub; no AI Admin deployment, migration, environment/config change, data reset or paid resource.

Important paths: kilas_ai/video_director.py (bounded inference/normalization), video_storyboard.py (complete/locked prompt contracts), video_parts.py (timelines/continuity), video_adapters.py (prompt payloads), video_routes.py (private generation/error responses), video_store.py (existing JSON retry draft). UI: templates/kilas_video/home.html, _result.html, _scene_prompts.html; static/kilas_video.js/css; locales/ui.json (Video keys only). Focused tests: test_kilas_video*.py; existing Video CI adds recovery suite.
