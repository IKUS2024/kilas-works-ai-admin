# Kilas Assist + Finance master completion

FINAL STATUS: URGENT PRODUCTION DEMO INCIDENT REPRODUCED; FIX AND ROOT-ONLY REGRESSION PASS LOCALLY. Release CI, merge, deployment and live log verification are pending. Real-device retry is required after deployment.

## Production Demo dependency incident — 2026-09-27 11:02–11:06 UTC
- Real owner-device requests reached bot `kilas-works-ai-admin` at deployed source `3db41314186623cdab1699a49ecf2697c87ad19b`, but Render logs contain 16 `[ASSIST_DEMO] processing_failed` entries in 11:02–11:07 UTC. User observed HTTP503. Read-only production DB confirms all five invitations created 11:02:20–11:04:45 have NULL sender and zero events. Five older events belong to a superseded 08:31 session; they are not evidence that the new invitations worked.
- Exact exception reproduced BEFORE editing in a fresh Python3.12 venv installed with only ROOT `requirements.txt`: `assist_demo.process` → `assist_reply` → `assist_business_media` → `file_utils` → `ModuleNotFoundError: No module named 'pypdf'`. `pip check` passes while both pypdf and pikepdf are absent. The prior Hub-installed CI masked this runtime dependency mismatch; successful boot/deploy did not exercise the lazy path.
- Fix: move `file_utils` import into Client Hub's upload-only `assist_business_media.teach`. No exception suppression, parser substitution or extra heavy bot dependency. Bot knowledge lookup and approved-original image/PDF send use the existing DB/transport; Hub validation, PDF extraction, original preservation, approval and tenant boundaries remain unchanged. Root requirements documents this boundary.
- New `test_assist_bot_runtime.py` uses the actual root Flask app, isolated DB, signed webhook, real teaching/test/Ready storage, binding, reply orchestration, Inbox, CRM and original-media transport. Only inference and external Meta HTTP/send boundaries are simulated. All three cases fail with the original missing-pypdf exception before the fix, then pass without either parser installed. Assertions cover owner phone, exact confirmation, sender binding/event rows, exact business knowledge and no foreign facts, same Inbox, Lead→Customer→Job, unbound/foreign refusal, exact original PNG/PDF bytes and tenant ownership, no upload-parser modules loaded, and unchanged Finance rows.
- Master CI now has an independent `root-bot-runtime` job: clean venv, ROOT requirements only, `pip check`, explicit parser-absence assertions, new acceptance suite and existing signed root webhook suite. Hub image/PDF training tests continue separately with Hub dependencies.
- Local root-only new suite3 PASS and existing signed webhook11 PASS. Applicable Assist/media, WhatsApp and release CI results will be recorded before merge/deploy. No production data, Finance behavior, credentials or migration flags changed. No fabricated production webhook used.
- NEXT: exact-candidate release CI → safe merge → affected production deployment(s) → verify LIVE/source and logs. Then owner generates a NEW “Sudah, coba di WhatsApp” invitation and presses Send on the real device. Do not claim real-device completion from these isolated tests.

