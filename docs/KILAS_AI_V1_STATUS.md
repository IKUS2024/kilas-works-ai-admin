# Kilas AI V1 durable checkpoint

Updated: 2026-09-28. Latest remote main before this work: `02d98395f95a15635835046e48209b1f7f6478f2`.

## Milestones

1. **Foundation — implementation awaiting focused CI.** Added default-off `KILAS_AI_ENABLED` gate, account-only route, conditional fourth product-picker entry, user-scoped thread store, seven additive Kilas AI tables, and a checksum-guarded PostgreSQL migration runner. No production schema has been applied. No existing product data or schema has been modified by this work. Focused tests are in `client-hub/tests/test_kilas_ai_foundation.py`; this Windows environment has no functional Python installation, so a dedicated GitHub Actions workflow will run them on pushed main.
2. **Core chat — not started.** Threads, messages, provider adapters, streaming, modes, fallback, history and actions remain to be built.
3. **Attachments — not started.**
4. **Tools and sharing — not started.**
5. **Usage and plans — not started.**
6. **Billing — not started.**
7. **UI finalization — not started.** Impeccable context was loaded for the new Kilas AI surface. No full-product audit was run.
8. **Production release — not started.** Client Hub has not been redeployed and `KILAS_AI_ENABLED` must remain OFF.

## Schema and configuration

- Local SQLite schema is appended as migration `0071_kilas_ai_v1_sqlite.sql` in `db.MIGRATIONS`.
- Production PostgreSQL must be migrated out of band with `python -m kilas_ai.schema` from `client-hub`, using the production `DATABASE_URL`, before the flag is enabled. This command applies only `0071_kilas_ai_v1_postgres.sql` under an advisory transaction lock, verifies its checksum on retry, and never runs the historical migration chain. **Do not run it until the implementation and focused tests are release-ready.**
- Current required feature flag: `KILAS_AI_ENABLED`, default OFF. Provider and payment environment variables will be recorded when their milestones are implemented. No provider keys have been added or exposed.

## Verification and next action

- Local `git diff --check` passed. Python route/tests cannot run in this Windows environment because `python.exe` resolves only to the Microsoft Store alias and no Python runtime is installed.
- Next: commit and push foundation to main as instructed; wait for focused `Kilas AI Focused QA`, fix any failure, then implement milestone 2. Keep production flag OFF throughout development.
