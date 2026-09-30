# Kilas AI Automation V1 checkpoint

Updated 2026-09-30 (Asia/Bangkok). Source: user attachment `e9e11c7d-5812-46b9-a220-f01aecd88609/Pasted text.txt`.

Feature branch `feature/kilas-ai-automation-v1-20260929` was based on `b61df7e8b6fc0229a5d78623b0c0401e9db22982`. The unfinished Kilas Work/Chromium draft PR #77 is untouched and was **not** this branch's base. The previous production Client Hub deploy `dep-datrqc942hec73ctit2g` at that SHA is the rollback point.

Current Kilas AI plans remain Free Rp0, Plus Rp69,000, Pro Rp149,000, Max Rp299,000; Chat/Search quotas, fair use, verified top-ups, adaptive Search, and 100 MB phone-photo upload remain intact. Before this release main had migrations through 0073; the Work draft uses 0074 off-main, so Automation uses 0075 to avoid collision. Automation remains inside Kilas AI with Chat | Automation navigation and no Computer Use, Chromium, browser service, separate product, or separate subscription. Finance, Assist, WhatsApp/Meta, onboarding, and AI Admin are outside scope.

Runner design: PostgreSQL-backed due schedule, deterministic occurrence identity, bounded one-shot command suitable for Render Cron, no Gunicorn loop. The owner explicitly approved exactly one 0.5 CPU / 512 MB Cron Job with a roughly $1/month minimum plus normal usage-based compute. Source: https://render.com/docs/cronjobs and https://render.com/pricing .

Implementation is merged: additive 0075 SQLite/PostgreSQL schema, opt-in targeted PostgreSQL release, account-owned Automation store, explicit natural-language schedule preview, IANA timezone, Chat | Automation navigation, scoped UI, existing-usage-ledger runner, and focused Python/Chromium/PostgreSQL QA. Local Windows has only the Microsoft Store Python stub; focused tests ran through GitHub Actions on Linux. `KILAS_AI_AUTOMATION_SCHEMA_APPLY` and `KILAS_AI_AUTOMATION_ENABLED` default off in code; the runner also defaults off via `KILAS_AI_AUTOMATION_RUNNER_ENABLED`. The prior deploy `dep-datrqc942hec73ctit2g` is the rollback point.

Scoped Impeccable detector ran on Automation templates/CSS and the two touched Kilas AI screens. It could not resolve Jinja `url_for` stylesheet links and consequently reported false flat-type-hierarchy warnings; the explicit error-state side-border warning was corrected. Initial Chromium checks passed at 1440/820/390/320; the hardening commit will rerun them.

PR https://github.com/IKUS2024/kilas-works-ai-admin/pull/81 merged into main at `33a403d41b7885e0a26e7545cf77b0db7c8aed9b`. Final head `951cc80da85e75a98e4c9e8832fd34cab077697c` passed all four Automation QA jobs: focused Python, existing Chat/Search/image/PDF/Finance/Assist boundaries, Chromium 1440/820/390/320 plus existing Chat browser checks, and isolated PostgreSQL migration. The final diff was limited to Kilas AI Automation and opt-in 0075 schema; `git diff --check` was clean. Broad legacy workflows failed only in untouched Assist public pricing/language training and old product/Finance navigation assertions; their migration jobs passed.

Production rollout on 2026-09-30 Asia/Bangkok: only `kilas-works-client-hub` was deployed, first as `dep-dau05rid0e5s73dok4s0` with `KILAS_AI_AUTOMATION_SCHEMA_APPLY=true`, then as live `dep-dau06je0tbcc73fg3as0` with that flag `false` and `KILAS_AI_AUTOMATION_ENABLED=true`. A read-only production database query confirmed the 0075 release record and all three Automation tables. The public production root returns a healthy 302 redirect to `/login`.

