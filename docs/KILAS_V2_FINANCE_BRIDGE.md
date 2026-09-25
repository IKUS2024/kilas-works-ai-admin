# Optional Finance Bridge — Phase 7

One existing Finance engine serves Standalone and Connected modes. Standalone
requires no Core schemas, rows, flags, customers, Jobs or AI Admin subscription.
Bridge is default-off and adds only owner-reviewed links to existing Finance APIs.

## Installation and activation

No deployment or production migration is part of this change. For an authorized
staging rollout only, after existing Finance migrations through 0059 and explicit
Core installers 0055/0056/0057:

```
cd client-hub
python -m kilas_core.finance_bridge_schema --apply
```

The installer chooses the paired 0060 backend SQL and installs immutable history
triggers in one transaction. Repeat installation preserves data. App boot never
installs Bridge. Set `KILAS_FINANCE_BRIDGE_ENABLED=true` only after installing;
existing Core/customer/job flags, business allowlist, active AI Admin subscription,
both OWNER memberships and Finance entitlement gates still apply. Disable this flag
to hide Bridge; it never disables Standalone Finance. Mapping disable preserves all
historical links and Finance data. Existing links are still readable while mapping
is disabled or Finance is read-only, under existing Finance access rules.

Owner workflow: Job/Customer Finance card → connection settings → explicitly choose
owned Finance business and active Business branch → confirm. Explicitly select a
Finance customer ID or review/create a new customer; names/phone/email never merge.
From Job, enter item descriptions, integer quantities, prices, currency, issue and
due dates; confirm to create DRAFT. Open Finance for authoritative review, issue and
payment. No AI/chat path calls Bridge writes; no Bridge issue/payment/FX endpoint.

## Atomicity and contracts

- Four additive Core tables: versioned connections, customer links, invoice links,
  operation records. All append-only, with scoped foreign keys and stable IDs.
- One customer link per source/customer/Finance business; one invoice per source/Job.
  New mapping versions never retarget a historical link. A second draft for the same
  Job is rejected; use authoritative Finance editing/void rules as appropriate.
- Browser-generated 32-hex operation keys are stable within the submitted form.
  Canonical request hash includes owner and payload. Same retry returns original
  result; changed payload using the same key is rejected. New key for existing link
  is rejected, not silently interpreted as success.
- Reviewed Finance `_write` accepts optional related business IDs. Exact owner checks
  and ascending business locks serialize mapping changes plus Finance creation.
  Nested existing Finance services reuse this transaction. New lock expansion is
  rejected. Ordinary Finance calls preserve their previous boundary.
- Finance create, Core link, operation record and both audit events commit together.
  Failures restore every row. No success guessed after a partial failure.
- `get_invoice_totals(..., include_identity=True)` reads status, currency, customer,
  branch and monetary totals from one Finance snapshot. Default output is unchanged.
  Core does no duplicate payment math and never treats claimed transfers as payment.
- Audit includes owner/source/target/branch/version, Core reference, resulting Finance
  object ID and operation key. No full customer payload or secret is logged.

## Validation and limitations

Service tests share identical cases between SQLite and disposable PostgreSQL 18,
including four concurrent customer/draft retries, rollback after Finance creation,
foreign tenant rejection, mapping revisions, expiry, raw history guards and payments
made through Finance. Real Flask tests cover CSRF, limits, confirmations, mobile form
payloads and independent Finance-only use with zero Bridge rows. CI mobile script
uses a loopback fixture and synthetic data only, including partial-payment readback.
See Phase 7 status for exact pass/pending evidence; this document is not certification.

Mapping settings enumerate existing owned active Business branches; workspace setup
stays in Finance. Five items can be entered in the minimal Bridge form; further draft
editing uses Finance. Existing protected accounting services enforce all dates, minor
units, item totals and supported currencies. This is operational cash Finance, not a
claim of a double-entry accounting suite.
