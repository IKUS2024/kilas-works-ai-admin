# Kilas AI V1 durable checkpoint

Updated: 2026-09-28. Latest remote main after milestone 1: `a3bd71473ca0cd671e843c8559ca73f2335f0a21`.

## Milestones

1. **Foundation — complete, committed and pushed.** Added default-off `KILAS_AI_ENABLED` gate, account-only route, conditional fourth product-picker entry, user-scoped thread store, seven additive Kilas AI tables, and a checksum-guarded PostgreSQL migration runner. Focused GitHub Actions run [36444675028](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36444675028) passed. No production schema has been applied. No existing product data or schema has been modified by this work.
2. **Core chat — implementation awaiting focused CI.** Added account-scoped thread create/read/rename/delete, bounded recent-message context, JSON/CSRF-guarded SSE send, operation-key duplicate protection, independent OpenAI/Anthropic streaming adapters and one fallback before answer text. UI has history, Fast/Smart/Expert selector, stream rendering, Stop and copy, plus mobile history drawer. Provider model IDs are required through configuration; no model ID is invented. Tests are in `client-hub/tests/test_kilas_ai_chat.py` and will run on the next main push.
3. **Attachments — not started.**
4. **Tools and sharing — not started.**
5. **Usage and plans — not started.**
6. **Billing — not started.**
7. **UI finalization — not started.** Impeccable context was loaded for the new Kilas AI surface. No full-product audit was run.
8. **Production release — not started.** Client Hub has not been redeployed and `KILAS_AI_ENABLED` must remain OFF.

## Schema and configuration

- Local SQLite schema is appended as migration `0071_kilas_ai_v1_sqlite.sql` in `db.MIGRATIONS`.
- Production PostgreSQL must be migrated out of band with `python -m kilas_ai.schema` from `client-hub`, using the production `DATABASE_URL`, before the flag is enabled. This command applies only `0071_kilas_ai_v1_postgres.sql` under an advisory transaction lock, verifies its checksum on retry, and never runs the historical migration chain. **Do not run it until the implementation and focused tests are release-ready.**
- Required feature flag: `KILAS_AI_ENABLED`, default OFF. Provider selection: `KILAS_AI_FAST_PRIMARY`, `KILAS_AI_SMART_PRIMARY`, `KILAS_AI_EXPERT_PRIMARY` (`openai` or `anthropic`; default OpenAI). Model IDs: `KILAS_AI_OPENAI_{FAST,SMART,EXPERT}_MODEL` and `KILAS_AI_ANTHROPIC_{FAST,SMART,EXPERT}_MODEL`. Existing secrets: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. No provider keys have been added or exposed.

## Verification and next action

- Local `git diff --check` passed. Python route/tests cannot run in this Windows environment because `python.exe` resolves only to the Microsoft Store alias and no Python runtime is installed.
- Next: commit and push milestone 2 to main; wait for focused `Kilas AI Focused QA`, fix failures, then implement milestone 3 attachments. Keep production flag OFF throughout development.
