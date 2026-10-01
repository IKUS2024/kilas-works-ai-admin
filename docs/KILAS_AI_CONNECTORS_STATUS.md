# Kilas AI connector release status

Last checked: 2026-10-01. PR #94 merged to `main` as `1c26e93cbe786c9f52d9618691f58604b45cda9c`. Client Hub and the existing Automation runner are live on that commit. Google is unavailable in the authenticated production QA account; there are zero production Google connection rows.

## Implemented

- Account-owned Google OAuth with hashed, single-use state, encrypted refresh credentials, scope checks, reconnect and local disconnect/revoke. Gmail requests read-only plus compose scopes; the compose scope covers Gmail draft creation and sending, while the separate server approval still gates sends.
- Gmail read/search/thread, a real Gmail draft, and a separately owner-approved send of that exact draft; Calendar read/free-busy/create/update/delete; Drive and Contacts read-only tools. A changed Gmail draft cannot be sent under the old approval. Google API calls use fixed hosts and bounded responses.
- A new email needs an address explicitly supplied by the owner or one unique matching Google Contact. A thread reply must match the thread's real sender and reply header. Ambiguous names cannot become guessed recipients.
- Existing business-scoped WhatsApp adapter and existing Finance service adapter. Neither modifies the underlying Assist routing or Finance ledger logic.
- Server-side connector authorization and exact-payload, expiring, single-use approvals with an audit trail. Unknown remote outcomes are terminal rather than automatically retried.
- Agent Connections and approval UI, incremental schedule parsing, and explicit marker for scheduled connector reads/one Gmail draft proposal per run so older Automation tasks retain their prior path. Cron never sends.
- Agent Chat lists pending approvals separately (up to 20), so another scheduled draft does not hide an older pending action.
- Focused SQLite, PostgreSQL and Chromium QA in `.github/workflows/kilas-ai-connectors-qa.yml`.

## Release gates

- Final connector QA run 36809971657 passed: focused connector, existing Agent and Automation tests, PostgreSQL migration, untouched-main baseline comparisons, and 1440/820/390/320px browser checks. Automation QA run 36809971652, Phase 6, Phase 8, Client Session Timeout, and the Phase 7 Finance runtime job also passed.
- Scoped Impeccable detector ran on the Agent template and CSS. It reported a flat-type warning only because it cannot resolve the Jinja stylesheet URL; the linked stylesheet defines explicit heading sizes. No whole-repository design fix was run.
- Phase 9, Phase 10 and Master Completion broad failures were reproduced against untouched pre-PR `main` by the connector QA baseline job. Phase 7 Finance baseline failed 18 tests; the pre-connector PR #93 run 36802449661 failed the exact same 18 named tests, with zero additions. No legacy tests were edited.
- Production PostgreSQL reports release `0077_kilas_ai_connectors` applied at 2026-10-01 03:28:28 UTC with checksum `b79f563c65b1a029cec534ac71565c3f41fc5bee9b092ef1cb192c8617f8e0ff`. Client Hub final deploy `dep-daut7a3ncjis73888pq0` and Automation runner deploy `dep-daut7cjncjis7388958g` are live on the merge commit. The one-time `KILAS_AI_CONNECTOR_SCHEMA_APPLY` flag was returned to `false`; the runner's next scheduled run succeeded at 03:31:12 UTC.
- Authenticated production QA checked Kilas AI Chat, Agent, Connections, subscription/usage, Finance entry, direct Assist entry, and the Admin access gate. Agent task preview, activation, pause, resume and deletion worked in an isolated QA account. Public login/register responded; production request logs showed no 5xx and app/runner logs no errors in the checked post-deploy window. Mobile viewport checks were CI browser checks, not authenticated production mobile checks.
- No real Google, Meta or Finance connector action was exercised in production: the QA accounts had no connected provider/business. No Google connections or action approvals exist in the production connector tables. Two synthetic QA accounts remain; their sole created Agent task is soft-deleted. Never describe an unconfigured connector as usable.

## Production setup required for Google

The owner must create/configure a Google Cloud OAuth web client and consent screen, enable Gmail, Calendar, Drive and People APIs, register the production callback URL `https://app.kilasworks.id/kilas-ai/agent/connections/google/callback`, and set these Client Hub environment variables:

- `KILAS_GOOGLE_CLIENT_ID`
- `KILAS_GOOGLE_CLIENT_SECRET`
- `KILAS_GOOGLE_REDIRECT_URI` (the callback URL above)
- `KILAS_CONNECTOR_ENCRYPTION_KEY` (a persistent Fernet key, kept server-side and backed up securely)

The authenticated production QA account currently sees Google as unavailable. Do not give the service placeholder production credentials. Once the owner supplies and verifies the configuration, connect a real Google account and perform a separately approved live read/draft/send smoke test before calling that provider usable. Existing WhatsApp and Finance availability is determined from their real tenant/business gates.

## Release scope

Only Client Hub and the existing Automation runner were deployed. AI Admin was not redeployed. No production data reset, Finance/Assist rewrite, WhatsApp reconfiguration or payment change was made. The release is operational with Google safely unavailable pending owner-controlled configuration and live provider verification.
