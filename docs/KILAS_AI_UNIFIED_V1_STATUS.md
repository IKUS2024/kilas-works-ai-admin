# Kilas AI Unified Experience V1

Updated: 2026-10-02. Branch: `feature/kilas-ai-unified-20261002`.

Started from remote main `8da6111` after verifying the previously completed Work V2, Chat Quality V2 and inline-result fixes were already merged. Those systems are retained.

## Implementation

- Canonical Kilas AI uses the existing persistent conversation surface, with no Chat/Work selector or manual Search checkbox.
- Ordinary conversation uses the existing shared `ChatQualityStream`: Luna low/medium, bounded context, at most one metered medium repair, existing fair-use and QA controls.
- Deterministic dispatch reuses existing routing, Search and Work runtime. Documents, Office, images, reminders, research, lifecycle controls and waiting-input continuations retain existing workers and storage.
- Sidebar uses Chat baru, recent conversations, real active-job count, separate notifications, history and settings.
- Legacy history is linked under Percakapan sebelumnya; no history is copied or removed. Existing legacy sharing remains available; unified sharing is not fabricated.
- Mobile capability-based focus behavior and permanent inline anchors are preserved. Stop cancels the foreground streaming request; durable jobs retain their existing job controls.

## Scope and release state

No schema/migration, infrastructure creation, production data reset, pricing, Finance, Assist, WhatsApp, Meta or Google scope change.

Focused routing/Work suites: 43 Agent experience, 18 result safety, 22 Work V2, 21 new unified tests and 12 intent tests passed. Shared Chat Quality V2: 18 passed with Python UTF-8 mode. Cost/fair-use, attachments, PDF, normal style, subscriptions, existing Agent/Automation/connector and legacy Chat tests passed after updating intentional UI wording expectations.

All eleven local browser journeys passed, including canonical unified Chat/analysis/Search/images/PDF/reminders at 320/360/390/820/1440. Screenshots: temporary `kilas-unified-{width}.png` and Work/shell acceptance captures. Image previews use the same private validated artifact URL, without a public storage route.

PR: https://github.com/IKUS2024/kilas-works-ai-admin/pull/119. Implementation head: `6bdfcc69dffa506579bdcbbcaf41eebde6cfe042`.

Current-head CI passed Autonomous/Work focused, browser, native PostgreSQL and Linux code sandbox; dedicated Chat Quality focused/browser; Automation schema/focused/browser/boundaries; Connectors browser/focused/PostgreSQL/baseline; Phase 8 WhatsApp runtime; Finance runtime/mobile; root bot and additive PostgreSQL release checks. Linux focused checks also passed the unchanged Finance baseline and Assist connections, confirming their local Windows deletion-lock errors are environmental.

Broad failures were compared with the existing production lineage's PR #118 evidence: Assist billing expects 200 but receives 302, and language normalization expects an English directive but receives None. Phase 9 expects the removed Finance onboarding heading; Phase 10 expects the removed Mulai Sekarang button. Same failure names/messages; related implementation files are unchanged. Full Phase 7 Finance baseline is still running and will be compared mechanically before release.

Scoped Impeccable engine 0.1.6 check: one existing flat-type-hierarchy suggestion. Detector cannot resolve Jinja stylesheet URLs; browser inspection is authoritative. No full audit or unrelated typography redesign.

No merge or production deployment yet. Production baseline Client Hub is LIVE on `8da611167d3ea23b243ddb4405e9cdc094205b04`, deploy `dep-davs2p0u01pc73fuhh30`; authenticated entry redirects normally to login, public login returns 200, baseline error-level logs are empty. Controlled production login window is open; awaiting user sign-in before authenticated production QA. Client Hub and existing Cron must both deploy the final merged SHA and reach LIVE before production success can be claimed.

Known limits: legacy history links the latest 50 historical threads without migrating them; older direct/shared links remain valid. Unified conversations do not add sharing. Simple image actions reuse the existing durable image worker internally. Optional Web Push depends on existing configuration; reminders still persist and deliver into their originating conversation.