The one approved Cron Job `kilas-ai-automation-runner` (`crn-dau073vlk1mc73d6ilc0`) is live at merge SHA on 0.5 CPU / 512 MB in Oregon, every minute. It is intentionally disabled with `KILAS_AI_AUTOMATION_RUNNER_ENABLED=false`; its first run logged `claimed=0 completed=0 disabled`. The Render connector cannot copy secret values from Client Hub. Owner was asked to set `DATABASE_URL`, `OPENAI_API_KEY`, `KILAS_AI_OPENAI_WEB_MODEL`, and any custom Kilas AI pricing/cost-cap overrides securely on the Cron environment page, without pasting values into chat. The isolated production QA owner successfully logged in, opened Automation, previewed and activated a reminder, paused it, and deleted it. Authenticated `/kilas-ai`, `/kilas-ai/usage`, `/products/finance`, and `/products/assist` returned 200; public `/login` and Automation CSS/JS also returned 200. Runner activation, timed result delivery, and final verification remain pending the secure Cron environment setup. No Finance, Assist, WhatsApp, AI Admin, or unrelated paid resource was deployed or changed.

## 2026-09-30 owner UX override — manual schedule controls

Owner clarified the preferred Automation creation UX: scheduling should not depend on the user writing date/time phrases inside the task sentence. The main instruction field is only for **what Kilas should do**. Below it, provide explicit tappable scheduling controls for **when** it should run.

Required creation flow:
- Task/instruction field contains only the job, e.g. “Bikinin itinerary Bali 5 hari.”
- Recurrence selector: **Sekali**, **Setiap hari**, **Setiap minggu**, **Setiap bulan**, and later Custom if needed.
- For **Sekali**, show a date picker + time picker + timezone selector.
- Past calendar dates must be disabled/unselectable. If the selected date is today, past clock times must also be disabled/unselectable. Only future date/time combinations may be activated.
- For **Setiap hari**, show time + timezone only.
- For **Setiap minggu**, show weekday(s) + time + timezone.
- For **Setiap bulan**, show day-of-month + time + timezone.
- Timezone must be user-selectable (at minimum Jakarta/WIB and Bangkok, with existing supported zones retained). Store the canonical IANA timezone value.
- Keep a clear human-readable preview before activation, e.g. “Sekali · 30 Sep 2026 · 17:00 · Jakarta (WIB)”.
- Natural-language schedule parsing may remain as an optional convenience, but it must no longer be the primary or required path for creating an Automation.
- The task sentence may be lightly normalized for readability, but schedule/date/time data must live in structured controls rather than being embedded in the task text.

This is a documented product requirement only at this checkpoint; do not treat it as deployed until the Automation form, validation, tests, and production QA are updated.

## 2026-09-30 owner-approved Automation capability direction (design only)

Owner approved the following product direction for future Automation expansion. This is a **design/roadmap checkpoint only**; do not implement or deploy from this note alone.

Output/action roadmap, in practical priority order:
1. **Email delivery first** using the existing Resend infrastructure already used by forgot-password email. Automation results should be able to be emailed to an explicitly selected recipient. Add safe idempotency, sent/failed status, bounded retry, subject/body handling, and optional attachments. Do not let the model freely choose arbitrary recipients without explicit user configuration.
2. **Automatic PDF output** for reports, itineraries, summaries, proposals, and similar scheduled deliverables, reusing the existing Kilas AI PDF renderer where safe.
3. **Search + sources** as a first-class Automation output, preserving real citations and existing Search quotas/cost guards.
4. **Watch/monitoring** that only surfaces meaningful changes or matched conditions, with anti-spam behavior.
5. **CSV/file output** for structured reports/data exports that users can download or receive by email.
6. **Image generation output** for scheduled creative tasks, reusing existing Kilas AI image generation and existing image quotas/cost guards.
7. **Multi-step Automation** so a single schedule can perform a bounded sequence such as Search → filter/select → summarize → create PDF → email result. Steps must be explicit, bounded, observable, idempotent, and must not become an unrestricted agent loop.
8. **WhatsApp delivery later**, only after explicit recipient/consent/template/24-hour-window rules are designed around Meta requirements. Email is the first external delivery channel.

Desired user experience: one Automation can produce one or more outputs (text, PDF, image, CSV/file) and optionally deliver them through an enabled channel such as Email, while also keeping a result record inside Kilas AI. Example target workflow: “Setiap Senin jam 8 cari berita AI penting minggu ini, pilih 10 terbaik, rangkum jadi PDF, lalu email ke saya.”

