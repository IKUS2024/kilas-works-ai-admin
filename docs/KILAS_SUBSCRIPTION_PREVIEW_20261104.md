# Subscription design preview

Replaces the unconnected Credits & Usage preview at `/kilas-ai/usage` with Free/Pro cards and a Bank Mega payment design. The profile navigation entry is now Subscription across the shared Kilas tool/drawer shell. The existing `/kilas-ai/usage?view=legacy` screen and its functional forms remain untouched and linked explicitly.

The preview implements no entitlement, quota, subscription, payment, copying or upload actions. It shows no invented current balance. Proposed feature counts are labeled Usulan; the entire page is labeled Rancangan paket and Langganan belum tersedia. Translator, Voice Over and receipt descriptions were checked against existing templates. The account is a labeled placeholder, and payment controls remain disabled. The requested removed quota-change footnote is absent.

Visual direction follows the parent's pixel-inspected textual specification for Library item `libfile_c66b4dfdafc88191af44648c16f06b96`. This executor did not personally view that reference: its supported Library transfer failed, and the parent explicitly authorized proceeding from the inspected textual specification. Rendered implementation screenshots were personally inspected at mobile and desktop sizes. The existing Kilas shell branding was preserved; no global design tokens or Finance styles changed.

## Validation

- Browser: 10 cases (320, 360, 393, 834, 1440px; en/id shell settings). No overflow, console errors, external requests or write requests. Checks include profile entry, repeated payment opening, close, Escape, Back/Forward, reload/direct hash state, and the legacy link. Screenshot/report output: `/tmp/kilas-subscription-review`.
- `test_kilas_ai_single_plan_console`: 6 passed, including unchanged existing account records and legacy checkout/top-up behavior.
- `test_kilas_ai_usage`: 5 passed.
- `test_kilas_ai_billing`: 2 passed.
- `test_kilas_ai_revisions`: 6 passed, 1 existing failure: retained-home conversation assertion fails before the changed profile label. Reproduced on untouched finance base `eebd4add756dad8836273f0021ee2c87747d9c11`.
- `test_kilas_ai_topups`: 4 passed, 1 existing failure: foreign invoice request redirects 303 instead of expected 404. Reproduced on the same untouched base.
- JavaScript syntax and `git diff --check` passed.
- Existing Copilot browser expectations were updated for the navigation label; full Copilot suites and full Finance regression suite were not run. No Finance or backend source changes.

Browser legacy navigation uses the local data-free preview harness; actual legacy forms and record preservation are covered by the application route tests. Local testing uses synthetic account/provider fixtures. Production login-dependent visual verification remains a release check.
