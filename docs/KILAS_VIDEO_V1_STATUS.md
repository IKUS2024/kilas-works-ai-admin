# Kilas Video Director V1

Starting main: `db83e813200e39c020abbc7eed88dbed42413fd4`. Branch: `feature/kilas-video-director-v1-20261003`.

Scope: a separate premium Video planning/education workspace, not video rendering. One metered existing OpenAI text/vision request produces a bounded universal spec; isolated deterministic Universal / Google Flow / Seedance / Higgsfield / Runway adapters produce copy-ready directions. No external video tool/API calls, new credit system, pricing change or Cron execution changes.

Private history: additive 0082 projects, revisions and references, plus checksum release tracking. Client Hub applies only this explicitly authorized checksum-idempotent release when Kilas AI is enabled; general historical migrations remain disabled. Owner-scoped reads/actions/images, version leases, optimistic saves, soft deletion and preserved prior plans on provider failures. References reuse existing safe JPG/PNG/WebP validation and normalization; existing plan upload counts remain.

UI inherits DESIGN.md and the current white/charcoal/orange product. Four areas: planning, Belajar (19 practical lessons), Workflow (product/UGC/cinematic), Tools (6 official destinations). Adds normal Video navigation and Home CTA; no Connections/Assist UI reintroduced. Copy feedback, reference removal, natural revisions, history, rename/duplicate/delete confirmation, no completion refocus on mobile.

Official URLs verified via primary pages 2026-10-03: labs.google/flow (redirects flow.google.com), seed.bytedance.com/en/seedance, higgsfield.ai, runwayml.com (redirects runway.com), capcut.com, adobe.com/products/premiere.html. Names and conservative descriptions only; no model/pricing claims.

Focused Video tests: 22 PASS locally, including relevant voice-over/script payload and immediate AJAX management. Corpus: 200 realistic idea + correction scenarios across 25 subjects and 8 approaches; never runtime-injected. This is offline contract/context coverage, not 200 live semantic answers.

Actual Chromium browser QA: PASS at 320/360/390/430/768/820/1024/1440. Real image selection/removal, create/revise/history/rename/duplicate/delete confirmation, clipboard master/platform/storyboard/everything, immediate management after generation, localized provider error recovery, white theme, no overflow or page errors. Synthetic AI transport is explicitly mocked. Local AI Agent (9), Product Hardening (38), Work V2 (22) regressions also passed.

Impeccable: one scoped detector run; Jinja-linked CSS and compact incumbent typography yielded advisories, rendered review is authoritative. Reviewer requested local copy feedback, fresh-plan management and SVG icons; all applied in one batch, final verdict: ship, all three listed fixes resolved. No global design/theme or Finance edits.

Status: IN PROGRESS. Remaining: native PostgreSQL/CI gates, Impeccable verdict/documentation, clean release to main, Client Hub-only deployment and controlled production verification. The verification browser is open on login; authenticated production verification is not yet evidenced. Prior three release documents remain uncommitted and preserved, outside this patch.

Final recovery fix: a failed provider/spec response returns only owner-authorized project/version metadata; the composer renews the consumed operation key and retries the same saved project with its retained references. No duplicate project, lost prior plan or bypass of metering. Focused regression passed. Candidate CI PostgreSQL release rehearsal passed; latest recovery candidate requires fresh CI.

## Production release ? 2026-10-03

Status: LIVE; authenticated controlled-account production QA remains PENDING.

Released main: `3a7ac31dd30a61549b1cca864f2ac3b43cca5162` (fast-forward of reviewed feature branch; direct-main release explicitly authorized). Implementation candidate `0951595` passed all three Video gates, and subsequent changes before release were scoped design documentation only.

All 17 main CI jobs passed across six workflows:

- Video QA: run 37095746347 ? focused, eight-width browser plus incumbent premium/unified regressions, PostgreSQL 0082.
- AI Focused QA: run 37095746350 ? foundation, browser, PostgreSQL schema.
- Autonomous Agent QA: run 37095746358 ? focused Work/Agent regressions, browser, code sandbox, PostgreSQL.
- Automation QA: run 37095746357 ? focused, boundaries, browser, PostgreSQL.
- Chat Quality V2 QA: run 37095746363 ? chat and browser.
- Client Session Timeout QA: run 37095746333 ? session timeout.

Only `kilas-works-client-hub` (`srv-da7ti2psrm7s73dh9i2g`) deployed. Render deployment `dep-db0846id0e5s73ag94a0` became LIVE at `2026-10-03T04:19:27Z`, exact released SHA above. No AI Admin or Automation Cron deployment; no paid resource, configuration, pricing or quota changes. The enabled Client Hub startup uses the rehearsed, checksum-idempotent additive 0082 release path; no historical/general migration or destructive operation was requested. No production records were reset or rewritten.

Verified at https://app.kilasworks.id after deployment:

