# Unified manual payment administration

The owner requested a simpler admin console covering current Translator,
Voice Over, AI and Finance offerings, with one approval activating the purchased
access or balance. Deployment is authorized. No real payment is approved as
part of implementation or release QA.

## Scope

- Four visible primary destinations: overview, payments, customers, usage.
  Mobile no longer hides Payments in a horizontal navigation strip.
- A single paginated queue joins existing AI subscriptions, AI capacity,
  Translator/Voice Over audio orders and Finance subscription bills. Pending
  proof uploads and completed decisions are available in history.
- Approve and Reject submit once to admin-only, CSRF-protected routes. The
  existing product settlement service owns transactions, locks, prices and
  idempotency. Finance business scope comes from the stored bill, not the form.
- Proof viewing is admin-only and no-store. Successful decisions return to the
  same queue with feedback. Duplicate or concurrent approval cannot grant twice.
- Translator usage and stored audio balances now appear in customer views.

This is not a new universal credit wallet or gateway integration. Existing
prices, units, expiry and entitlement behavior are unchanged. The new Credit &
Usage preview stays inert. No Finance ledger, customer Finance UI, migration,
environment setting, provider key or WhatsApp configuration changes.

## Validation

- New isolated SQLite integration matrix: 16 tests pass, covering all four
  products, exact proof bytes, RBAC/CSRF, retry/conflict/concurrency, rollback,
  server-resolved Finance scope, queue/history/filter/pagination and bound input.
- Existing single-plan/admin console: 7 pass. Manual AI billing: 2 pass.
  Protected Finance baseline runner passes.
- Existing topup and old platform-control tests have 1 and 3 failures,
  respectively, reproduced unchanged on baseline e7329a8d (old login fixture
  redirects and retired Platform Admin branding assertion).
- New CI gates run the same matrix on PostgreSQL 18 and a responsive Chromium
  journey (320/393/768/1440 widths, proof, approve, refresh, history, Back, reject).
  Native PostgreSQL and browser results must be green before deployment.
- Candidate fd239f79: all three dedicated CI jobs succeeded in run 42676599010,
  including 16 native PostgreSQL tests and all 20 responsive browser page checks
  plus proof/approve/refresh/history/Back/reject.
- Local browser execution could not start under this workspace's socket
  restrictions, so the browser gate is performed in CI.

## Release

Only the existing Client Hub service requires deployment. Static Creative and
the suspended root bot are unchanged. Verify exact merged SHA, deployment LIVE,
unauthorized admin denial, authenticated read-only console and error logs.
Do not submit any real approval or upload synthetic proofs to production.
