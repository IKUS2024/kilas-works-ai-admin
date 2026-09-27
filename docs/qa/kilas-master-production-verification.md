# Master release production verification

Observed 2026-09-27, approximately 06:00–06:11 UTC. This is a partial production certification, not a claim that all real WhatsApp flows passed.

## Release and data integrity

- PR58 merged as `234f94c23f989e0dd89811da6a7782bb52511b32`; its tree equals candidate `0144f7c1fb5763a184174bcca54a412d82438681`, with all ten required CI workflows green.
- `kilas-works-client-hub`: final deploy `dep-dasb2no473hc73fgo95g`, LIVE at06:02:45 UTC.
- `kilas-works-ai-admin`: deploy `dep-dasb2ofpn0mc73fkuo0g`, LIVE at06:02:44 UTC.
- Both run the merged release SHA; autodeploy remains disabled. Environment updates merge explicitly named nonsecret flags and do not replace environment maps.
- Render environment updates themselves initiate a deployment. One redundant same-SHA Hub deployment was observed before this behavior was known; checksum-idempotent release application made no duplicate schema changes.
- Only Assist0066–0069 applied, atomically at06:00:25 UTC. All four checksums matched repository SQL. The temporary schema-apply flag was then disabled; historical migration/backfill flags stayed disabled.
- All30 Finance table counts and sorted full-row fingerprints match the preflight exactly. See `kilas-master-finance-integrity.json`. No financial QA writes were performed in production. Finance core service, branch accounting and Finance templates were not changed by this release.

## Production checks passed

| Surface | Observed evidence |
|---|---|
| Assist Home | Existing owner and business preserved; readiness and pending WhatsApp visible; five navigation destinations; separate Finance shortcut |
| More | Finance, usage, training/Test, WhatsApp, business/account/support/logout destinations visible |
| Pricing and usage | Demo7days/no card, first paid month99k, Starter299k, Pro799k; Normal and business-level usage counts, no customer provider/token/cost terminology |
| Training/Test | Existing knowledge answered a real customer-style test correctly enough for owner review; owner confirmation remains required and was not clicked |
| Actual inference accounting | One economical OpenAI call recorded in the existing usage ledger, correct tenant and simulation context, cost present; no second explanation call |
| Inbox | Tenant-scoped WhatsApp Inbox and demo binding entry load; this owner currently has no bound WhatsApp thread, so media rendering and real delivery are not certified here |
| Customers | Scoped Lead/Customer filters and contact list load |
| Jobs | Exact filters Perlu tindakan, Dikerjakan, Selesai, Batal; existing Job remains visible |
| Finance | Separate existing workspace loads with existing branch/currency/navigation and records; no financial forms submitted |
| Owner/admin separation | Attempted Platform System entry from the customer session returned the owner's Finance workspace; no platform data was exposed. Full Admin actions were verified in isolated QA/CI, not in this production owner session |
| Runtime configuration | Both services log only allowlisted commit and true/false presence for WhatsApp/OpenAI/Claude/webhook signature/Assist runtime; all present/enabled |
| Runtime errors | No error-level logs returned for both production services in the inspected06:02:45–06:06:55 UTC window |

Existing authenticated Finance preference redirects public registration/landing attempts into that owner's workspace. A fresh anonymous production registration was not performed; signup-first forms and actual registration are covered by the identical-code release browser tests and isolated QA. Existing browser login was preserved.

## Still requires real operator/device evidence

1. Owner reviews Test AI and confirms readiness when satisfied, opens Coba WhatsApp Demo and presses Send from a real WhatsApp device. Confirm actual signed inbound, reply and only the bound prospect thread in Demo Inbox; check a second prospect cannot read it. The managed browser's device/deep-link opening is blocked by organization policy; synthetic events are not a substitute.
2. An authorized production Platform Admin signs in through normal authentication. Verify System's authenticated bot bridge, queue, business detail and scoped support banner/audit in production. No admin account was fabricated or privilege elevated for testing.
3. With a VERIFIED paid business, the operator completes Meta number registration using the customer's OTP directly in Meta, syncs the authoritative WABA/Phone ID mapping, receives the signed inbound challenge and delivered outbound receipt, then activates. OTP/secrets must not be added to this report or chat. Do not mark Connected without both evidence gates.
4. Using a real authorized business transaction, verify invoice WhatsApp delivery, inspect payment evidence, and let the responsible human confirm payment. Check the SAME authoritative invoice/payment/Income/Job Selesai and paid receipt. Automated rollback/idempotency/accounting assertions already passed; no fictitious production payment should be posted for QA.
5. Verify Connected removes demo entry and retains the same trained knowledge, then record the actual live evidence in the master checkpoint before declaring COMPLETE.

No real WhatsApp message/OTP/production financial payment was fabricated, and no secret values appear in this report. All remaining work belongs to the same master task.