## 2026-09-30 conversation curriculum and structured schedule candidate

Branch `feature/kilas-ai-natural-conversation-schedule-20260930` starts from remote main `075712374d6d5244ee309f23d932b4a3699e1c65` and preserves the already merged natural response policy from PR #83. The candidate strengthens its correction, multilingual, clarification, tradeoff, and truthful-tool guidance; uses that canonical policy in the actual Search path as well as Chat, Research synthesis, and Automation; and routes complex Automation AI tasks through the existing internal reasoning/cost guard.

An internal TSV curriculum now has 100 authored three-turn scenarios across ten categories, with 40 selected Golden cases, representative good/bad examples, and a deterministic/offline evaluation helper. No customer-facing training page or model selector was added. Automation create/edit now offers structured once/daily/weekly/monthly controls, full IANA timezone validation, exact next-run preview, and a legacy natural-language mode for existing interval schedules. Both forms use the existing canonical schedule JSON and require no migration. Frontend past-time constraints complement authoritative server validation. Focused Python/Chromium QA and final deployment are pending; the existing production Cron secret/activation gate from the V1 rollout remains unchanged.

PR #84 (`https://github.com/IKUS2024/kilas-works-ai-admin/pull/84`) is open at head `e18a492fe606797dc70404604be7f12e088664c9`. A missing mocked web-model setting and cross-test due-run interference were corrected in two follow-up commits. The final-head Kilas AI Focused QA and all four Automation QA jobs passed, including responsive Chromium, existing Finance/Assist boundaries, and disposable PostgreSQL schema checks. The Phase 8 workflow also passed. The final diff touches only Kilas AI implementation, scoped Automation UI, internal tests/fixtures, and this status file; no Finance, Assist, or migration files changed.

The broader master, Phase 9, and Phase 10 PR workflows remain red on unchanged Assist billing/language tests and stale product-entry/Finance browser expectations; the same failures appear on the immediately preceding PR run. The Phase 7 Finance baseline was still running at this checkpoint. A requested merge of PR #84 was rejected by automatic approval review because PR checks were failed or pending, so **no merge or deployment has occurred for this candidate**. Preserve the feature branch and do not bypass that gate. Production Cron remains disabled pending the separately requested secure environment setup.

## 2026-09-30 PR #84 release completion

PR #84 was rechecked before release at head `572c2c6b3fde2dcb08d67f93e896d5848d9261fb`. The Kilas AI-specific checks were green: `focused`, `browser`, `boundaries`, and `postgres-schema` all passed. The remaining red jobs were verified as out-of-scope legacy/baseline failures in untouched areas: Assist billing/language/CRM tests, stale Phase 10 product-entry expectations, Phase 9 Finance onboarding expectation, and the pre-existing Finance baseline assertions. PR #84 itself changed only Kilas AI implementation/UI/tests plus this status document; it did not modify Finance, Assist, or migrations.

After that verification, PR #84 was merged to `main` as `e5d06ede2044776a229ade368d54465abc1fb502`.

Render production release:
- `kilas-works-client-hub` deploy `dep-dau98htg1s2s73c05lm0` is LIVE on the merge commit.
- `kilas-ai-automation-runner` deploy `dep-dau98iid0e5s73ept5n0` is LIVE on the same merge commit.
- Client Hub booted successfully on Gunicorn and Render reported the primary URL `https://app.kilasworks.id` live.
- No production 5xx request logs were present in the post-release verification window.
- The Cron runner completed successfully after the new deploy with `claimed=0 completed=0`.

Read-only production PostgreSQL verification found one active Automation record and one Automation run with `SUCCEEDED`, zero failed runs, and zero overdue due-now rows. The latest stored schedule is a structured one-time schedule using the canonical schedule JSON and `Asia/Bangkok` timezone. No Finance, Assist, WhatsApp, AI Admin, or database migration change was made as part of this release.

Targeted Kilas AI natural-conversation + structured Automation schedule release is therefore deployed and production-healthy. Broad repository workflows may remain red for the verified unrelated legacy assertions above; do not treat those as Kilas AI release regressions.

