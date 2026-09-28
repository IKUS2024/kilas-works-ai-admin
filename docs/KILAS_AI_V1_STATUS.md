# Kilas AI V1 durable checkpoint

Updated: 2026-09-28. Latest remote main after milestone 4: `c0d9b410e678cbb103e8fdca4399cc8c014f9d3e`.

## Milestones

1. **Foundation — complete, committed and pushed.** Added default-off `KILAS_AI_ENABLED` gate, account-only route, conditional fourth product-picker entry, user-scoped thread store, seven additive Kilas AI tables, and a checksum-guarded PostgreSQL migration runner. Focused GitHub Actions run [36444675028](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36444675028) passed. No production schema has been applied. No existing product data or schema has been modified by this work.
2. **Core chat — complete, committed and pushed.** Account-scoped thread create/read/rename/delete, bounded recent-message context, CSRF-guarded SSE send, operation-key duplicate protection, independent OpenAI/Anthropic streaming adapters and one fallback before answer text. UI has history, Fast/Smart/Expert selector, stream rendering, Stop and copy, plus mobile history drawer. Provider model IDs are required through configuration; no model ID is invented. Focused GitHub Actions run [36445653535](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36445653535) passed.
3. **Attachments — complete, committed and pushed.** Added up to four 2 MB PDF/DOCX/TXT/CSV/JPEG/PNG/WEBP files per message, content/MIME validation, bounded PDF/DOCX/text extraction, durable account-owned DB bytes, owner-only downloads, image content conversion for both provider formats, and pending previews with individual removal. Scanned/image-only PDFs are explicitly rejected rather than falsely claimed as read. Focused GitHub Actions run [36446449648](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36446449648) passed.
4. **Tools and sharing — complete, committed and pushed.** Added OpenAI Responses web-search tool with stored actual URL citations; separate image generation/edit calls and durable generated images; one-time owner share links stored by hash, anonymous read-only page and immediate revocation; regeneration without duplicating the user message. Provider model IDs remain configurable and no tool pretends to run when unavailable. Focused GitHub Actions run [36447369968](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36447369968) passed.
5. **Usage and plans — implementation awaiting focused CI.** Added Free/Plus/Pro/Max limits, user-level atomic pre-call reservations, daily/monthly/paid-period counters, configurable burst/fair-use controls, provider/model/token ledger with null unknown costs, and account-only usage/pricing page. Additive migration `0072` adds usage reservation status. Focused test: `test_kilas_ai_usage.py`.
6. **Billing — not started.**
7. **UI finalization — not started.** Impeccable context was loaded for the new Kilas AI surface. No full-product audit was run.
8. **Production release — not started.** Client Hub has not been redeployed and `KILAS_AI_ENABLED` must remain OFF.

## Schema and configuration

- Local SQLite schema is appended as migration `0071_kilas_ai_v1_sqlite.sql` in `db.MIGRATIONS`.
- Production PostgreSQL must be migrated out of band with `python -m kilas_ai.schema` from `client-hub`, using the production `DATABASE_URL`, before the flag is enabled. This command applies only `0071_kilas_ai_v1_postgres.sql` and `0072_kilas_ai_usage_status_postgres.sql` under an advisory transaction lock, verifies checksums on retry, and never runs the historical migration chain. **Do not run it until the implementation and focused tests are release-ready.**
- Required feature flag: `KILAS_AI_ENABLED`, default OFF. Provider selection: `KILAS_AI_FAST_PRIMARY`, `KILAS_AI_SMART_PRIMARY`, `KILAS_AI_EXPERT_PRIMARY` (`openai` or `anthropic`; default OpenAI). Model IDs: `KILAS_AI_OPENAI_{FAST,SMART,EXPERT}_MODEL`, `KILAS_AI_ANTHROPIC_{FAST,SMART,EXPERT}_MODEL`, `KILAS_AI_OPENAI_WEB_MODEL`, `KILAS_AI_OPENAI_IMAGE_MODEL`. Existing secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Usage configuration: optional `KILAS_AI_BURST_PER_MINUTE` (default 30), `KILAS_AI_MAX_PER_HOUR` (default 300), and `KILAS_AI_MODEL_PRICING_JSON` (no default price map; unknown cost remains null). No provider keys have been added or exposed.

## Verification and next action

- Local `git diff --check` passed. Python route/tests cannot run in this Windows environment because `python.exe` resolves only to the Microsoft Store alias and no Python runtime is installed.
- Next: commit and push milestone 5 to main; wait for focused `Kilas AI Focused QA`, fix failures, then implement milestone 6 billing. Keep production flag OFF throughout development.
