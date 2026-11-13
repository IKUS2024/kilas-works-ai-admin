# Credit & Usage: Rp99,000 / 30 days

The owner requested reactivation of Credit & Usage: manual bank transfer,
required proof upload, a single admin approval, and repeated AI use for 30 days.
Free limits and owner exemptions must not change. No production payment is
approved as release QA. Finance data, accounts, ledger and UI are untouched.

## Behavior

- The real subscription checkout replaces the inactive 2,000-credit preview.
  The server selects PLUS at Rp99,000; client amounts/plans cannot override it.
- Uploading a valid proof only enters review. Admin-only CSRF-protected approval
  grants the existing account subscription. Replays cannot grant again;
  rejection allows a new proof. Renewal preserves the unused active term.
- Active paid accounts use Chat/search/documents/images, audio/Voice Over,
  Translator and AI Call without additional commercial top-ups. Existing
  authenticated provider readiness, disable switches, file/duration limits,
  per-request/rate/concurrency protection and external-action consent remain.
- Existing active PLUS/PRO/MAX customers receive the same expanded access;
  historical invoices/credits/audio balances remain intact. Expiry returns to
  the unchanged free entitlement and does not consume it with paid usage.
- Audio grant provenance is saved at admission in additive schema 0115.
  An already-dispatched finite job can finish after expiry without debiting an
  old audio balance; new clauses/leases recheck current access.
- Native paid Translator/Call operations retain supplier-cost evidence separately
  from the Free campaign allowance. No quota is silently added to the paid term.
- No recurring charge, new gateway, payment auto-approval, price migration or
  global QA exemption is introduced. The live bank destination needs to be
  reconciled: old preview showed Mega, existing checkout uses BCA. Deployment
  must wait for the owner's decision; neither bank configuration changed here.

## Validation

Local: isolated checkout/expiry/security/Free-restoration suite (10), existing
manual payment suite (17), native Translator/Call/readiness/relay suites (162),
segment/clauses (32), VO alternate/edit/upload (20) pass. Legacy assertions about
inactive previews/commercial paid capacity were updated to the authorized new
behavior. Browser execution is blocked locally by Chromium socket sandbox; a
responsive end-to-end customer/admin browser gate and PostgreSQL18 replay/
concurrency suites are in Access Pass 30 Day QA. Their results must be read for
the final head before release. No production synthetic orders or paid inference.

## Release checklist

Verify selected bank, exact commit/checks, additive schema application, Render
LIVE at merged SHA, authenticated read-only customer/admin UI, and clean startup
logs. Real provider inference and a real transfer are not simulated or claimed.
