# Text Group Chat release — 2026-10-16

Base: main `381f425080c88885bb354889e938d9c10877bb43`, verified against GitHub and Render LIVE `dep-db93ffnavr4c73ct9qp0` before implementation. Authorized target: `IKUS2024/kilas-works-ai-admin`, Client Hub `srv-da7ti2psrm7s73dh9i2g`, My Workspace `tea-da34t2gu01pc73ft7uf0`. Only Group Chat text is added.

## Behavior and boundaries

Personal / Group tabs extend the existing AI Chat. Authenticated account owners create named groups. Invitation tokens have 256 bits of randomness, are stored only as SHA-256 hashes, and can be replaced/revoked by the owner. An anonymous invitation reveals neither the group name nor history. A short-lived HttpOnly SameSite invitation cookie preserves the exact local return destination across password login, registration and OAuth session rotation. Joining is an explicit CSRF-protected consent action; visiting/logging in never joins automatically.

Active members can read ordered durable text history, send text, mention `@Kilas`, choose Ask AI, and request a decision/action summary. The AI never starts a conversation or introduces itself. Prompts contain only this group's messages and member display names. No Personal store, attachments, connectors, email, file tools, calls, or external actions are available to this AI path. UI copy follows the existing Indonesian/English/Spanish/Chinese App Language setting. AI is instructed to follow conversation language.

Group-owner settings provide member removal, invitation replacement/revocation, an AI pause switch, AI request count and a link to existing account usage/budget controls. Removal is durable, fences rejoining through existing links, and immediately denies every subsequent server history/send/summary/settings request. The polling client clears its displayed history on an access denial. Previously received messages cannot be recalled from another person's device.

## Concurrency and accounting

Separate group/member/message/operation tables isolate group histories and Personal chats. Membership and history reads/writes share the group row lock (SQLite uses BEGIN IMMEDIATE). Messages have increasing database IDs and unique operation/role pairs. A server-derived group/member/client key and payload fingerprint prevent replay/mutation of an accepted operation. Only one AI request runs per group; ordinary human discussion remains admissible during it. No ambiguous or failed AI request is automatically regenerated.

AI calls use the existing `usage.reserve` / `usage.finish`, premium-capacity checks and top-up ledger under the creator's user ID; members' balances are never used. Membership and owner AI controls are rechecked after admission and before provider dispatch. Removal during generation prevents answer publication/delivery to that requester. Actual returned usage settles through the existing ledger, including provider work already performed when access is revoked. Existing sponsorship, plan limits, pricing and credit amounts are not changed.

## Migration and rollback

Additive migration `0099_kilas_group_chat_{postgres,sqlite}.sql` creates four isolated tables/indexes only. PostgreSQL startup applies only this new release through an advisory-locked, transactional checksum guard; existing historical migration settings are unchanged. SQLite's initialization is idempotent. No old rows, financial records, subscriptions or balances are rewritten.

A code rollback to the preceding commit disables the new routes/UI and leaves these additive tables/history intact for a later forward release. No destructive down migration should be run on production. Reapply is checksum-idempotent and safe after a failed deployment.

## Verification

All provider responses are synthetic; tests block real outbound requests. No real invitations, production test accounts, payments, provider generations or balance mutations were made for QA.

- `tests/test_kilas_group_chat.py`: **16 passed**. Current revocable auth sessions, creation/escaping, all private route isolation/CSRF, invitation login/register return + explicit consent, replacement/revocation/removal, cross-group/Personal exclusion from AI, owner-only usage and credit debits, depleted owner capacity denial, owner pause, concurrent retries/AI mutex, removal during admission/generation, failed retry, pagination/order, four UI languages and Personal-stream regression.
- `tests/test_kilas_group_postgres.py`: **PASS**, disposable loopback PostgreSQL 17.11. Deliberate failed-DDL transaction rollback, additive apply/reapply/checksum mismatch, preservation sentinel, real psycopg2 SQL, six concurrent text retries -> one message, duplicate AI -> one dispatch/owner usage row, membership and removal/revocation. Disposable schema removed afterward.
- `tests/kilas_group_browser_qa.py`: **PASS**, Chromium, 1280×900 and 375×812. Two authenticated participants, polled text/AI updates, explicit summary, owner pause, anonymous invitation privacy, member removal clears UI/history, Personal tab/composer, no horizontal overflow or JavaScript errors. Synthetic screenshots retained in `/tmp/kilas-group-browser-evidence/` during execution. Final visual fix removes composer overlap on mobile.
- Existing AI Call Python suite: **26 passed**. Existing Call engine/player JavaScript suites: **24 passed**. No Call implementation was edited.
- Existing quota suite **5 passed**, billing suite **2 passed**, Personal chat **7 passed / 1 unchanged baseline assertion** after adapting only the test runner's legacy login fixture to current server-backed sessions. No existing test files or assertions were changed. The remaining Personal assertion rejects an Indonesian phrase anywhere in rendered HTML, but that phrase is present in the pre-existing embedded translation catalog. The exact same assertion fails on clean `381f425`; baseline comparison is in `/tmp/kilas-group-personal-baseline.log`. New Personal stream/privacy regression passes with real current auth.
- Python/JavaScript syntax and `git diff --check`: PASS.

## Limits

Safe polling runs every three seconds while the page is visible. AI answers are published as complete text, rather than streamed. Context/summaries use at most the latest 200 messages / 28,000 characters; the UI states the window. Groups support up to 50 active members, 50 groups created per owner, text messages up to 6,000 characters and a bounded send rate. Removed members cannot self-readmit via another invitation link. Crashed/uncertain provider operations are not retried automatically. Real provider response quality/language matching and real multi-user production use remain untested because paid provider QA was not authorized.

Deployment evidence is recorded in the final handoff after GitHub main and Render LIVE are verified.
