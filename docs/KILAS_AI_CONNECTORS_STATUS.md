# Kilas AI connector release status

Last checked: 2026-10-01. PR #94 (`feature/kilas-ai-connectors-agent-20261001`) is a draft. The connector schema and code have **not** been deployed to production. Client Hub and Automation runner still run the existing main release.

## Implemented in the branch

- Account-owned Google OAuth with hashed, single-use state, encrypted refresh credentials, scope checks, reconnect and local disconnect/revoke.
- Gmail read/search/thread, a real Gmail draft, and a separately owner-approved send of that exact draft; Calendar read/free-busy/create/update/delete; Drive and Contacts read-only tools. A changed Gmail draft cannot be sent under the old approval. Google API calls use fixed hosts and bounded responses.
- Existing business-scoped WhatsApp adapter and existing Finance service adapter. Neither modifies the underlying Assist routing or Finance ledger logic.
- Server-side connector authorization and exact-payload, expiring, single-use approvals with an audit trail. Unknown remote outcomes are terminal rather than automatically retried.
- Agent Connections and approval UI, incremental schedule parsing, and explicit marker for scheduled connector reads/one Gmail draft proposal per run so older Automation tasks retain their prior path. Cron never sends.
- Focused SQLite, PostgreSQL and Chromium QA in `.github/workflows/kilas-ai-connectors-qa.yml`.

## Release gates

- Focused connector, existing Agent, existing Automation, PostgreSQL migration and 1440/820/390/320px browser checks: branch runs through `b65efa2` passed. The next run at `254bd2b` exposed a scheduled-draft test assertion about retry wording; the assertion has been corrected and the new provider-draft flow is pending rerun.
- Scoped Impeccable detector ran on the Agent template and CSS. It reported a flat-type warning only because it cannot resolve the Jinja stylesheet URL; the linked stylesheet defines explicit heading sizes. No whole-repository design fix was run.
- PR broad suites: Kilas AI Automation passed. Phase 10 and Master Completion reported failures in previously existing Assist/product-entry paths. The connector workflow reproduced the same failing checks against untouched `main`; these are confirmed baseline failures, not connector regressions. Phase 9 reported a Finance entry heading mismatch and is being compared against untouched `main` as well. No legacy tests have been edited.
- No production database migration, deploy or provider authorization has occurred. Never describe an unconfigured Google connection as usable.

## Production setup required for Google

The owner must create/configure a Google Cloud OAuth web client and consent screen, enable Gmail, Calendar, Drive and People APIs, register the production callback URL `https://app.kilasworks.id/kilas-ai/agent/connections/google/callback`, and set these Client Hub environment variables:

- `KILAS_GOOGLE_CLIENT_ID`
- `KILAS_GOOGLE_CLIENT_SECRET`
- `KILAS_GOOGLE_REDIRECT_URI` (the callback URL above)
- `KILAS_CONNECTOR_ENCRYPTION_KEY` (a persistent Fernet key, kept server-side and backed up securely)

Without that setup, the UI reports Google as unavailable and no Google API call or send can occur. The service must not be given placeholder production credentials. Existing WhatsApp and Finance availability is determined from their real tenant/business gates.

## Planned release procedure after gates pass

Review diff against current main; mark PR ready and merge. Set `KILAS_AI_CONNECTOR_SCHEMA_APPLY=true` on Client Hub for exactly one merged-commit deployment to apply checksum-guarded additive migration 0077, then turn it off. Deploy the changed Automation runner only after the schema exists. Verify both services on the merged commit, logs and no new 5xx, then smoke-test Agent/Connections, Chat, subscription, Admin, Finance and hidden Assist routes. Use no production data reset or WhatsApp/Finance reconfiguration.