- `/healthz`: HTTP 200, status ok, Client Hub, PostgreSQL.
- `/static/kilas_video.js` and `/static/kilas_video.css`: exact normalized contents match released source.
- `/login`: actual Chromium at 320/360/390/430/768/820/1024/1440; no horizontal overflow or page errors.
- Protected Home, Video planning/Belajar/Workflow/Tools, Kilas AI and account routes redirect an unauthenticated request to Login.
- Render error-level and Traceback/Exception/ERROR queries since deployment: empty at post-deploy check.

LIMIT: the dedicated verification browser still shows `/login` and a protected Home request returned 302. Earlier Ready replies did not yield an inspectable authenticated session; browser closed and was reopened using the same persistent profile. No credentials were requested, extracted or substituted. Therefore real production plan creation/vision/revision/copy/history, authenticated Home/AI/Finance/Settings and Services navigation have NOT been claimed as verified. Their local/CI coverage above is distinct from production evidence.

Next step only: finish controlled-account production QA after successful sign-in, using the already prepared `%TEMP%/kilas-video-production-qa.py` helper and open CDP 9333 verification window; do not rebuild, rerun a broad audit, change another feature or redeploy unchanged code. Inspect normal real-plan quality and reference preservation, and record results/errors honestly. Prior three unrelated modified release documents remain preserved and excluded from this release.

## Authenticated production QA continuation - 2026-10-03

Controlled sign-in restored successfully. Real Video plan creation with synthetic bottle image, metered vision, Seedance prompt, copy controls, no-voice-over Runway revision on the same project, reload/history, owner rename, duplicate and confirmed deletion of the duplicate passed. Original synthetic QA plan remains saved. Home/Kilas AI/Settings loaded; Services href checked exactly https://kilasworks.id; no Assist/workspace controls appeared in normal Home/navigation.

Real Chat arithmetic and first-turn image understanding passed. Synthetic TXT plus PDF reading, verified quantity/total facts, Markdown revision and uploaded attachment persistence after refresh/reopen passed. Eight-width Chat captures showed no horizontal overflow.

Confirmed production regression: an explicit follow-up about the already uploaded red-square/blue-circle image returned that the image was unavailable. Diagnosis: agent_chat.context replayed stored document text but not stored image bytes on visual follow-up. Narrow fix isolated on fix/kilas-ai-image-followup-20261003: replay up to five images from only the latest image turn in the same owner's same conversation, gated on explicit image/foto questions and current vision capability. New uploads keep precedence; unrelated messages do not replay binaries. Four focused regression/isolation tests and 38 product-hardening tests passed locally. No migration, Finance or Cron execution change. Remaining artifact QA and corrected-release CI/deployment/production retest are in progress.

A synthetic mobile exact-marker assertion used underscores that Markdown rendered as formatting; visible answer was QAMOBILEOK and no request error occurred. This was a QA assertion mismatch, not evidence of a product failure. Touch/viewport checks are being completed separately with a plain-word answer.

Second related live regression during existing-attachment retest: contextual question "Pada foto lampiran ... saya upload sebelumnya, apa ...?" was classified as background work due to the word upload. Narrow request-ingress fix: preposition-led questions about an existing image/file return no work intent. Five focused tests now cover binary replay, owner/conversation isolation, new-upload precedence, no replay for unrelated Chat, and no new Job for this question. The first image-context release ca30caf passed all 13 CI jobs and went LIVE as dep-db08kapsrm7s73ehp2vg; final related routing correction requires CI and deployment before the retest can be marked complete. No migration or Finance change.

Other live checks passed: actual generated paper-boat image and edited yellow-circle variant visually inspected; previews and downloads; generated PDF and revised PDF parsed with 30/360000 and 40/480000 synthetic facts; artifacts persist at all eight widths. Touch emulation reports fine-pointer false, stable viewport height after DONE, no auto composer focus, manual tap works. Home, account Settings and AI settings passed eight-width overflow/navigation checks. The earlier broad /workspace substring QA assertion also matched Finance's valid /finance/workspaces route; corrected to retired Assist routes only, with no product code change for that assertion.

Final live retest found an existing PostgreSQL-only PDF scan lookup failure (literal percent signs interpreted as bound parameter markers), resulting in Chat POST 500 before image replay. Narrow correction binds the LIKE pattern as a parameter; adds native PostgreSQL coverage for scan matching, empty result, image replay and owner isolation. Five focused SQLite tests passed; release CI and final production retest remain required. Finance remains unchanged; read-only invoices overflow by 21px at 320px and 9px at 768px, recorded as an out-of-scope issue.

Release gate diagnosis: browser interaction QA raced the automatic start request against its expected PLANNING card. The interaction fixture now mocks only worker execution, leaving real browser requests, persisted Jobs, controls and navigation intact; worker behavior is tested separately. Local four-width interaction QA passed. PostgreSQL scan/image/owner coverage passed in CI. Final corrected-candidate CI remains pending.