## Historical business media release — 2026-09-27 09:20 UTC
- [PR61](https://github.com/IKUS2024/kilas-works-ai-admin/pull/61) merged as `3db41314186623cdab1699a49ecf2697c87ad19b`. Exact tested candidate `509e24e93012d5c2918541d93b9063265a397973`; candidate and merged source trees both `954b16ade2ba416f748be62c727f6e7d08a211de`.
- Both production services LIVE at3db4131. Client Hub initial migration deployment dep-dasdrcnlk1mc73bi32lg finished09:11:49UTC; bot dep-dasdru0473hc73fse1kg finished09:12:59UTC; final Hub deployment dep-dasdru97lnhs738p2o40 finished09:13:04UTC after disabling the controlled migration flag. Existing auto-deployOFF retained.
- Only additive0070 applied09:11:48UTC, checksum `85a562631be83d5fd3a5172a09d076d2e7664fafd4bbb3ef89ff2272b0fb15d0`. Earlier0066–0069 checksums unchanged. KILAS_ASSIST_SCHEMA_APPLY set back to false by named-key merge; historical migrations/backfills remain disabled. No credentials duplicated or exposed, no production reset.
- All TEN release workflows SUCCESS on exact509e24e: Master36308149162; Phase2 36308149190; Phase3 36308149194; Phase4 36308149220; Phase5 36308149192; Phase6 36308149183; Phase7 36308149218; Phase8 36308149185; Phase9 36308149206; Phase10 36308149197.
- Protected Finance baseline job108588720879:39 files,1018 tests,PASS,zero skipped. Native PG18 additive rollback/retry, composite file ownership, foreign-FK rejection, deletion isolation and exact seeded Finance preservation PASS. Existing signed owner-phone routing, tenant isolation, Inbox, Customer/Jobs and browser journeys remain green.
- REAL PRODUCTION UPLOAD VERIFIED in the previously authorized pilot workspace: image upload and image→PDF replacement both called the configured model, extracted the visible business facts, and displayed natural confirmations and the taught-file area. Original filename/MIME/business ownership and exact original byte hashes verified by read-only DB checks. Both records had approved_send=0 and explicit internal-only instructions. No file was authorized or sent to a customer.
- Cleanup used the normal Hapus control on the one temporary PDF only (replacement already removed the temporary image). The original preexisting business file, profile, services, FAQs and AI settings compare EXACTLY UNCHANGED by full-row count/fingerprints. The previous test confirmation reappeared. Two new teaching history/audit events remain as an honest record of the verification; two vision usage calls are correctly scoped to the pilot and knowledge_assist.
- All30 Finance table counts and full-row fingerprints compare EXACTLY UNCHANGED before/after deployment and live upload verification. Zero Finance code/template/accounting changes. No payment/Ready/connection approval or fabricated webhook submitted in production.
- Latest checked error-level logs09:11:14–09:20:18UTC: none. Final Render deploy records and live attachment UI match the release. Browser upload needed the documented synchronized file path; an attempted original download hit a browser interception/runtime error, so browser download completion is not claimed. Original byte preservation is verified independently and authenticated download/isolation routes pass automated tests.
- Screenshot of the live taught-PDF controls is saved privately for the user; customer workspace screenshots were not committed to the public repository.

### Remaining live acceptance / next continuation
- Business media implementation, automated acceptance, additive migration, deployment, real image/PDF understanding and cleanup verification are complete. Do not restart them or redeploy for this documentation-only checkpoint.
- Next owner-device check: upload a genuine catalog/photo with its usage instruction, approve relevant customer sending, Tes sebagai customer → Sudah, coba di WhatsApp → Send prefilled invitation → request that catalog/photo. Verify actual received original file, correct business reply and the same Demo Inbox/CRM continuation.
- The available browser has no usable WhatsApp sending device; the prior whatsapp:// device launch is blocked. No mock, synthetic signed event, or deployment result is claimed as proof of real WhatsApp delivery. Connected-production media behavior passes the real adapter/storage/transport regression with Meta HTTP replaced at the boundary; assisted Meta/OTP/device acceptance still needs the existing authorized operator/device.
- Resume from deployed3db4131 plus this checkpoint. The earlier Demo routing override remains intact: bound sender always uses its business, unbound sender gets only the workspace instruction, and legacy OWNER logic is unreachable from the Demo ingress.

## Historical business media implementation checkpoint — 2026-09-27
- Continued from remote main d2ea3c1975aa33995bf98a8e5c7dfbeebeddd282 (deployed source 78d567f6). Branch feature/kilas-business-media-20260927. No completed Demo routing work restarted; Finance implementation untouched.
- Added image/PDF attachment beside conversational training and a small taught-file list with original download, summary, usage instruction, permission to send, remove and replacement. Default file sending requires the owner's explicit checkbox approval; knowledge can be taught without permitting original-file distribution.
- Extracts visible business facts through existing multimodal model routing and confirms naturally. Existing bounded document/image validation; original bytes preserved in business_files. New 0070 metadata separates facts/instruction/approval/version from original bytes, with composite tenant ownership FK. No path from customer Inbox media into this store.
- Test uses the same relevant file knowledge as WhatsApp. Successful current-knowledge test + confirmation retains the existing Ready/invitation/deep-link flow. Upload/removal/replacement/instruction changes invalidate readiness; tenant-scoped originals and knowledge survive verified purchase.
- Demo and connected production use the existing inbox_media_service image/PDF upload/send transport and existing channel credentials. Model selects only a permitted original from that business for a relevant current request; unknown IDs, unrelated/negated requests, expired/rebound sessions, revoked files and human takeover fail closed. Durable per-event claims prevent automatic resend after replay or uncertain transport; sent originals are mirrored into the same scoped Inbox.
- Local regression suite covers multipart image/PDF training, exact original bytes, foreign read/modify/send denial, extracted knowledge in Demo inference, exact original image/PDF upload, Inbox membership, no random media, owner permission revocation, replacement/removal, tested-knowledge binding, verified purchase preservation, production same-media transport, private customer attachment non-promotion, invalid bytes and provider failure. Existing owner-phone/legacy isolation signed-webhook suite PASS.
- Native PG18 CI extends the existing atomic additive migration/rollback/Finance preservation rehearsal with composite ownership and deletion isolation. Deploy Client Hub first with only KILAS_ASSIST_SCHEMA_APPLY=true, keep historical migrations OFF; verify 0070 checksum, then deploy bot, turn apply flag OFF. No production reset, no Finance redesign or accounting migration.
- PR61 initial candidate 7ea32ad2: Master Assist/native PG18 PASS. Phase8 exposed an older Core deployment without Assist tables; fixed by applying the existing Assist runtime feature gate to media delivery, not by bypassing schema errors. All three signed/Core WhatsApp suites and all11 Assist files pass locally after the correction. Broad product questions now include bounded taught-file knowledge without triggering media send. Empty-file businesses retain their previous knowledge identity.
- Next: finish applicable CI on exact corrected candidate, merge, controlled additive rollout, browser/DB/log verification, record exact release evidence. Real device Send and Meta/OTP require the existing external actors; mocked transport is not proof of live delivery.


## Authoritative Demo correction release — 2026-09-27 07:56 UTC
- Continued the existing release without restarting: baseline main d99e41e; former live code234f94c. PR60 merged as `78d567f6edae9c3c3fe24e228e707b05c52849cb`. Tested candidate `418c80a4750ebbb92cc230d47ace8d029135f0be`, tree4e93aea7a4ceace354824317fc1181449055d80d. [PR60](https://github.com/IKUS2024/kilas-works-ai-admin/pull/60).
- Both production services are LIVE at78d567f6: bot deploy dep-dascndnpn0mc73frk2ig finished07:55:04UTC; Client Hub dep-dascndu0tbcc73erm71g finished07:55:08UTC. Existing auto-deployOFF retained; no environment changes, no schema migration, no production reset.
- Root cause verified in source and read-only production state: unbound Demo ingress fell through into platform OWNER commands; production had zero active bound sessions and zero new Demo events before this correction. The separate Ready and WhatsApp steps made missing the binding invitation easy. The owner's phone also skipped platform inbound media persistence.
- FIXED: shared Demo channel terminates before all legacy reasoning. Active bindings use their exact business; unbound/invalid/expired senders receive only “Untuk mencoba Kilas Assist, buka Demo dari workspace Kilas kamu terlebih dahulu.” Infrastructure failure fails closed. The entire platform OWNER dispatch block was removed from public webhook ingress, including owner/customer lookup and command actions. Existing helper functions and authenticated internal transports remain separate.
- FIXED: one “Sudah, coba di WhatsApp” POST validates the successful current-knowledge test, marks Ready, creates a unique invitation and redirects to real6282213039137 with KWDEMO prefill. Confirmation: “Demo aktif ✅ Sekarang chat seperti customer bisnis kamu.” Six-part onboarding still automatically starts the seven-day demo and opens training. Redundant start/readiness/technical-ID controls removed. Existing completed legacy users can resume through an ordinary training action without a manual start step. Connected production hides Demo and preserves knowledge.
- FIXED: fresh explicit binding clears inherited legacy takeover, while repeated invitation preserves current human handoff. The owner's media is stored and linked like other Demo media. Inbox hides the invitation marker while retaining exact event/session membership. Conversational training receives existing onboarding knowledge as context.

### Acceptance evidence
All eight requested cases are automated with real application routes/storage; external AI/WhatsApp transport is replaced only at its boundary:
1. Owner phone passes the real signed webhook, binds, and receives business Demo replies; legacy owner and platform models are asserted not called.
2. Active binding selects the exact business, including separate-tenant rebind/history checks.
3. Unbound owner/other senders get the fixed instruction only; duplicate deliveries do not resend; DB failure and invalid signature cannot reach owner/customer data.
4. Another sender cannot steal a claimed token; foreign owner Inbox404; explicit session rows prevent cross-business history exposure.
5. Real Test POST → confirmation POST marks current tested knowledge Ready, creates pending binding, and opens the correct real number with KWDEMO. Failed/stale tests cannot create it.
6. A distinctive taught price/rule is asserted in both test and real Demo generation input, excluding another business's secret fixture; no platform catalog injected.
7. The same stored inbound/reply rows appear in the authenticated Demo Inbox, with transport marker hidden.
8. That Demo conversation starts as Lead, concrete booking intent promotes Customer and creates the normal Job; foreign business has no Job and Finance receives no test writes.
- Additional checks: owner media membership; expiry/replay; human takeover/resume; fresh invitation versus repeated invite; connected-business Demo hiding and knowledge preservation.

### QA / production verification
- ALL SIX applicable PR workflows SUCCESS on exact418c80a: Master36304159614, Phase2 36304159682, Phase7 36304159618, Phase8 36304159568, Phase9 36304159619, Phase10 36304159680.
- Master CI includes isolated Assist suites plus signed Demo webhook/owner isolation, and native PostgreSQL18 rollback/retry/Finance preservation. WhatsApp and mobile/desktop browser journeys passed.
- Protected Finance baseline:39 files,1018 tests,PASS, zero skipped; job108577361249 finished07:53:56UTC. Finance runtime/native/mobile also PASS.
- Local focused checks: all10 Assist files, root signed ingress11, current Demo9, master journey10, platform takeover8, media webhook9, four Inbox files, tenant runtime/isolation PASS. Old platform media/takeover fixtures now use real current Demo sessions; no production bypass added.
- Production browser shows the new understanding text, “Sudah sesuai?”, “Sudah, coba di WhatsApp”, “Ajari lagi”, and simplified Demo Inbox. An initial reload during the Render swap still showed the old page; a subsequent completed reload verified new UI. No production teaching/Ready/payment forms were submitted for this check.
- Bot boot reports exact78d567f6 and only boolean presence for WhatsApp, OpenAI, Claude, webhook signature and Assist runtime. Both Render deployments report LIVE; no error-level or processing-failed logs in inspected07:55:09–07:56:06UTC window.
- Before/after read-only full-row fingerprint and count comparison of all30 Finance tables is EXACTLY UNCHANGED. There are zero Finance implementation/template/migration changes in this correction. No production financial QA writes.

### Remaining live gate / next continuation
- Real WhatsApp Send and actual signed inbound/reply/Demo Inbox acceptance are NOT certified by mocked transport or deployment status. The connected browser has no usable WhatsApp sending device; the previous wa.me launch reached a blocked whatsapp:// deep link. Do not fabricate provider webhooks, auto-approve owner knowledge, or reset data to claim completion.
- Owner's next action in their own workspace/phone: Latih Kilas Assist → Tes sebagai customer → review answer → “Sudah, coba di WhatsApp” → Send the prefilled message → chat like their business customer. Then verify exact-business reply, scoped Demo Inbox, and Lead/Customer/Jobs from real traffic.
- Earlier master external gates (authorized production operator/Meta/OTP/real connection and legitimate payment/receipt acceptance) remain documented below and are not claimed closed by this Demo correction.
- Resume from78d567f6 and this evidence; do not rerun completed unchanged implementation or redeploy solely for this documentation checkpoint.

## Authoritative latest summary (2026-09-27 06:11 UTC, supersedes historical checkpoint notes below)
- Current remote main at release verification: `234f94c23f989e0dd89811da6a7782bb52511b32`. This documentation checkpoint will be committed above that release; its parent remains the deployed source. Working branch: `feature/kilas-master-completion-20260927`, code milestone `0144f7c1fb5763a184174bcca54a412d82438681`.
- Production baseline before this task: both services at `4344748c439597744806ad8ccb6a5ad7a8a0e54f`. Production NOW: both services LIVE at `234f94c23f989e0dd89811da6a7782bb52511b32`; Client Hub final deploy `dep-dasb2no473hc73fgo95g`, bot `dep-dasb2ofpn0mc73fkuo0g`. Auto deploy remains OFF.
- PR/merge: [PR58](https://github.com/IKUS2024/kilas-works-ai-admin/pull/58) MERGED at 05:59:18 UTC after all ten release workflows passed on exact candidate0144f7c. Main merge tree exactly equals tested candidate tree. No production code edits remain uncommitted.
- DONE: checkpoints1–8 implemented and deployed. Signup-first/six-part onboarding, conversational training/Test/Ready, private bound demo architecture, Inbox/media/safe explanation, CRM and four-state Jobs, authoritative Finance bridge, auditable pricing/usage/router/cost, seven-section Platform Admin, assisted mapping/evidence gates. Implementation and synthetic transport tests are not evidence of real WhatsApp delivery.
- Tests passed: Master Assist/native PostgreSQL18 and Phase2–10 workflows all SUCCESS. Protected Finance:39 files,1018 tests,0 skips,PASS (job108561445869, finished05:58:28 UTC). Native migration rollback/retry/Finance preservation; tenant isolation for Inbox/knowledge/Customer/Jobs/mapping/Finance/support; multi-viewport Admin/support; standalone Finance and same-invoice confirmed Income/Job Selesai browser journeys PASS.
- Bugs/failures diagnosed and fixed: internal Kilas workspace middleware regression; legacy activation/mapping bypasses; demo HUMAN takeover parity; archived synthetic transport/completion fixtures; old pricing/onboarding/navigation expectations. Financial assertions were retained/strengthened. Historical broad repository suite is NOT all green; unchanged legacy/out-of-scope expectations and baseline comparisons are inventoried in `docs/qa/kilas-master-regression-triage.md`. No applicable release gate remains failing.
- Migration/schema: only additive0066–0069 applied atomically at06:00:25 UTC; all four production checksums match committed SQL. Client Hub first, bot second. Assist apply flag is now OFF on both, historical migrations/backfills remain OFF. No reset or Finance accounting migration. Full-row fingerprints and counts of all30 Finance tables are exactly unchanged before/after release; evidence in `docs/qa/kilas-master-finance-integrity.json`.
- Production verification: Home/More/Inbox/Customers/four Job statuses/usage/pricing/training page/separate Finance workspace load successfully. A real Test AI request succeeded from existing knowledge; existing usage ledger records one OpenAI economical-route call under the correct tenant and simulation feature with cost recorded. No knowledge edits, Ready confirmation, invoice/payment or Finance QA writes were made. Both services' allowlisted boot diagnostics show WhatsApp/OpenAI/Claude/signature configuration present and Assist runtime enabled. No error-level logs in inspected post-release window. See `docs/qa/kilas-master-production-verification.md`.
- IN PROGRESS / NEXT: checkpoint9 remaining real demo sender binding/inbound/reply/media and prospect privacy, production operator System/support/connection checks, assisted Meta+customer OTP, signed inbound + delivered outbound, then real authorized invoice/receipt delivery. Existing app customer session is not a production Platform Admin session. Never fabricate signed events, mark Connected manually, or confirm a nonexistent payment to close this gap.
- Remaining external blockers: managed browser cannot open the real WhatsApp device/deep link (organization policy), no accessible WhatsApp sending device, and no authenticated production Platform Admin/Meta operator session or customer OTP. These require the owner/operator. All independent implementation, applicable CI, migration, deployment and available production smoke work is done.
- Resume: read this summary and the production verification report, inspect only changed remote/deploy facts, obtain real device/operator evidence through normal product flows, then update this checkpoint. Do not reread PDFs, restart implementation, rerun unchanged expensive suites, create duplicate PRs, reset data, or deploy solely for documentation. FINAL remains NOT COMPLETE until outstanding live gates pass.


## Current baseline (2026-09-27)
- Current remote main: `4344748c439597744806ad8ccb6a5ad7a8a0e54f` (fresh ls-remote and clone).
- Working branch: `feature/kilas-master-completion-20260927` from current main.
- Repository: IKUS2024/kilas-works-ai-admin.
- Production kilas-works-client-hub: LIVE at the same SHA (fresh Render deploy readback).
- Production kilas-works-ai-admin: LIVE at the same SHA (fresh Render deploy readback).
- Both services on main, auto deploy OFF (preserved).
- Production PostgreSQL 18: available. Infrastructure IDs intentionally omitted from this public checkpoint.

## Source of truth / implementation map
Read all 30 master pages, all 31 detailed blueprint pages, and all 14 pricing pages once.
Precedence: user's MASTER TASK and FINAL OVERRIDES > Master Blueprint > detailed Blueprint > repo legacy docs. Pricing PDF is supplementary only.
- Signup FIRST, existing six onboarding parts, seven-day free demo, conversational training/test/ready, real prospect-private demo WhatsApp, paid activation, assisted connection.
- Exactly two products: Assist and protected separate Finance. No Coexistence, Worker, content/video or website service in the requested product UI.
- Exactly four owner Job statuses: Perlu tindakan, Dikerjakan, Selesai, Batal. Meetings/deals remain NEW; only invoice/payment intent advances IN_PROGRESS; completion requires authoritative Finance posting.
- Finance invoice/payment/ledger stays authoritative. Screenshots are candidates only; human confirmation required; no second ledger and no production Finance QA writes.
- Pricing: Demo 7 days; launch first paid month 99,000 (either selected paid plan, per final prompt); Starter 299,000; Pro 799,000 IDR/month. Auditable rule; bundle Finance entitlement.
- Customer usage no provider/model/token/cost jargon; configurable inexpensive provider route, structured same-call explanation; internal cost attribution.
- Platform SaaS admin separated from customer CRM; auditable support banner; assisted WA queue; fail-closed WABA/Phone ID routing.

## DONE
- Fresh main and both live deployment identities verified.
- Source PDFs fully read and extracted into scratch only.
- Production DB table/column inventory read-only (no secrets selected).
- Production existing authorized customer session inspected: Assist Home and More load, bottom destinations already Home/Inbox/Customers/Jobs/More.
- No applicable AGENTS.md found in repository or workspace ancestors.

## IN PROGRESS
Checkpoints 1–6 have substantial implementation, still not complete. Four-state Jobs, atomic payment completion and auditable pricing now tested. Next: complete demo/manual media, Finance bundle entitlement, production runtime/connection flow, and SaaS Admin; then full QA/deploy.

## Checkpoint 1–2 local implementation (not deployed)
- Existing account creation preserved; returning Google users now enter their existing workspace.
- Product picker shows only Assist/Finance; Assist More removes Services/Content/Talent.
- Home shows readiness/WhatsApp/usage and separate Finance link; Inbox navigation defaults to WhatsApp.
- New assist_journey lifecycle uses existing onboarding_sessions events; trial starts after all six parts and cannot restart on retries.
- New owner-only /business/<id>/train teaches and corrects one canonical FAQ through existing versioned knowledge service, with conflict checks.
- Test AI uses current scoped business facts. Successful test fingerprint must match before owner confirms readiness; failed inference never establishes ready.
- Training normalization preserves current business status. Knowledge stays in existing business/FAQ/config authorities.
- Demo CTA requires readiness and active demo/paid entitlement; connected businesses redirect to production Inbox.
- Additive migration 0066 introduces private demo bindings and explicit event-to-message membership. No Finance services/templates/calculations edited.
- Demo webhook intercept resolves the bound tenant before knowledge/inference; raw message remains in platform Inbox, and only explicit session messages appear in tenant workspace. Duplicate claims precede AI/send; ambiguous sends are not retried.
- Shared sender rebind deactivates old binding without moving old messages. Demo CRM uses tenant WhatsApp identity and same-inference structured facts; actionable leads promote in all tenants.
- Demo reply uses bounded relevant knowledge + recent messages, same-call safe explanation, and configurable OpenAI economical route / Claude escalation. Existing configured Claude path remains available. Provider errors are sanitized.
- Text human replies include an independently verified explicit demo scope on the internal bridge and are linked to that session. Takeover is checked before and after AI.
- Router scopes now include customer_insight, follow_up and assist_demo in the existing usage ledger. Provider dimension and profitability UI still pending.

## Findings / bugs / diagnosis
- `kilas_core/jobs.py` exposes only three owner states and groups COMPLETED into IN_PROGRESS: stale relative to final four-state requirement.
- Home currently promotes demo before training, omits readiness/usage/Finance shortcut; More advertises content/project/talent outside scope.
- Canonical Assist catalog still prices 499,000 and retired Pro 999,000; subscription lifecycle must be reused, not replaced.
- Existing Finance workspaces, entitlements, branches, bridge, invoice/payment services exist: preserve their accounting contracts.
- Demo binding exists in routes_client audit/session state. Found a gap: shared-number messages currently use platform knowledge, not prospect-trained knowledge; rebinding one sender across businesses needs a bounded session history to avoid cross-session exposure. Must fix before certification.

## NEXT (one task; internal checkpoints)
0. Finish current schema/WA/AI/payment/admin inspection and relevant test baseline.
1. Signup-first flow, naming and navigation.
2. Conversational training/Test AI/ready and real prospect-private demo.
3. Inbox/media/safe explanation/CRM.
4. Four-status deterministic Jobs.
5. Authoritative Finance bridge invoice/payment/receipt.
6. Pricing/usage/configurable AI router/cost.
7. Platform Admin.
8. Assisted production WhatsApp connection.
9. Full QA, additive migration rehearsal if needed, merge/deploy/live smoke.

## Tests passed
Fresh protected Finance baseline: 39 files, 1018 tests, 0 skipped, all PASS (logs in scratch /tmp/kilas-master-finance-baseline).
Workspace baseline and post-change suite PASS. New master journey suite: 5 tests PASS (six-part gate, seven-day retry safety, knowledge correction, tenant isolation, current-version successful test required, GETs without model/writes).
New demo suite: 7 PASS (binding, cross-tenant rebind, replay, takeover/media, lead→customer→job, ambiguous delivery, expiry). New router suite: 3 PASS (cheap route, bounded fallback/error redaction, no hidden reasoning/ungrounded action). Journey suite rerun PASS.
## Tests still failing
New isolation test initially expected 403; existing security deliberately returns 404 to conceal tenant existence. Test corrected to exact 404; no authorization weakened. Broader suites not yet run. GitHub commit-workflow wrapper returns no PR-triggered runs for merge main; not evidence of green CI.
## Migration/schema notes
Production contains kw_core_* Jobs/CRM/bridge/WhatsApp and existing subscriptions, ai_usage_ledger, knowledge revisions, Finance tables. Migration 0066 is local only; migration rehearsal and production apply pending. No production data modification performed.
## PR/merge status
Remote checkpoint branch exists; signup/training checkpoint committed as 37246ec. Demo/router checkpoint committed as 540753cb. Finance/Jobs/pricing/cost checkpoint committed as a6fd709. No PR/merge yet. CLI push has no GitHub credential; authenticated GitHub connector can publish changes.
## Deploy status
No changes deployed in this run.
## Production verification
Read-only Home/More baseline only; master journey not verified.
## Remaining external blockers
None established yet. Real production WhatsApp OTP and test messages may need owner involvement; do independent implementation first.
## Resume
Read this checkpoint, inspect working diff/current main only as needed, and continue NEXT without rereading unchanged PDFs or restarting completed work. Keep status IN PROGRESS until all definition-of-done gates are verified.

## Remaining implementation risks at this checkpoint
- Legacy audit-bound demo tests must be migrated to explicit session fixture and preserve isolation assertions; old production demo users will need a fresh binding (knowledge/data stay intact).
- Demo human template/media outgoing attribution still needs the same scope contract as text replies.
- Demo voice/document vision and payment evidence extraction are not yet integrated; original inbound media remains visible.
- Jobs now show four states and Finance bridge atomically completes paid Jobs. Receipt uses existing idempotent transport; real delivery verification pending.
- New pricing is integrated with the existing payment/subscription lifecycle. Finance included entitlement integration, SaaS Admin, production WABA queue, and full production runtime routing still require completion.

## Checkpoints 4–6 implementation update (not deployed)
- Owner Jobs now expose exactly NEW / IN_PROGRESS / COMPLETED / CANCELLED with required Indonesian labels. Ordinary owner/AI updates cannot set COMPLETED; only the private Finance payment actor can.
- Finance bridge calls the unchanged authoritative record_invoice_payment service, verifies PAID/zero outstanding and posted income references, then updates Job in the SAME Finance compound transaction. Job/audit failure rolls back payment and income. External receipt send runs after commit with stable invoice identity; UI/network retry does not add income or another invoice.
- Assist invoice panel shows completed paid invoice and Konfirmasi Pembayaran. Meeting/deal without payment remains Perlu tindakan through existing deterministic gate (additional negation/evidence hardening still pending).
- Launch pricing is an auditable rule with immutable snapshot in existing project requirements + audit. First paid month 99,000, normal Starter 299,000 / Pro 799,000; promo eligibility checks verified Assist invoices across plans. Per-business transaction reuses existing unpaid checkout. Historical locked invoice amounts preserved.
- Verified new-format order applies one existing subscription period per unique invoice and supports idempotent renewal/plan change. Legacy orders keep existing lifecycle.
- Public landing now starts with registration/login and pricing; pricing included on active Demo Home, training conversion and Paket & Penggunaan. Finance remains separate.
- Migration 0067 adds provider attribution to existing ai_usage_ledger (historical default Anthropic). New OpenAI calls explicitly attribute provider; no new cost or Finance ledger.
- Customer counters expose reply/media/follow-up counts and Normal/Tinggi/Hampir capacity status only. Starter/Pro thresholds configurable; high usage never blocks a call.
- assist_costs platform read model provides provider/feature/business costs, projected monthly cost, actual verified subscription revenue, ratio, largest feature and configurable 15%/25% guardrails. Dashboard wiring pending.
- Expired demo sender no longer falls back to platform knowledge. A paid user may request a fresh binding after old session expiry. Journey respects configured subscription grace period.

## Validation at this update
- Assist suites: journey 5, demo 7, router 3, billing 4, costs 2 tests PASS (21 tests across five suites; earlier four-suite aggregate then new cost suite).
- Jobs store and route suites PASS; Finance bridge service and route suites PASS. Bridge shared tests augmented with completion and transaction rollback assertions; financial assertions not weakened.
- Finance protected baseline rerun: 39 files / 1018 tests, one Home navigation-gate regression identified; other 38 files PASS. Fixed Assist Home to respect Finance visibility and selected owned Finance business. Entire affected Finance phase1b suite then PASS (16 tests); protected test unchanged. Final full rerun still required at release gate.
- AI usage diagnostics/monthly diagnostics/monthly query PASS. FX suite initially exposed pre-existing template/test wording mismatch (same mismatch verified on baseline SHA) plus stale 499k price. Restored explicit USD/IDR labels in Admin costs and updated only the reference price expectation to 299k; FX suite PASS with all calculation assertions unchanged.
- Legacy Jobs fixture lacked onboarding/demo schema; added additive fixture tables instead of hiding production errors. Former manual-COMPLETED test expectation was stale against final master rule; now asserts rejection, and bridge tests prove successful authoritative completion.
- Outstanding broad regressions not yet audited: old demo audit-range fixtures, retired-single-plan UI assumptions, old Web labels and public channel behavior. Preserve security/accounting contracts while updating only proven stale expectations.

## Resume priority
1. Finish required Finance bundle entitlement without changing Finance accounting or multi-business/branch semantics; preserve existing explicit bridge mapping.
2. Assisted WhatsApp queue + authoritative WABA/Phone ID mapping and test gates; SaaS Admin/support banner and audit.
3. Full production Assist inference/media/payment evidence/follow-up integration and demo manual media/template scope.
4. Upgrade final regression fixtures, rehearse additive migrations, review complete diff, merge/deploy both services, verify live. Do not certify before these gates.


## Checkpoints 7–8 implementation update (not deployed)
- Added migration 0068 operational connection queue/evidence, without duplicating authoritative WABA/Phone Number ID mapping.
- Verified new Assist subscriptions enqueue Pending. Missing requested phone does not roll back a valid payment; owner can complete the profile and request connection.
- Operator stages, Meta WABA asset membership + requested-number verification, one-use inbound challenge from trusted owner, outbound send claim and signed delivered/read receipt. Both tests must match the current mapping before Activate. Changed mapping invalidates evidence; ambiguous outbound sends are not automatically retried.
- Authoritative inbound resolver now cross-checks canonical CONNECTED config and WABA identity. Unknown/missing identity fails closed. Assisted Core routing supports the verified shared system credential with the tenant's own Phone Number ID.
- Embedded Signup/Coexistence customer writes retired; customer status page exposes business wording only. Public anonymous chat retired while shared WhatsApp Inbox storage remains usable.
- New Platform Admin has seven required sections, tenant detail, subscription revenue/cost summaries, explicit unknown operating expenses, configuration/DB observations, scoped support sessions, permanent banner and action audit. No tenant Finance aggregation.
- Found integration atomicity issue: nested knowledge_writer committed an enclosing commerce transaction. Corrected commit ownership to preserve payment/activation rollback; no Finance calculation or ledger behavior changed.
- New connection suite initially lacked explicit optional Core fixture schema: added existing installers rather than hiding missing tables. Connection six tests and Platform Admin three tests PASS. Added transaction rollback test next; full release gate still pending.
- Production remains baseline, not deployed. Real Meta/OTP/inbound/outbound verification is still pending. These are implemented workflow gates, not claimed production outcomes.

## Remaining at current working checkpoint
- Finish Finance bundle entitlement and owner-visible mapping navigation.
- Production structured Assist inference/CRM/knowledge, media payment candidates, and outgoing demo media/template session attribution.
- Harden deterministic payment intent against negation; finish naming/usage sweep.
- Complete regression diagnosis (including intentionally retired public/self-service paths), browser QA, PostgreSQL migration rehearsal, safe merge/deploy and live verification.
- New platform pages currently require existing optional Core tables (confirmed in production); local fixtures explicitly install them.
- No true external blocker has been established. Do not stop at this intermediate implementation checkpoint.


## Runtime / media / bundle update after reconnect (not deployed)
- Production Assist now uses relevant owner knowledge + bounded recent history, with reply/explanation/incremental CRM in one structured inference. Fenced atomic writes preserve takeover and concurrent owner Job edits. Informational contacts stay Leads; meeting/deal is NEW, explicit payment intent is IN_PROGRESS; negated/hypothetical payment is rejected. Customer-requested human handoff persists until explicit owner return.
- WhatsApp profile name and phone are captured from matching Meta contact identity; name is primary and phone secondary in Core Inbox.
- Migration 0069 adds only tenant-scoped, cached media extraction candidates. Image/PDF originals remain visible. Owner-requested analysis can show detected payment and compare the existing linked authoritative invoice; it never confirms payment, posts income or completes a Job.
- Demo human media/templates now validate explicit session scope before sending and attribute only the exact outgoing message. Accepted sends stay accepted if history attribution temporarily fails, avoiding a misleading resend prompt.
- Included Finance derives from the existing explicit Assist-to-Finance mapping, verified paid subscription and common owner. It creates no subscription/payment ledger. Expired standalone Finance may establish a mapping only when verified Assist already grants the bundle. Original protected expired-entitlement assertion remains unchanged and passes.
- Checkout regression found by broad QA: route and billing service both opened the purchase transaction. Removed the redundant route transaction; new real route POST/retry test proves one purchase and immutable promo amount.

## Current QA facts and diagnosis
- Protected Finance: fresh regression of 38 Finance suites / 1014 tests PASS, plus four Finance baseline tests PASS (1018 total). Finance bridge service/routes including bundle, posted income and rollback assertions: 26 PASS.
- New Assist runtime suite: 3 PASS (tenant knowledge/CRM/four statuses/same-call explanation, in-flight takeover fence, persistent requested human handoff). Media 4 and billing 5 PASS together. Other previously passing Assist suites still need final milestone rerun.
- Broad harness initially used unittest for plain-function legacy files, yielding zero tests in 33 files; corrected to pytest for those files. This was a harness error, not evidence of product failures. Independent legacy suites use separate processes because their module-level DB fixtures cannot safely share one process.
- Remaining failures include obsolete single-plan/499k expectations, removed public chat/self-service journeys, old Brain/navigation/service-catalog labels and old demo audit-range fixtures. These must be updated against final requirements while preserving tenant/auth/idempotency assertions; no tests deleted or skipped to obtain green.
- Baseline comparison proves existing knowledge setup, targeted upgrade and several UI fixture failures predate this task. In-scope blockers still require diagnosis/fix; do not dismiss them merely as pre-existing.
- PostgreSQL rehearsal tooling is being prepared locally; production PG18 schema has not been changed. Do not replay the entire historical migration chain on production. Only an explicit additive 0066–0069 release migration should be applied after rehearsal.

## NEXT after this checkpoint
1. Finish regression diagnosis and retirement-compatible test fixtures; fix in-scope pre-existing knowledge/setup failures.
2. Rehearse additive schema updates and rollback/no-financial-data-change assertions; add controlled release-only migration runner.
3. Browser QA with disposable fixtures, production credential-path/flag review (never print secret values), current-main review, PR/merge, deploy both services and verify LIVE.
4. Real WhatsApp binding, assisted Meta/OTP and inbound/outbound verification remain unverified; never claim them complete from mocks.

FINAL STATUS: IN PROGRESS. No PR, merge or deployment in this task yet. No true external blocker established.


## Concurrent resume verification — 2026-09-27 04:57 UTC
- A resumed session found the original worktree still receiving active edits. It used an isolated worktree at /workspace/scratch/f3a55a3f7ae4/kilas-works-ai-admin to avoid overwriting the ongoing regression work.
- Fresh remote refs: main 4344748c439597744806ad8ccb6a5ad7a8a0e54f; master branch f39d0b5caeeb898b8c6c46a9a78423964b1fe7ca. Both Render production services independently confirmed LIVE at main baseline, auto-deploy remains OFF.
- Independent PG18 PGlite rehearsal PASS: atomic failed-migration rollback, 0066–0069 apply/retry, exact Finance table row preservation, tenant binding/rebind isolation. Log /tmp/kilas-resume-pg-release.log. This does not certify native PostgreSQL concurrent sessions.
- Found missing customer-facing profile fields in Assist knowledge (business name, address, public phone, closed days, payment instructions) and a possible third paid model call after provider fallback plus low confidence. Fixed both in three source files; canonical owner guide now remains in the bounded FAQ set. Private trusted-owner phone is excluded.
- Five new knowledge/router regression cases plus existing journey/router/runtime suites: 16 tests PASS (/tmp/kilas-resume-knowledge-tests.log).
- These four-file fixes were applied to the original worktree only after verifying those paths had no concurrent edits and git apply --check succeeded. Preserve client-hub/tests/test_assist_knowledge_contract.py and the changes in assist_training.py, assist_reply.py, ai_router.py in the next master checkpoint commit.
- Remaining release gates still apply. No production deployment or customer Finance data writes performed by this resumed session.

- Complementary resume fix + checkpoint is now durably published at remote branch `feature/kilas-master-resume-20260927`, commit `714638296a852a5378b27941409f54c602c013ef`. The four implementation/test files are already applied to this original master worktree; no cherry-pick is needed if they remain in the next commit.


## PostgreSQL release rehearsal and regression diagnosis (latest)
- Durable runtime/media/bundle milestone is f39d0b5 on the feature branch. Production is still unchanged.
- New assist_schema.apply_release applies ONLY 0066–0069 with an advisory transaction lock, checksum tracking, atomic rollback and idempotent repeat. Opt-in KILAS_ASSIST_SCHEMA_APPLY=true; historical RUN_MIGRATIONS_ON_BOOT must stay false in production.
- Native local PG process could not switch to a non-root user in this environment. Rehearsal uses official PGlite PostgreSQL 18.3 with a local protocol socket and disposable random schema. This proves SQL/schema/transaction behavior, NOT real multi-process server concurrency.
- Rehearsal PASS: full synthetic baseline, deliberate final-migration failure rolls back all earlier release DDL, successful additive application, idempotent retry, exact before/after rows for ALL existing Finance tables, demo binding/cross-tenant rebind/isolation. Added SaaS overview/economics/system and customer usage queries also PASS on PostgreSQL 18.
- PostgreSQL diagnosis found literal percent wildcard statements passed through psycopg2 bound-parameter execution. Fixed only Assist usage and Customer Insight queries by binding the LIKE patterns; protected Finance DB adapter/calculations unchanged.
- Production public chat resolver always returns 404 and old link-creation endpoint now returns 410. Archived shared-store tests use a clearly fixture-only resolver with original tenant/paid checks; a new unpatched integration test proves ALL public read/write endpoints reject without model calls or writes. No production access gate re-enabled.
- Legacy demo CRM fixtures now use authoritative explicit demo session rows instead of audit-log phone/range inference. Customer suite 14 PASS; public compatibility + retirement 19 PASS; WhatsApp suites 5 + 17 PASS; Operations routes 10 PASS; Jobs store 15 PASS.
- Knowledge baseline failures were stale expectations: legacy maintenance edits are draft-only and preserve approved tenant config; readiness there measures required profile facts, not optional booking/payment/fixed prices. Updated tests retain row identity, history, concurrent writer locks and approved-config preservation. Knowledge setup 13, assist 33, parser 32 PASS; combined semantics/blockers 52 PASS.
- Retired single-plan expectations now test Starter/Pro and 99k promo, retain historical invoice amounts and forbidden Basic reactivation. Pricing compatibility 23 PASS. AI simulation compatibility 11 PASS with bounded cheap-to-strong fallback and unchanged quota/isolation assertions.
- New real Ready-path regression exposed normalization changing FAQ fingerprint after the successful Test AI. Readiness normalization now preserves exact tested source knowledge. New six-test journey suite PASS, including successful Ready and no paid entitlement granted.
- Review-request operation fixtures now seed a paid-completed Job via the private Finance actor, with authoritative payment posting/rollback retained in separate bridge tests. Operations store 14 PASS. Platform Jobs test now requires explicit scoped support entry instead of bare admin tenant access; final rerun pending.
- Synthetic browser QA harness prepared, refuses production service/DB/provider credentials, uses disposable SQLite, real application routes and deterministic external AI boundary, blocks external network, and visibly marks synthetic data. Browser execution/deployment of this harness pending; never count mocked WhatsApp as real end-to-end delivery.

## Current NEXT / release gates
Finish scoped browser journey and remaining regression failures (including retired self-service and old dashboard/catalog expectations), inspect root webhook regressions, review credentials/configuration without values, review complete diff/current main, then PR/merge, additive migration, deploy both services and live smoke. Real demo WhatsApp and assisted inbound/outbound tests remain pending. FINAL STATUS remains IN PROGRESS; do not claim COMPLETE.

- Additional resumed-session QA: signed root webhook batching PASS (2 tests), platform media webhook suite PASS, tenant runtime/isolation 29 PASS, tenant follow-up 22 PASS. Logs /tmp/kilas-resume-test_kilas_whatsapp_webhook.py.log, /tmp/kilas-resume-test_inbox_media_webhook.py.log, /tmp/kilas-resume-tenant-pytest.log, /tmp/kilas-resume-followup-pytest.log. Three top-level test fixtures updated to canonical WABA + current required profile fields, retaining all no-send/isolation assertions; explicit missing/wrong WABA regression added. Patches already applied to original worktree after clean-path/apply checks.
- Removed accidental pricing HTML include from the <title> blocks in assist_training.html and assist_usage.html; the pricing cards remain in page content. Existing journey suite PASS. Changes already applied to original worktree.
- Independently reproduced readiness knowledge_changed after normalization rewrote FAQs. Adopted the concurrently implemented routes_client preserve_status metadata-only fix; additional six-case knowledge contract suite PASS on that implementation. No replacement of the original fix is needed.
- Render browser configuration read reaches sign-in (no secrets read or credentials requested); Render connector service/deploy reads work. Live customer browser session remains available for read-only post-deploy verification. Resumed session has not changed Render settings, deployed, or sent WhatsApp messages.

- Resume coordination: original execution is actively driving the synthetic QA browser (shared tab at kilas-master-qa.onrender.com). Resumed execution leaves that tab/session, production configuration and deployment ownership untouched to prevent conflicting releases. Its remaining working changes are limited to the title fix, three root fixture/security tests, and the already-documented knowledge contract test. Ensure the untracked test_assist_knowledge_contract.py is included in the next commit (it was not included in 5166df4).

- Resume review in progress: isolated session is testing a concrete assist_reply evidence bug (model excerpt may omit a negation and incorrectly advance/cancel a Job). It will change only assist_reply.py and a new focused regression file, then apply after clean-path checks. Please preserve those eventual patches. Latest complementary durable branch is 495ae6767779f91e6e4934fd570c54ed76d9ef38, based on original 5166df4.

- Resume evidence fix completed: reproduced nine failing negation/condition subcases from model excerpts. assist_reply now expands each exact quote to its original customer clause before payment/cancel gates; unrelated affirmative clauses cannot license the excerpt. Five focused cases PASS, production runtime three PASS, knowledge contract six PASS in isolated processes. Logs /tmp/kilas-resume-action-before.log and /tmp/kilas-resume-action-after.log, /tmp/kilas-resume-action-runtime.log, /tmp/kilas-resume-action-knowledge.log. Source patch and new test_assist_action_evidence.py applied here after clean-path/apply checks. Preserve both in next master commit; no Finance source changed.

- Evidence-clause fix and checkpoint are durably published on complementary branch at 136912e67421b48441b0c8b11964c81157356b8c. It includes earlier preserved title/root-test/knowledge fixes on top of original 5166df4. All corresponding source/test patches are already applied to this master worktree; avoid duplicate cherry-picks.

- Resume CI gap closed in configuration: added .github/workflows/kilas-master-completion-qa.yml with isolated, network-blocked Assist suites and native PostgreSQL 18 service running the existing additive 0066–0069 rehearsal in a random schema. Existing Finance CI remains intact. Exact Assist CI command passes 10/10 files locally (/tmp/kilas-resume-assist-ci-command.log). YAML parsed successfully. Native CI result remains PENDING until PR/workflow execution; do not report it passed from local PGlite. Preserve new workflow in next master commit.


## Browser QA / latest production baseline — 2026-09-27
- Remote main rechecked: 4344748c439597744806ad8ccb6a5ad7a8a0e54f. Working branch feature/kilas-master-completion-20260927 at 5166df4 before the next QA fix commit. Both production Render services remain LIVE at 4344748; no production settings/schema/data changed.
- Dedicated free synthetic Render service kilas-master-qa (srv-dasa65d9fdbs73cigm10), deploy dep-dasa65t9fdbs73cignmg, LIVE at 5166df4. It has no production database/provider credentials and blocks external network. Its mocked AI/WhatsApp boundaries do NOT count as real transport verification.
- Real browser navigated all six existing onboarding sections, leaving FAQ and documents optional, then conversational teaching → Test AI → owner confirmation → Siap melayani. Demo period, promo99k, Starter299k, Pro799k, Home, More, natural customer usage labels and separate seven-section Platform Admin rendered. Explicit support entry displayed the permanent tenant banner.
- Browser found training-state label stuck at Belum dilatih after successful teaching; fixed by observing persisted training/test events and extended the journey assertion. Browser also found an early legacy simulator shortcut inside onboarding; replaced with six-step/training guidance. Two malformed page-title includes removed without removing pricing cards.
- Demo launch reaches the external wa.me redirect, which the managed QA browser reports as blocked by organization policy. No WhatsApp message was sent and no real delivery/binding is claimed. Continue with independent QA.
- New fixture harness update enables existing self-service Finance visibility for QA and fixes the visible synthetic-data banner for body tags with attributes. These changes await the next QA deployment.
- Five commerce invoice UI tests exposed a pre-existing missing accessible file-description/size-validation affordance on subscription proof upload. Restored it on templates/invoice.html only (NOT tenant Finance UI/services/calculations). All five now PASS. Targeted production security/upgrade suite 19 PASS; journey6, knowledge5, assisted connections7, Platform Admin3 PASS.
- Remaining broad failures are being compared once against current-main baseline using documented Client Hub cwd and pytest per-file isolation. Logs: /tmp/kilas-remaining-regression and /tmp/kilas-baseline-comparison. Do not mark them waived or delete tests to obtain green.
- NEXT: finish browser Jobs/Inbox/Admin and new QA fixes, diagnose remaining production-path failures and stale assertions, credential/flag review without values, then PR/merge/additive migration/deploy/live verification. FINAL STATUS: IN PROGRESS.

- Resume follow-on work: updating only three stale dashboard expectations in test_customer_dashboard_cleanup.py to the Assist-only Home and retained authorized historical-project routes. No dashboard or Finance source changes planned; all cancellation, ownership, CSRF, payment-history and concurrency assertions remain. Native workflow addition is saved remotely at f9a1d8136f90a64d94ea7f1be1887fcd3aaf7ffc.

- Dashboard cleanup regression: 18/18 PASS after three stale UI expectations were moved to Assist Home and authorized historical-project routes. All cancellation/ownership/CSRF/history/idempotency/concurrency assertions retained; no production source change. Applied test_customer_dashboard_cleanup.py patch after clean-path check. Log /tmp/kilas-resume-dashboard.log. Next isolated fixture audit targets test_payment_checkout_reliability.py price/history/UI expectations.

- Payment checkout reliability 25/25 PASS in original worktree (/tmp/kilas-resume-checkout-original.log). Original session concurrently corrected current-price fixtures; resumed session preserved those edits and added explicit historical Rp999k invoice row immutability/catalog preservation assertions plus current admin amount/risk labels. No payment/Finance implementation changed. Latest original milestone fa7597a includes all evidence, title, root fixture and knowledge fixes. New master CI workflow + dashboard/payment test updates remain to include in next original commit.
- Release ordering review: Client Hub must apply additive 0066–0069 before the new bot starts, because signed webhook processing now reads kw_assist_connections. Keep RUN_MIGRATIONS_ON_BOOT=false and use KILAS_ASSIST_SCHEMA_APPLY=true only for the controlled Client Hub release; verify checksum rows then turn it off. Both services need existing Core/Customers/Jobs/Playbooks/Operations/WhatsApp Core gates plus KILAS_ASSIST_RUNTIME_ENABLED for intended fleet routing. Credential presence and actual provider/transport success remain separate evidence. Native CI result and production deployments still pending; both live services rechecked at baseline 4344748.

- Complementary checkpoint dfb17f6167f5caa5d3cb608ca9af96ffc0258f6b is now remote, based on original fa7597a. It preserves the new native-PG workflow and passing dashboard/payment fixture updates already in this worktree. No duplicate cherry-pick is needed.

- Resume final runtime review: testing demo customer-requested human handoff. Production Assist persists HUMAN requests, but assist_demo currently drops the same structured _handoff_requested field. Isolated session will patch only assist_demo.py/test_assist_demo.py if reproduced; no changes to QA browser/deployment ownership.

- Demo handoff parity fixed after a failing regression: a customer HUMAN request now persists takeover before its acknowledgement is sent; later demo messages remain stored but do not invoke AI/send until owner explicitly resumes. Eight demo tests PASS (/tmp/kilas-resume-demo-handoff-after.log), preserving isolation/rebind/expired-session/delivery-uncertainty assertions. Source/test patch applied after clean-path checks.
- Master QA workflow now also runs on the two task branches, allowing native PostgreSQL proof before the final release PR. It performs disposable tests only, with contents:read and synthetic loopback DB credentials; no deployment or production secret access. Native run still pending until remote push result is observed.

- Remote resume checkpoint 55b98f0fb080061922927ee33a1bff9233be642b includes the applied demo handoff fix and task-branch master CI trigger. Native CI is being observed on this branch; original release branch remains authoritative and no production/QA deployment is being driven by resumed session.

- NATIVE POSTGRESQL GATE PASSED on resume commit 55b98f0fb080061922927ee33a1bff9233be642b: GitHub Actions run 36297070287, additive-postgres-release job 108557789607. Native PostgreSQL 18.6 log confirms atomic deliberately failed migration rollback, additive 0066–0069 apply, idempotent retry, exact Finance row preservation and demo tenant binding/rebind isolation. The intentional nonexistent_migration_function error is the rollback test, followed by PASS. Evidence: https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36297070287 . This closes the native-server SQL/transaction rehearsal gap; it does not claim production deployment or real WhatsApp delivery.

- Resume narrow regression cleanup now owns only test_checkout_payment_pending_fix.py (same observed admin label mismatch) and test_business_hub_v2_phase_a.py (role=img accessibility attribute falsely treated as a login role selector). No application source changes planned.

- Narrow regression fixtures complete: checkout pending suite 22 PASS and signup/login/admin-bootstrap phase A 20 PASS. Login test now inspects named form controls instead of rejecting the harmless SVG role=img accessibility attribute; original owner/admin routing and bootstrap security cases remain. Admin proof-review labels now match rendered Tagihan/Terbaca/Selisih/Duplicate Risk. Both patches applied after clean-path checks; logs /tmp/kilas-resume-checkout-pending.log and /tmp/kilas-resume-login-roles.log. Native master CI run 36297070287 finished SUCCESS for both Assist regression and PostgreSQL release jobs.

- Resume coordination: opened a DRAFT release PR on the ORIGINAL master-completion branch (not the complementary resume branch) to start existing release CI while QA continues. Reuse this PR; do not create a duplicate. It is not merged, has no requested reviewers, and makes no production changes. Release/deployment ownership remains with original execution. Also review legacy browser harnesses in Phase 2–10: they still navigate retired public chat and may need explicit synthetic compatibility fixtures/current journey assertions, never a production public-channel re-enable.

- Draft release PR is #58: https://github.com/IKUS2024/kilas-works-ai-admin/pull/58 . Head at creation fa7597a; base main4344748. Both native resume CI jobs are already green. Keep PR draft until remaining release gates are resolved; use this existing PR for subsequent master commits and eventual merge.


## Release hardening and browser checkpoint after fa7597a
- QA service latest LIVE: fa7597a1ffb29f1556f86c0b285693ca7bb8876f, deploy dep-dasae4h7lnhs738bdfj0. All seven Platform Admin pages opened successfully in browser; support entry/exit and exactly four Job filters verified. Fresh real registration form → two-product picker → Assist business creation → wizard step 1 verified on this build. Synthetic-data banner now visible.
- Finance shortcut now remains visible for Assist/owned Finance workspaces even if the separate product marketing flag is off. This grants navigation only; Finance service authorization, entitlement and accounting checks remain unchanged.
- Legacy admin Activate POST now redirects to the authoritative assisted business detail instead of bypassing signed inbound/outbound gates. Legacy connected-channel refresh cannot change Phone ID, WABA or credential reference without the assisted workflow. Two additional bypass tests PASS; assisted connection suite now 9 PASS.
- Retired Embedded Signup/Coexistence suite updated to final assisted-only contract: all 41 original scenario test functions retained. Each old public-write scenario now proves HTTP410, no external transport, no business/mapping/payment/subscription/audit mutation, including replay, missing payment, bad identity, cross-tenant and secret cases. Direct helper/CSRF/ownership/state/transaction coverage retained; positive assisted evidence and rollback are in test_assist_connections. 41 PASS.
- Baseline comparison completed once for unresolved suites against 4344748. Most failures reproduce on main and are stale incomplete-profile or old dashboard/catalog expectations. Corrected actual regression fixtures use explicit demo membership, canonical WhatsApp mapping and current catalog price; historical Rp999k invoice row and accounting differences remain exact. Foundation26, paid lifecycle8, subscriptions31, Inbox25, workspace10 PASS.
- Original baseline/full comparison logs are /tmp/kilas-baseline-comparison and /tmp/kilas-remaining-regression; no unresolved case should be called passed. Remaining fixture updates, native-PG CI, final regressions, release review, production flags/credentials verification, migrations, merge/deploy/live smoke are still NEXT. No production mutation or real WhatsApp delivery has occurred. FINAL STATUS: IN PROGRESS.

- Draft PR #58 CI now exposes expected obsolete browser assertions: Phase 9 fails at the old five-item operator nav (admin now has seven Platform Admin sections). Resumed session owns only kilas_workspace_browser_qa.py expectation updates for this CI failure, with support-scope security added and Finance browser journeys retained. Phase 8 currently fails the old Pro-price lifecycle fixture, and Phase 10 fails the public chat assertion in paid lifecycle; original session is already editing those files.

- Phase 9 CI browser expectation patch applied after clean-path check: seven SaaS Platform Admin sections replace the retired five-item admin landing, Jobs expects Selesai as fourth state, six-step onboarding cannot offer early simulation, and explicit support entry/banner/foreign-tenant denial/exit are asserted at all five viewports. Existing Finance browser routes, product switching, screenshots, layout/focus/JS checks and legacy operational smoke remain. Syntax/diff checks PASS; browser execution is PENDING on the next original PR head, not claimed green. File: client-hub/tests/kilas_workspace_browser_qa.py.

- CI on 4419244: master native/Assist QA is SUCCESS. Phase 3/4/6 all reach browser QA then fail the same retired demo/share UI assumption in public_chat_browser_qa.py; resumed session now owns that script plus its test-only public_chat_dev.py fixture endpoint, preserving production HTTP410 and the existing explicit compatibility resolver. Phase 8 root tenant suite now hits the new stricter assisted legacy-refresh guard; resumed session will update only those legacy root validation fixtures, not provisioning security.

- CI follow-ups applied: root tenant suite now 29 PASS against the hardened 4419244 provisioning guard. Duplicate/new legacy mapping is rejected before network or writes; credential failure/success/secret tests explicitly refresh already-validated legacy mappings. New assisted activation bypass tests remain unchanged. Log /tmp/kilas-resume-refreshed-tenant.log.
- Public browser CI fix applied: test explicitly expects production share creation HTTP410, obtains the seeded synthetic path from an owner-scoped /dev fixture endpoint, then retains shared-store CRM/takeover/isolation assertions and current Percakapan label. Production resolver remains retired; fixture uses the already-documented test-only compatibility resolver. Syntax passes, browser verification pending next PR head. Files public_chat_dev.py/public_chat_browser_qa.py.

- Original release execution now owns remaining browser fixture updates: kilas_playbooks_browser_qa.py, kilas_operations_browser_qa.py, phase10_release_dev.py/phase10_release_browser_qa.py and the two final product labels in kilas_workspace_browser_qa.py. It will add only scoped disposable compatibility ingress, preserving production retirement/Finance assertions. public_chat_dev.py helper completion will be changed narrowly to the existing private Finance actor. Keep production/QA deployment ownership here.

- Resumed session also owns Phase 10 CI browser/harness compatibility now: actual 4419244 failure is obsolete picker labels (Pilih Layani Customer/Keduanya), followed by the known retired share path and old payment-confirm button. Updates will keep both Assist-plus-Finance and standalone Finance/accounting browser scenarios, use only an owner-scoped synthetic shared-chat fixture, and preserve production HTTP410. Phase 7 Finance runtime/native/mobile job already passed on 4419244; full Finance baseline still running.

- Phase 10 CI compatibility patch applied: picker now asserts exactly Assist/Finance and retains the sequential Assist-then-Finance scenario; retired share POST is asserted HTTP410 and replaced only for archived synthetic transport by authenticated /dev/chat-path. Existing Finance ledger/account/budget/draft/partial-payment/isolation cases remain. Payment confirmation selector matches Konfirmasi Pembayaran and now additionally requires resulting Job Selesai. Phase 9 picker labels also corrected from observed CI DOM. Syntax checks PASS; full browser execution remains pending next PR head.

- Coordination overlap resolved: original ownership note for Phase 10 arrived during resumed patch work. The above Phase 10 and Phase 9 picker changes are ALREADY applied, and Flask smoke confirms anonymous/foreign /dev/chat-path=404, authorized synthetic path=200, production link POST=410, archived fixture GET=200. Resumed session stops editing these files now; original may continue/review those applied patches. No full browser pass claimed.

## Latest release QA checkpoint
- Current main/production baseline remains 4344748; working branch feature/kilas-master-completion-20260927 at 4419244 before this QA fixture commit. Existing PR #58 remains draft/unmerged.
- Native PostgreSQL 18 additive rehearsal and Assist regression both PASS on master branch CI run 36297382650. Phase 10 old-code/additive migration readback also PASS (job108558638383). Phase 7 core/native/mobile Finance job PASS; full Finance baseline result still pending.
- Phase 2–6 failures reached browser QA after successful SQLite/PostgreSQL tests; actual error was the retired Coba Demo/shared-link entry. Archived transport browser regressions now explicitly assert production link HTTP410 and use an authenticated synthetic fixture path; production public resolver remains 404. Existing shared-store takeover/CRM/isolation and protected Finance checks retained.
- Phase 9 expects seven Platform Admin items and scoped support banner; product picker tests use Assist/Finance. Phase 10 retains all Finance ledger/draft/partial-payment assertions and adds paid Job Selesai assertion. Playbooks/Operations browser ingress updated to the same scoped synthetic fixture. Browser rerun pending next head.
- Single purchase path 12 PASS; root canonical tenant/assisted-refresh suite 29 PASS. Browser scripts compile and git diff --check passes. Production still untouched; real demo WhatsApp/assisted OTP and transport verification still pending. FINAL STATUS: IN PROGRESS.

- Finance CI diagnosis: exactly one of 1018 tests fails, test_finance_phase1b.FinanceUITests.test_dashboard_button_gate, after the intentional Assist Finance-shortcut visibility change. Resumed session will update only this navigation expectation while adding explicit beta-off GET/POST denial and zero-financial-row mutation assertions. No Finance service/template/calculation change.

- Finance navigation test corrected and strengthened: all 16 phase1b UI/security tests PASS (/tmp/kilas-resume-finance-nav-gate.log). With beta OFF the Assist Finance navigation label may be visible, but Finance GET and initialization POST must remain 404 and exact accounts/categories/transactions rows unchanged. Existing owner/foreign/admin/CSRF/ledger checks remain. Patch applied to original; no Finance implementation or UI design touched. The full 1018 baseline must be observed green on the next CI head.

- Resumed durable checkpoint 0f717220ea232668c2a21bd7595820cf6eb7f035 is remote on complementary branch, based on original 4419244, preserving current browser fixture follow-ups, 29-pass legacy refresh fixture, strengthened 16-pass Finance nav gate, native CI evidence and PR58 release handoff. All patches already exist here. Original execution continues browser fixture ownership and release; do not duplicate/cherry-pick these working paths. Production still not deployed.

- Original execution diagnoses Phase9 follow-on /admin/customers=404: new support middleware accidentally blocks the pre-existing dedicated Kilas Works internal workspace. It owns a narrow middleware correction for that exact stored internal scope only (never customer tenants, never while supporting another business), with regression coverage. Also owns safe server-only configuration health reporting for final release credential verification; no secret values will be emitted.

- Resumed CI review on 983e81e: Master/native, Phase2–5 and Phase10 all PASS. Phase7 runtime PASS, baseline pending; Phase8 pending. Phase6 fails only its synthetic legacy-complete helper: public jobs.update_job correctly rejects the private Finance actor (invalid_scope). Resumed session now owns only this helper in public_chat_dev.py, will call the existing private transaction API in the disposable fixture. Production Job completion guard remains unchanged. Phase9 middleware fix stays with original execution.

- Phase6 synthetic helper fixed narrowly in public_chat_dev.py: uses jobs.transaction + private jobs._update_job with existing Finance actor for archived completed-history fixture. Public update_job and authoritative Finance completion security unchanged. Flask fixture smoke PASS: anonymous/foreign denied, production owner completion rejected, scoped fixture completion200 and retry unchanged. Log /tmp/kilas-resume-phase6-fixture.log. Full browser rerun remains pending next original head; patch already here, include with next commit.

- Latest fixes verified: Platform Admin/read-only/configuration/support-isolation suite5 PASS and signed webhook/authenticated no-secret health suite3 PASS. Protected Finance phase1b16 PASS. Phase9 bug was a real new middleware regression, corrected only for the stored Kilas Works internal scope when no customer-support session is active. No customer tenant bypass added. Native Assist and Phase2–5/10 CI PASS on983e81e. Next commit carries these fixes and Phase6 fixture correction.

- Resumed review: Phase8 CI36297797718 also PASS on983e81e. Phase7 baseline finished with exactly the known single Finance nav expectation failure (1018 tests; job108559766947); its tested fix is already staged for the next head. Historical broad logs are NOT a current full-suite pass: unresolved pre-existing suites and retired-dashboard/service-catalog assertions remain in /tmp/kilas-regression-comparison.json. Additional changed failures are old admin Finance action-center context (3), checkout plan card (1), and catalog unfinished-project link (1); these are outside the current supported Assist/standalone Finance release journeys, which Phase10 verifies. Do not report the entire historical repository suite green.

- Original execution now owns narrow fixture updates in test_ai_setup_reliability_and_persistence.py, test_onboarding_auto_normalize.py, test_client_hub_v1.py: baseline already fails incomplete profile/phone forms; tests must supply current required facts and exercise final assisted gate. All persistence/isolation/normalization assertions retained.

- Resumed production preflight is READ-ONLY: production PG18 is available; no kw_assist_* release tables exist yet. Recorded count + sorted row fingerprints for all30 Finance tables in docs/qa/kilas-master-finance-integrity.json (no raw financial rows, amounts, contacts or secrets). Use identical query after additive deployment to compare; genuine concurrent customer activity may legitimately change a hash. No database writes, configuration changes or deployments by resumed session. Include this preflight evidence in durable release checkpoint.

- Resumed 849b271 CI diagnosis: Phase4/5/6 stop at the same single jobs-route assertion, which still expects the dedicated internal Kilas workspace to require customer-support scope. Original middleware intentionally restored internal access. Resumed session owns only test_kilas_jobs_routes.py alignment, retaining explicit customer-tenant denial and support-scope isolation; no middleware changes.

- Jobs internal-workspace fixture alignment complete: all17 jobs-route tests PASS (/tmp/kilas-resume-internal-jobs.log). Existing lifecycle checks retained; added direct customer-tenant denial, blocking internal scope during explicit customer support, and restoring internal access after support exit. This test-only change is already applied to the original worktree. User reconnect instructions at12:49 WIB preserve the same task; no restart, no completed implementation removed.

- Reconnect durable resume checkpoint is remote at ff492a55cf352e40008c6798f806c7cf293fc3c1, based on original849b271. It includes the17-pass Jobs isolation fixture and all30-table production Finance preflight fingerprints. These files already exist here; no cherry-pick needed. PR58 on original remains the sole release PR.

- Final targeted persistence fixtures now PASS: AI setup reliability30, auto-normalize5, Client Hub V1 auth/ownership/persistence22, Jobs routes17, assisted mapping9. Forms now submit current required description/business and owner phones; no runtime validation weakened. Old admin Connect WhatsApp POST now redirects to assisted detail without mutations, matching the already-retired Activate POST; regression proves neither legacy route invokes provisioning.
- Phase9 multi-viewport product/Admin/support browser is SUCCESS on849b271 (run36298180860). Phase2/3/8/10 and Master/native also SUCCESS. Phase4/5/6 on that head failed only the internal Jobs fixture assertion; corrected17-pass test is included next. Phase7 full1018 still running at last poll; runtime/mobile is green.

- Resumed release coordination on0144f7c: all complementary fixes/preflight artifact are now committed on the authoritative branch. No further source edits owned by resumed session. Original owns PR58 readiness/merge, configuration and both deployments; resumed session will observe CI and independently compare read-only Finance fingerprints after deployment. Production remains baseline until original releases.

## Release candidate0144f7c
- Remote main remains4344748. Candidate0144f7c has nine green PR workflows: Master/native, Phase2/3/4/5/6/8/9/10. Phase7 full Finance baseline still running on this head; runtime/native/mobile Finance is green. Full1018 Finance step is now SUCCESS on previous849b271, artifact upload finishing. No Finance code changed between those heads.
- PR58 marked ready; no reviewer messages sent. Merge/deploy remain pending final gate. Core Finance source and templates have zero changed paths. Potential-secret diff scan matched only the explicitly synthetic loopback PostgreSQL CI URL.
- Production preflight fingerprints of30 Finance tables are durably committed. Release configuration will be merged by key only, never replace environment or print secrets. Client Hub migration flag first, bot after successful additive0066–0069 checks; historical migrations/backfills remain disabled.

## Release authorized execution — 2026-09-27 05:59 UTC
- ALL10 PR workflows SUCCESS on0144f7c1fb5763a184174bcca54a412d82438681. Phase7 full protected Finance:39 files,1018 tests,0 skips,PASS (job108561445869, final log05:58:28UTC); Phase2–10 browser/native/scoped suites and Master/native all green.
- Fresh remote main4344748, candidate0144f7c. PR58 ready, mergeable. Proceeding with user-authorized merge and sequential deployment. No production mutation has occurred at this exact pre-merge checkpoint.

- PR58 MERGED successfully as234f94c23f989e0dd89811da6a7782bb52511b32. Client Hub nonsecret release flags merged by key; historical migrations/backfills disabled, only Assist schema apply enabled. Bot flags unchanged until Hub schema validation. Production rollout IN PROGRESS.

- Client Hub234f94c LIVE via dep-dasb1ju0tbcc73ekrct0 at06:00:27UTC. All4 production checksum rows exactly match committed0066–0069 SQL, applied atomically06:00:25UTC. KILAS_ASSIST_SCHEMA_APPLY now disabled by key merge. Render env-update operation itself starts a deploy despite autodeployOFF; an extra same-SHA explicit deploy was queued before that behavior was observed. Reapplication is checksum-idempotent; do not trigger duplicate bot deploy.
- Bot nonsecret runtime flags now merged only after Hub/schema proof; expected234f94c deployment is being observed. Both final LIVE/configuration checks and Finance fingerprints/live smoke remain pending.

- Independent resumed production verification: both Client Hub and bot are LIVE at234f94c. Final Hub deploy dep-dasb2no473hc73fgo95g; bot dep-dasb2ofpn0mc73fkuo0g. Repeated the identical READ-ONLY fingerprint query after both became live: all30 Finance table row counts and full-row fingerprints are EXACTLY UNCHANGED from preflight. No production Finance QA writes were made. Post-deployment result appended to docs/qa/kilas-master-finance-integrity.json; include with final durable checkpoint. Original continues browser/configuration verification.

- Resumed independent production configuration read: allowlisted ASSIST_CONFIG startup logs on BOTH services at234f94c report WhatsApp/OpenAI/Claude/webhook-signature credential presence and Assist runtime=True. Only booleans/commit were read; no credential values. This confirms configuration presence, not actual provider connectivity or WhatsApp delivery. Observed live authorized Assist Home and training/pricing DOM with required navigation and99k/299k/799k labels; no knowledge/payment messages submitted by resumed session.
