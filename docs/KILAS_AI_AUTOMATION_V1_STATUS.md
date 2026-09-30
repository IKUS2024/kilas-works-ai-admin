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
