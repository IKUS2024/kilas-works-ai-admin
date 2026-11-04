# Business identity and payment readiness — 2026-11-04

This is a review-only change. No deployment, verification submission, live transaction, credential creation or payment configuration change is included.

## Public information and provenance

- Retained the existing site identity: Kilas Works / CV Kilas Teknologi Kreatif. This is repository evidence, not independent legal-document verification.
- Added exactly the owner-confirmed office street line: Taman Ubud Indah VII / 18.
- Made the existing site WhatsApp number visible and directly reachable: +62 822-1303-9137. The number/configuration is unchanged; ownership has not been independently verified.
- Added a sign-in-required link to `/kilas-ai/usage`. Copy distinguishes AI account billing from Creative Services bookings via the existing WhatsApp consultation flow.
- Explicitly states that the wallet is a preview and automated QRIS/virtual accounts are unavailable. The preview remains disabled, without payment submission or invented balances/rates.
- No bank account number is added to public pages or this document. No prices, charges, booking terms or Finance implementation are changed.

## Existing implementation

`client-hub/kilas_ai/payment_gateways.py` returns `ManualTransfer` unconditionally. Subscription and capacity operations create pending invoices/orders through `billing` and `topups`; they do not create provider checkout sessions. `billing_routes.py` renders authenticated invoices using shared `payment_service.BANK_DETAILS`, with proof upload and authorized admin review. The existing shared destination is a personal BCA account, not the requested company settlement destination. It remains unchanged in this patch.

`/kilas-ai/usage` renders `credits_usage_preview.html`; `?view=legacy` renders the existing settings/billing page. Authentication and account boundaries are preserved. The generic gateway protocol is already the appropriate future integration boundary. No unused adapter, callback route, database migration or configuration toggle is introduced merely to suggest that integration exists.

## Information needed before business verification

Confirm the legal registered company name against documents, especially its spelling relative to bank records. Supply the complete registered/operating address (city/regency, province, postcode and country as required by the actual verification form); the supplied street line alone is not a full address. Confirm that the existing WhatsApp is the intended business contact and supply an authorized business email if required. Confirm the private company settlement account and account-holder match through an authorized channel. These fields must not be inferred from the street name or copied from a personal payment destination.

The actual Xendit onboarding requirements and account/channel activation status must be checked in the owner's authorized Xendit account before submission. This document does not claim the website now satisfies provider verification or invent refund/privacy/service policies. Any missing required policy must be supplied/approved before publication.

## Future integration implementation gates

1. Agree which existing product/order types are payable, their unchanged authoritative prices/currency, and whether the preview wallet is to become an actual product. Its custom-amount conversion and wallet terms remain unresolved.
2. Select and verify the current Xendit API contract and available QRIS/VA channels; use approved test access first. Keep provider credentials server-side. Separate test/live configuration and do not log credentials or bank details.
3. Persist provider payment references against tenant-owned pending orders with authoritative amount/currency; avoid duplicate checkout on retries. Keep manual orders and their authorized review distinct.
4. Authenticate provider callbacks using the selected API's documented mechanism. Match amount, currency, order and tenant; handle duplicate, delayed and out-of-order callbacks idempotently in a transaction. Redirect/success pages must never grant credits or subscription access.
5. Test expiry, failure, cancellation, provider outages, reconciliation and exactly-once entitlement changes, plus access isolation and forged callbacks. Reuse the existing billing authority rather than bypassing it.
6. Separately authorize company settlement setup, provider verification submission, live channel activation, release and any live transaction. None has happened in this change.
