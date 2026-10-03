# Kilas AI Product Hardening V1

## Current checkpoint — 2026-10-03

- Starting/latest fetched remote main: `fee850688e4914c2bfe136e9662082eb451aede1`.
- Release QA branch: `feature/kilas-ai-product-hardening-v1-20261003`, created from exact latest main. Native PostgreSQL and browser CI must pass before advancing main. No production deployment yet.
- Preserve pre-existing local changes to Chat UI Cleanup, Unified V1 and Premium UI V1 status documents. They belong to the previous completed release and are excluded from this patch's staging.
- Implemented so far: modern root landing despite stale Assist selection; customer Connections navigation removal and legacy Connections view redirect; runtime capability contract for conversation providers; contextual image follow-up routing; deterministic bsk/pukul scheduling normalization and future Search precedence; structured DOCX/CSV/XLSX/PPTX extraction; bounded owner/conversation document continuity; isolated scanned-PDF rasterization using existing vision when configured; explicit labeled synthetic document examples.
- Backend connectors, OAuth records/configuration, Assist, WhatsApp, Finance, billing/pricing/quotas and database schemas remain preserved. No migration is introduced.
- PDF vision limits: 3 pages, 1.5M pixels/page, 3 MB raster bytes/document, isolated 15-second deadline; Linux worker memory/CPU ceiling. No OCR engine or Chromium infrastructure.
- Existing file limits preserved: 2 MB documents; image ingress 100 MB with existing pixel/normalization limits; per-plan attachment counts unchanged. Native PDF first 15 pages; Office text 12,000 chars; XLSX first 5 sheets/200 rows/20 columns; PPTX first 30 slides. Formulas are data with cached values identified, never executed.
- Regression corpus expanded from 210 to 250 conversations; fixtures never imported into runtime prompts. This is an evaluation corpus, not a claim that 250 live provider answers were semantically validated.
- Local focused evidence: hardening 31 tests (10 new + inherited 21), Work V2 22, document workers 23, attachment 6, chat intent 12, cost-quality 35 PASS. Readable short PDFs were initially misclassified and fixed before release; spreadsheet/CSV assertions now verify the new structured representation.
- Browser acceptance PASS at 320/360/390/430/768/820/1024/1440: auth, modern Home, canonical AI, hidden Connections, preferences, schedules, account/dialogs/subscription, Finance home/transactions/accounts/invoices/reports, contrast and no overflow. Screenshots in temporary `kilas-premium-ui-qa`.
- Additional fixes: interval-watch threshold clarification preserved; recurring news stays Search work instead of becoming a reminder; scheduled public news has a deterministic WEB step at execution; ambiguous image follow-ups now reach actual IMAGE plans with original visual context; uploaded-document analysis remains Chat rather than accidentally creating another document; multiple long files retain all source names and closing boundaries.
- PDF native extraction also runs in the bounded isolated worker. Linux worker address-space ceiling is 192 MB to leave headroom on the existing 512 MB service. No service upgrade required.
- Local regressions all pass after diagnosed failures: Agent 9 and Connector 32 retain backend OAuth/approval/token/isolation checks while expecting the intentionally hidden Connections surface. Provider tests verify the original system instruction plus runtime truth contract. UTF-8 corpus reading is explicit on Windows. Hardening suite now 36 tests (15 new + inherited 21).
- Impeccable rendered review inspected the actual white mobile drawer and desktop captures. Primary navigation/history/account grouping retained; Preferensi AI clarified to Pengaturan AI. Detector's two live-thinking pulses correspond to actual in-flight requests, and the dark-glow suggestion refers to overridden legacy CSS rather than the rendered white canvas. No global theme/Finance stylesheet changed.
- Remaining: finish native PostgreSQL and remote CI, final source review, advance main only when clean, targeted deployment and real production verification.
- Deployment scope will include Client Hub and Cron because document worker/planner changes execute in the existing background runner; no other service/resource or configuration change is authorized/needed.
- Dedicated production QA login requested. Do not fabricate authenticated acceptance if the owner does not sign in.

Status: IN PROGRESS. Production remains at the previous white UI release.
