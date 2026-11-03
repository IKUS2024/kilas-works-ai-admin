# Products catalog review evidence — 2026-11-03

Baseline: `eb92047f0a6c4bb64ed4c8b07770a3fe4499b394` (PR195 retained).
Initial catalog head: `df5da1d0fbb42cad51e2139640bee43efa5a9302`, PR196.

The catalog contains Finance, Creative Services and Shotcut. Card content is left aligned. White button labels on `#bd4700` have 5.17:1 contrast; hover `#a43c00` has 6.51:1. The Finance POST and CSRF/ownership guards are unchanged. No production configuration, provider behavior, database schema, or installer handling changes.

## Catalog-specific checks

- Initial catalog: 14 focused server tests and 24 Chromium scenarios passed (Home/agent, en/id/es/zh, 320/390/1440 px).
- Final browser suite additionally sends restored drafts through real Flask routes with `providers.stream` mocked, then checks Products/Back/refresh leave the composer empty. No paid provider transport. Screenshots and `results.json` are emitted to `/tmp/products-catalog-qa` and uploaded by Products Catalog QA.
- Keyboard activation/focus, repeated clicks, browser Back/Forward, direct catalog access, unsafe return URL fallback, login interruption, Creative Services/back and Shotcut's exact external URL/new tab/null opener are covered.
- Existing tests whose assertions required Finance/Creative Services in the former expandable sidebar were updated to check catalog navigation. The Finance onboarding browser still submits the real original Finance action after entering the catalog.
- JavaScript syntax, JSON parsing and `git diff --check` pass. This Flask/Jinja/CSS change has no separate frontend build/typecheck task.

## Initial-head CI comparison and corrections

Failures were compared with a separate unchanged-main worktree. Tests were run as independent processes, matching repository workflow practice; collecting legacy fixtures together can cause environment/import-order differences.

| Workflow | Initial failure | Comparison / action |
|---|---|---|
| Conversation Copilot | Expected `Jasa Kreatif` and `Finance` in sidebar | Introduced stale navigation assertions. Updated to inspect catalog; 30-test standalone suite passes. |
| Six reference UI | Drawer browser queried removed `.chat-product-entry button` | Introduced stale selector. Updated to Products anchor; unchanged-main and corrected drawer browser both pass. |
| Global UI | Four Home failures; Finance dashboard/category and style-loading failures | Four Home failures reproduce on main. Finance dashboard reproduces the same four failures/two errors. Standalone style-loading passes on both trees; combined workflow fixture behavior is pre-existing. |
| V2 Phase 9 | Finance navigation label in `test_kilas_workspace.py` | Same three failures on both trees. |
| V2 Phase 8 | WhatsApp auth/scope | Same three failures/two errors on both trees. |
| V2 Phase 7 | Finance bridge/bridge routes | Same bridge/route failures on both trees; no Finance implementation edits. |
| V2 Phase 10 | `test_subscription_lifecycle.py` dashboard assertion | Same assertion fails on unchanged main and catalog. |
| Master Completion | Continuous-training language normalization | Same `None != {'forced_language': 'en', 'follow_customer': False}` failure on unchanged main. |
| AI Automation | Chat auth, automation text/browser, PostgreSQL setup | Same five Chat failures and automation failure on both trees; browser fails at same heading after redirect to login. PostgreSQL relation failure occurs in unchanged schema setup (see limitation below). |
| Autonomous Agent | Cost/quality old offer copy, code-worker `user_id`, browser heading, PostgreSQL setup | Same cost/quality failure, four code-worker errors, and browser heading failure on both trees. PostgreSQL limitation below. |
| Chat Recovery | Workspace-runtime image-edit test / model checks | Compared with unchanged main independently; production code in those areas is byte-identical. Browser and PostgreSQL jobs on initial catalog head pass. |

Local comparison logs and JSON are in `/tmp/catalog-ci-comparison`. Browser comparison uses installed Chromium for both worktrees where old scripts require a bundled browser unavailable locally.

PostgreSQL limitation: the AI Automation/Autonomous schema jobs fail with missing `kilas_ai_conversations`. Their test files, `db.py`, and migrations are byte-identical to unchanged main. A separate local PostgreSQL baseline run was not available; this is source comparison, not a claim of successful PostgreSQL execution.

Initial head's HD Image/Document, managed offering, and Chat audit hardening workflows passed. Later-head CI is authoritative for the corrected navigation assertions. Do not infer that all repository workflows are green from catalog-specific success.

No merge, PR approval submission, deployment, or production mutation was performed during this review.
