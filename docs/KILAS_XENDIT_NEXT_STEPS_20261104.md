# Checkout implementation findings — 2026-11-04

## Product direction correction

The owner clarified the earlier instruction: "ini yg skrg kan hanya luna bro yg lain ga ush karena kan gw bikin gratis yg bayar nnti hanya generate gambar". Chat is intended to be free with Luna, with image generation intended to become paid. Subsequent voice-over monetization may also be considered; this does not establish permanent free access to every non-image service.

The newly added Pro/fixed-pack summary has therefore been removed from the new wallet preview. It risked presenting historical billing constants as the new pricing strategy. The extra route price context, fixture values and section styles were removed too. Legacy billing remains reachable and its handlers/prices/entitlements are unchanged. The disabled checkout explicitly states image-generation and voice-over credit rates are not set. No statement here establishes active runtime flags or enables free usage.

## Source facts, not new offers

| Item | Current implementation | Evidence |
| --- | --- | --- |
| Customer-facing Kilas Pro | Rp99,000 / 30 days; new invoice on renewal | `templates/kilas_ai/usage.html`, `kilas_ai/billing.py:review` |
| Internal identifier for that offer | PLUS, not PRO; gateway hardcodes PLUS | `kilas_ai/payment_gateways.py:ManualTransfer.subscription`, `kilas_ai/usage.py:PLANS` |
| Fixed capacity packs | MINI Rp25,000; EXTRA Rp50,000; POWER Rp100,000; 90 days after verified payment | `kilas_ai/topups.py:PACKS`, `create_order`, `review` |
| Other retained plan records | PRO Rp149,000; MAX Rp299,000; not selected by current subscription checkout | `kilas_ai/usage.py:PLANS`, `payment_gateways.py` |
| Old custom-amount helper | Integer IDR 20,000–100,000,000, 365-day expiry; no production caller found | `kilas_ai/topups.py:create_custom_order`, `review`; callers are tests |
| Audio is separate | 60 sec Rp19,000; 300 sec Rp89,000; 600 sec Rp169,000 | `kilas_ai/audio_store.py:PACKS`, `audio_billing.py` |
| New custom-amount wallet | Design-only, no rate or purchase min/max; no authoritative universal credit balance | `templates/kilas_ai/credits_usage_preview.html`, `docs/KILAS_CREDITS_USAGE_DESIGN_20261021.md` |

Pack allowances and custom-order budget ratios are internal provider-cost accounting. They must not be advertised as customer credit units or a rupiah-to-credit exchange rate. The old custom helper's limits and expiry are not authorization for the proposed wallet. Preserve custom-amount intent; the fixed-pack summary describes the existing system only.

Existing terms and privacy templates already contain business contact `kilasworks@gmail.com`. This is repository evidence, not independent ownership verification. Their general subscription paragraph defers specific payment terms to the applicable product/invoice. It does not define the new wallet's refund, expiry, transferability, conversion, minimum/maximum, tax/fee treatment or failed-job charging policy. Do not invent those terms or adopt provider terms on the owner's behalf.

## Smallest practical automated checkout

Follow the confirmed free-chat / future paid-image direction. Do not build automated checkout for historical Pro/fixed-pack offers by inference. Define the custom wallet’s image entitlement and any separately approved voice-over policy first. A hosted checkout alone does not define what a payment buys.

Xendit's current [session overview](https://docs.xendit.co/docs/payment-sessions-overview) and [one-time flow](https://docs.xendit.co/v1/docs/payment-1) support server-side `POST /sessions`, `session_type=PAY`, `mode=PAYMENT_LINK`, IDR/ID, followed by redirect to the returned `payment_link_url`. Use automatic capture and disable saved payment methods; do not turn a 30-day manually renewed product into automatic recurring billing. [Create-session API](https://docs.xendit.co/apidocs/create-session).

Implementation still required:

