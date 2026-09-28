# Kilas Assist UI refresh — 2026-09-28

Branch: `feature/impeccable-kilas-assist-ui-refresh-20260928`. Ready for review; not deployed or pushed. The user's implementation request supersedes the earlier audit-only scope. The original audit remains unchanged.

## Implementation

The existing dark/orange brand now uses one opt-in Assist presentation layer: `client-hub/static/assist_ui.css`. It covers entry/authentication, onboarding, Home, training, both Inbox renderers, Lead/Customer lists, details and Insight, Jobs, follow-up, WhatsApp setup, subscription/checkout, More, settings and supporting account screens. Typography, spacing, borders, focus treatment, controls, status text and responsive layouts follow the same rules. Native forms show submission feedback without disabling named submitters or changing requests.

Home prioritizes training and daily navigation, with plan comparison in an expandable section. Lists use readable rows instead of repeated boxes. Filters and pagination wrap on narrow screens; primary controls have 44px minimum touch targets. Inbox supports mobile conversation views and preserves reading position. Empty search results explain what to try next.

Shared base integration only opts Assist into the new assets. Finance routes, Finance workspace sessions and Finance authentication entry are excluded. On the product picker, only the Assist option receives new styles. No shared stylesheet was rewritten. No production Python, routes, calculations, schema, tenant authorization, payment verification, WhatsApp/Meta gates or CRM/Jobs architecture changed.

## Audit disposition

| Finding | Implemented treatment |
| --- | --- |
| A1 | Visible associated Inbox search, handler filter and reply labels. |
| A2 | Associated contact-profile labels, input IDs and autocomplete hints. |
| A3 | Readable status/metadata sizing; larger body text and stronger muted contrast. |
| A4 | Pagination targets at least 44 × 44px, wrapping layout. |
| A5 | Legacy Inbox replaces 1.2s polling with adaptive 3–10s idle intervals and failure backoff up to 30s; focus/visibility refresh remains. Full-page endpoint retained to preserve backend architecture. |
| A6 | Refresh defers replacement while the affected region has focus; open follow-up edits and disclosures persist. Canonical Inbox no longer forces a reader back to the bottom. |
| A7 | Selected stages, pages and conversations expose current state; business switcher uses pressed-button semantics. |
| A8 | Scoped Assist tokens and common component rules, with Finance styles untouched. |

## Verification

**Browser:** 84 successful page checks (28 routes at 360×800, 820×1180 and 1440×1000) in headless Microsoft Edge, using isolated synthetic fixtures. No document horizontal overflow, unnamed form controls or page JavaScript errors were reported. Each viewport also passed profile-label focus, follow-up draft/focus retention, reply draft/focus retention, reconnect feedback, pagination sizing, selected-stage semantics and native submission-feedback checks. No message or payment was sent. [Raw browser report](qa/kilas-assist-refresh-browser.json).

Visual inspection covered representative desktop/tablet/mobile screens and a bounded confirmation pass. Selected screenshots: [mobile Home](qa/kilas-assist-refresh/360-home.png), [desktop Home](qa/kilas-assist-refresh/1440-home.png), [tablet training](qa/kilas-assist-refresh/820-training.png), [mobile Inbox](qa/kilas-assist-refresh/360-canonical-conversation.png), [checkout](qa/kilas-assist-refresh/1440-checkout.png), [mobile Leads](qa/kilas-assist-refresh/360-leads.png).

**Regression tests:** 80 passed across six independently executed suites:

| Suite | Passed |
| --- | ---: |
| `test_assist_continuous_training.py` | 10 |
| `test_assist_crm_cleanup.py` | 12 |
| `test_kilas_workspace.py` | 10 |
| `test_checkout_payment_pending_fix.py` | 22 |
| `test_assist_connections.py` | 9 |
| `test_kilas_jobs_routes.py` | 17 |

Two continuous-training PDF/media cases could not pass on Windows because the existing PDF sandbox requires Linux `resource` limits: `test_media_upload_replace_delete_and_permissions_do_not_reconnect` and `test_paid_waiting_connection_reuses_demo_and_connection_keeps_knowledge`. They were excluded from the final 80-test run and require Linux CI. The sandbox was not weakened. Existing fixtures also required closing cached SQLite connections before unlinking files on Windows; that adaptation was confined to a temporary test runner. Jobs ran with native pytest.

**Finance boundary:** six Finance-session routes rendered semantically identical DOM against the pre-refresh templates: overview, transactions, reports, More, account and login. None loaded Assist assets or acquired the Assist root marker. Comparison ignored only insignificant text/class whitespace. [Evidence](qa/kilas-assist-finance-boundary.json). This is a scoped presentation check, not a rerun of the entire Finance suite.

**Impeccable:** context initialization and one scoped detector pass completed. Its sole remaining suggestion was a 10px declaration in canonical Inbox; all local 10–12px declarations there were then raised to 13px and included in the browser confirmation. [Unmodified finding content](qa/kilas-assist-refresh-detector.json), with repo-relative paths. The detector could not resolve a Jinja-generated stylesheet link; rendered browser checks supplied the missing layout evidence. No claim of automated accessibility certification or a second clean detector run is made.

All implementation diffs were reviewed for Finance leakage and behavior changes; `git diff --check` passed. No deployment, migration, production data access, connection configuration or payment configuration operation occurred.

## Reproduce and review

Use the project's Python dependencies plus Playwright. The local browser harness explicitly rejects production environment markers and uses test fixtures:

```powershell
$env:KILAS_ASSIST_UI_QA = '1'
$env:QA_BROWSER = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
python -B client-hub/tests/assist_ui_refresh_qa.py
```

Screenshots and JSON default to the temporary `kilas-assist-ui-review` directory. On Linux, run each listed regression file independently with `python -m pytest client-hub/tests/<file> -q`, including the two PDF cases. Desktop/tablet/mobile here means viewport emulation, not physical-device or Safari testing. Password-reset token states and every possible billing/connection state were not individually exercised by the 28-route browser matrix; their scoped presentation rules retain existing templates and business conditions.

Next: review this branch and run the two Linux-only cases before any separately authorized production release.
