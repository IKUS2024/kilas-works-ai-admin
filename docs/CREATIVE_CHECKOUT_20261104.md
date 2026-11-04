# Creative Services checkout — 2026-11-04

Baseline: clean remote main `c1545bdff16a15f10f83c45bfe01eeee2ab9a93f`.

Six existing package buttons now enter `/creative-services/checkout/creative_{event|social}_{basic|standard|premium}`. Public checkout displays the chosen service and price before login; the signed, 30-minute selection cookie retains service/tier/add-on across the existing password/OAuth/registration login rotation. Authenticated drafts use signed, owner-bound identities. Back/reload and concurrent retries reuse the same persisted invoice. `/creative-services/orders` resumes owned orders after closing the browser.

`client-hub/creative_catalog.json` records the approved public Creative Services catalog and deliverables. These offers differ from legacy Content/Event catalog products, which remain unchanged. The server computes every total and persists the complete offer, customer fields and Bank Mega destination in the project's JSON snapshot. Catalog-version changes require a refreshed checkout. Prices: event 1,500,000 / 3,000,000 / 5,000,000 IDR per event; social 4,500,000 / 6,000,000 / 9,500,000 IDR per month. Optional social influencer additions: 2,000,000 / 3,500,000 / 7,500,000 IDR. No tax, fee, subscription renewal or delivery commitment was introduced.

`/creative-services/payment/<invoice>` shows the complete receiving account and copy control, owned invoice and real upload form. Existing project/invoice/payment/project_files tables provide durable storage; no schema, credential, infrastructure, global bank setting or Finance changes. Existing generic invoice routes redirect these orders to their scoped Bank Mega flow so legacy BCA details cannot appear for them.

The existing account and KILAS_ADMIN checks protect invoice/proof access. CSRF is enforced. PNG/JPEG only, bounded request and 5 MB source limit, MIME/signature/extension validation, traversal/trailing/executable-content rejection, maximum 20 megapixels and no animated images. Pillow verifies, decodes and re-encodes to a metadata-free JPEG before private DB storage. Upload and status change commit atomically. Repeated uploads do not create duplicate records or overwrite review/verified states. No public proof URL, OCR/provider call or automatic payment confirmation.

Authorized admins discover proofs at `/admin/payments`, inspect `/admin/payments/<payment_id>` (including receiving bank, brief and scope), view private proof, and use existing approve/reject/request-reupload controls. Proof submission only sets UNDER_REVIEW; invoice remains ISSUED and project PAYMENT_PENDING. No credits, fulfillment or money transfer occurs on upload. Customer-facing manual-payment explanation is omitted as requested.

The login tagline alone now reads “Create, work, and grow with Kilas.” / “Berkarya, bekerja, dan berkembang bersama Kilas.” via existing i18n; registration copy and layout are unchanged.

## Validation before release

- 11 focused SQLite integration tests: all 15 prices/add-on combinations, snapshot immutability, stale catalog guard, fields, amount/plan/status tampering, CSRF, owner/foreign/anonymous/admin access, malicious uploads, rollback, retries, concurrency, durable reopen, admin queue/rejection/reupload, legacy invoice routing, full account, EN/ID tagline and add-on preservation through real login.
- 30 browser journeys through actual package buttons at 390px and 1024px: all six packages and every social add-on; login return, copy exact leading-zero account, Back, closed/reopened tab, upload, reload and pending status. No external requests or paid transitions.
- Native PostgreSQL 18.6 disposable loopback rehearsal: 15 price combinations, concurrent checkout/upload, JSONB snapshot lookup, private BYTEA persistence and reopen. No paid transition.
- Existing Creative Services 8-test suite and responsive studio browser checks pass, including original enquiry/language/portfolio behavior. The enquiry tests now use its consultation navigation because package buttons correctly enter checkout.
- Existing checkout reliability 25 tests and payment-pending 25 tests pass.
- Source/bundle check and diff whitespace check pass.

Local internal evidence (not uploaded): `/tmp/creative-checkout-browser/{event-checkout,social-checkout,payment}-{390,1024}.png` and `results.json`; `/tmp/creative-checkout-tests.log`, `/tmp/creative-postgres.log`, `/tmp/creative-payment-regression.log`, `/tmp/creative-pending-regression.log`.

Reference PNGs could not be materialized with the current Library helper (download failed). Implementation follows the parent's direct pixel inspection and authorized handoff; parent retains the actual references for independent comparison. Production deployment and authenticated production writes are not claimed by these local results. Synthetic proof images are plain test images; none were marked paid.

## Independent review fixes

Creative checkout endpoints are explicitly allowed through the Finance session routing guard; route-level session, CSRF and owner/admin checks remain enforced. Invalidated customer sessions preserve only validated catalog package/add-on selection in the existing signed, bounded cookie before redirecting to login. Arbitrary return URLs are ignored.

Proof submission and admin verification now share the cancellation owner lock and PostgreSQL payment/invoice/project row-lock order. Closed projects/invoices reject proof and cannot be revived by verification. Customer history/payment and admin detail show the closed state without transfer/upload/approve actions. Regression coverage includes active Finance sessions, revoked login recovery, cancellation, historical inconsistent review state and native PostgreSQL concurrent cancellation/upload/verification (zero paid transitions).

Repository-wide CI has unrelated pre-existing failures: core simulator, WhatsApp, subscription dashboard, Assist continuous training, home markup, Finance dashboard and viewport mock. These were reproduced on both baseline a718e304 and checkout head; relevant checkout/studio/native PostgreSQL checks passed. Full suite is not claimed green.

## Checkout image correction

Replaced checkout/payment card portfolio stills with two generic AI-created service illustrations supplied in asset commit 556d9a57: wedding camera production and phone/product filming with ring light/laptop. Mapping is presentation-only by the stored service, so historical orders render the corrected image without rewriting snapshots, prices, catalog versions or payment state. Both images retain their complete 1859×846 landscape composition at mobile/desktop widths. Alt text identifies them as illustrations. Portfolio assets, login/chat and order/auth/proof behavior are unchanged.

Regression coverage: all six package cards, historical snapshot rendering with unchanged project/invoice/payment records, image response MIME/dimensions, 30 real package/add-on browser journeys with image/framing assertions at 390/1024px, checkout/security suite and exact 61-file source/bundle comparison. Internal screenshots remain in /tmp/creative-checkout-browser; no production order/proof writes are used for verification.