1. Freeze the purchase amount, currency, product/entitlement version and owner in a local pending order. Add provider/session/payment references and test/live mode in separate persistence, keeping old manual invoices distinct. Gateway protocol currently returns only a local integer invoice ID; it needs a deliberate hosted-session handoff, not an unconditional adapter swap.
2. Create/reuse a session server-side. Handle timeouts and uncertain creation without blindly making duplicate orders. Store provider references/expiry, restrict redirects to the trusted provider response and keep sensitive customer fields out of logs. Never derive a charge from browser-submitted prices.
3. Authenticate callbacks and verify business, session, reference, amount, currency and actual captured success. The [session callback schema](https://docs.xendit.co/apidocs/webhook-notification-sent-defined-webhook-url-updates-payment-session) identifies completed/expired sessions; [payment callbacks](https://docs.xendit.co/apidocs/payment-webhook-notification) supply payment/capture evidence. Session completion alone is not sufficient for unrelated SAVE/authorization flows. Xendit's [webhook handling guidance](https://docs.xendit.co/docs/handling-webhooks) documents callback tokens, duplicates, retries and out-of-order delivery.
4. Apply entitlement exactly once inside a database transaction, uniquely keyed by payment/order. Extract the existing grant logic behind a trusted settlement boundary; do not impersonate a KILAS_ADMIN or fabricate an uploaded proof to call today's `review` function. Browser return pages only read status.
5. Reconcile pending/uncertain orders through authenticated [GET /sessions/{session_id}](https://docs.xendit.co/apidocs/get-session) and correlated payment evidence. Define expiry/late-payment handling; retain an auditable exception queue rather than silently losing money or granting twice.
6. Mock-test tampered prices, foreign owners, forged callbacks, duplicate/late/out-of-order events, retries/timeouts, currency/amount mismatch, captured vs authorized state, cancellation, reconciliation and double-grant prevention before separately authorized provider testing/live activation.

## Exact outstanding decisions and access

- **Product decisions (pending):** the intended custom-amount wallet for image generation, and any separately approved voice-over paid usage, need a customer-facing credit definition, conversion/rates, IDR min/max and increments, expiry/refund rules, fees/tax and usage debit semantics. Do not infer these from internal budgets or old custom orders.
- **Account/channels (unknown, not proven inactive):** owner-side Xendit account verification and availability of the chosen QRIS/VA channels have not been inspected. [Xendit's checklist](https://docs.xendit.co/docs/payments-integration-setup) requires activated live channels and separate test/live credentials; inactive channels fail. Approved amounts must also meet each selected channel's limits, which have not been confirmed for this account.
- **Secrets/access (not configured by this work):** no Xendit adapter or referenced Xendit configuration exists in inspected application code. Existing secret availability is unknown; no secret values were requested or inspected. An authorized operator must later securely supply the permitted API credential, callback verification token and merchant/business identity, and configure the callback endpoint. Creating credentials/persistent access is outside the current permission.
- **Business/legal (pending confirmation):** confirm legal entity spelling against registration and company bank-holder records; confirm the full office address is appropriate for verification; confirm existing support email/contact and supply the approved wallet/checkout-specific policies. Company Bank Mega settlement setup remains a separate owner-side action. Public contact publication does not configure settlement.

No provider API call, payment, credential creation, bank replacement, Xendit submission or agreement acceptance was performed. Backend integration remains real engineering work; mock-only scaffolding without agreed entitlement semantics would not make checkout ready.

## Historical validation of the removed summary

Single-plan/console suite passes (6 tests), including existing ledger-preservation and authentication checks and a new regression that varies authoritative prices and verifies rendered values without creating invoices/orders. Manual billing suite passes (2 tests). Credit & Usage browser suite passes 10 size/language cases, retaining custom input validation, disabled payment, keyboard tabs and zero network writes. Updated desktop/mobile screenshots and report are under `docs/qa/business-payment-20261104/`. No provider integration is exercised or claimed by these local checks.

## Correction validation

The six-test console suite includes a regression that rejects Pro/fixed-pack prices in the new preview while confirming the unchanged legacy checkout remains reachable. Billing suite (2 tests) and responsive browser checks (10 size/language cases, disabled checkout, custom-input validation, tabs and no network writes) pass for this correction. Screenshots in `docs/qa/business-payment-20261104` are updated to the corrected UI.
