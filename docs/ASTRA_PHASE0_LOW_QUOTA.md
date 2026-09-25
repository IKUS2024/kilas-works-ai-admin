# ASTRA PHASE 0 — LOW-QUOTA AUDIT PROMPT

CONTINUE CURRENT REPOSITORY — AUDIT ONLY, NO IMPLEMENTATION.

Repo: IKUS2024/kilas-works-ai-admin
Branch to inspect/work from: feature/kilas-core-v2

FIRST:
Read docs/KILAS_V2_MASTER.md completely.
Treat it as the product and architecture source of truth.

IMPORTANT:
This run is intentionally LOW-SCOPE because agent usage is limited.
DO NOT implement Kilas V2.
DO NOT redesign anything.
DO NOT deploy.
DO NOT touch production data.
DO NOT modify Finance behavior.

FINANCE IS A PROTECTED EXISTING MODULE.
Do not reset, migrate, rename, delete, redesign, or change accounting behavior.

TASK:
Perform Phase 0 architecture audit only.

Inspect the current codebase enough to map:

1. Current inbound message paths
   - WhatsApp webhook/routes
   - Inbox services
   - platform inbox abstractions
   - any web/customer chat path that already exists

2. Customer/contact persistence
   - where customer identity is stored
   - how tenant/business isolation works
   - duplicate/customer matching behavior if any

3. Current Kilas Order architecture
   - order_service
   - order_intake_ai
   - order catalog/search
   - quotation/payment/project bridges
   - what can be reused for generic Jobs

4. AI architecture
   - ai_brain_shared
   - context_engine
   - sales engine/brain
   - intent routing
   - how actions/writes are currently executed

5. Finance boundary
   - identify existing Finance routes/services/repositories
   - identify the narrowest safe integration points
   - DO NOT recommend rewriting Finance

6. Current onboarding and product entitlements
   - how AI Admin vs Finance access is determined
   - where menu/product visibility is controlled

7. Database/schema/migrations
   - only identify what already exists
   - list additive schema needs, if any
   - no migration implementation

8. Testing/deployment
   - existing test suites relevant to Inbox, AI, tenant safety, Order, payments, Finance
   - safest staging/feature-flag approach

OUTPUT ONLY:
Create/update docs/KILAS_V2_AUDIT.md with:

A. Current architecture map
B. Reusable components
C. Dangerous coupling / technical debt
D. Finance protected boundary
E. Proposed Kilas Core module boundaries
F. Minimal additive schema proposal
G. Exact files likely to change in Phase 1
H. Exact files that should NOT be touched
I. Regression test plan
J. Recommended Phase 1 implementation sequence

Do not write production code.
Do not deploy.
Do not create migrations.
Do not change UI.
Do not commit unrelated cleanup.

Before finishing, verify git diff contains only documentation changes.
