# Kilas product context

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Indonesian UMKM owners and staff managing customer conversations, business knowledge, contacts and concrete customer requests. Platform operators manage customer support in a separate administrative workspace.

## Product Purpose
Kilas Assist helps a business teach an AI assistant its own information, handle WhatsApp conversations, understand contacts and follow up concrete requests. Kilas Finance is a separate existing financial workspace; it is protected and outside this Impeccable task.

## Operating Context
Existing Flask/Jinja application in `client-hub`, server-rendered HTML, shared CSS and plain JavaScript. Production runs on Render. This is an established application, not a greenfield project.

Current workflow: essential business setup → continuous Latih Kilas → optional answer preview / independent confirmation → real WhatsApp demo or paid production connection. Training updates existing canonical knowledge; do not restore a mandatory preview/test or restart a healthy demo binding.
CRM: Inbox → Lead/Customer → contact detail → Jobs. Customer Insight is inside contact detail, not another navigation destination. Informational interest remains Lead; a concrete request can become Customer/Job without requiring payment. Follow-up drafts require human review.

## Capabilities and Constraints
- Preserve all existing functionality and production data. Current authorization is installation, initialization and audit only: no UI fixes, redesign, business logic, migration, deployment, payment or connection changes.
- Do not modify Kilas Finance, including accounting, templates, styles, data, routes and its existing Job bridge. Shared base templates/CSS also contain Finance behavior; future Assist work must be scoped explicitly and checked for Finance impact.
- Checkout requires essential identity plus valid account/business/plan. Operating hours, service model, business phone and owner WhatsApp phone do not block payment. Payment verification and production Meta/OTP/WhatsApp gates remain authoritative.
- Preserve tenant isolation, existing Inbox, human takeover and customer-message evidence boundaries. Do not fabricate customer facts, jobs, payments or transport verification.
- Current Jobs implementation exposes Perlu tindakan, Dikerjakan, Selesai and Batal. The latest CRM release records Finance-only completion. Older three-status requirements are historical; this audit does not change statuses or completion authority.
- Do not log out/disconnect WhatsApp, deregister numbers, substitute numbers or create WABAs as part of design work.

## Brand Commitments
Keep the Kilas Works / Kilas Assist names, existing identity and Indonesian product language. This task authorizes no rebrand or visual replacement. Existing code is the visual authority; missing DESIGN.md is not permission to redesign.

## Evidence on Hand
Source baseline: `c0d27c2dabb99d1c68448524f0407f77440f5eab` (main inspected for this task). Current release and product changes are recorded newest-first in `docs/KILAS_MASTER_COMPLETION_STATUS.md`. Inspect current routes/templates and the latest checkpoint before relying on older phase documents or conversation recollections.

Live read-only review saw Home, training, Lead list, Jobs and Inbox in the existing owner session. No form submission, message, payment, training, connection or Finance interaction was performed for this audit. Private customer content must not be copied into reusable design context.

## Product Principles
1. Make the next business task clear using real state and existing permissions.
2. Keep Assist and Finance distinct; preserve trusted financial behavior.
3. Teach once and refine continuously without duplicate onboarding.
4. Keep contact identity, customer evidence and concrete work connected.
5. Preserve human review and authoritative payment/connection boundaries.

## Open Decisions
No new aesthetic direction, font, palette, image-generation build preference, dark/light theme requirement or accessibility certification has been approved. Accessibility recommendations are audit findings, not a claim of compliance. Live-edit integration and automatic hooks remain disabled for this audit-only phase.

## Provenance
Initialized from the user's explicit instruction to use existing Kilas context, current repository implementation and latest release checkpoint on 2026-09-28 WIB. No new product facts were invented and no redundant interview was required for these already specified constraints.
