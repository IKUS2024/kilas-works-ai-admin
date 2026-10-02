# Kilas Work universal output — 2026-10-02

Branch: `feature/kilas-work-universal-output-20261002`.
Base: latest remote main `81a5624` (merged PR #111, including its sustainability ceiling), retaining PR #110 and the existing shared shell/runner. **Review only: DO NOT MERGE OR DEPLOY.** No production calls, environment/resource changes, data writes or migrations were performed.

## Delivered experience

Customer-facing **AI Agent → Work**, **Chat | Work**, **Pekerjaan aktif**, **Beri tugas**, and “Berikan pekerjaan untuk Kilas…” are consistent across the existing Kilas AI screens, subscription footnote, task links and connector result copy. Internal routes, tables and names remain compatible. The existing dark shell, orange accent, Markdown safety, Chat history and background controls remain.

Professional document requests default to a real PDF; normal questions remain conversation. Intent recognizes Indonesian/English creation requests and document types, explicit formats, contextual revision phrases, structured data and image work. It is deterministic, conservative and extensible, not an unrestricted semantic classifier. Examples: proposal/SOP/report/letter/brief/itinerary/CV/checklist/company profile; budget tables prefer CSV. Explicit XLSX/DOCX/PPTX are unavailable rather than falsely reported complete. Existing coding/watch/scheduled work and Gmail approval retain their engines.

Simple document creation uses a bounded server-owned DOCUMENT/create plan without an unnecessary model planning call. Research documents use WEB/search followed by DOCUMENT/create. The registered document worker writes the finished synthesis through the existing Luna text adapter (medium reasoning, max 3,000 output tokens, bounded input). Existing simple/complex Agent policy and all PR #111 fair-use/QA/security remain unchanged. No routine Sol prose-polishing call, model fallback, fake sleep or another runner is introduced.

Writing → deterministic quality gate → existing `pdf.render(..., professional=True)` → PDF signature/parser/text validation → fenced transactional persistence. Only then can the step/job complete. Invalid/unfinished results retain bounded failure/retry behavior. Research output is supplied as untrusted evidence; raw WEB prose is not directly rendered into the PDF. Source findings remain inspectable under the existing task details; file cards precede optional research details.

The reusable **Kilas Document Standard** specifies language, appropriate document-specific sections, verified supplied facts, no invented commercial/client facts, no placeholders/fake logos/emojis/system jargon or repetitive prose. Forty offline ID/EN evaluation fixtures carry request/facts/prohibitions/desirable/undesirable characteristics; they never enter runtime prompts. Deterministic checks catch structure, missing supplied prices/timelines, unsupported Rp values, repeated paragraphs, placeholders and malformed tables. This is not a semantic proof of every model sentence; factual accuracy and natural live prose still require controlled acceptance review.

PDF output uses the existing ReportLab engine, A4, bundled/runtime fonts, margins, heading hierarchy, readable paragraphs/lists, repeating table headers, page numbers, metadata and compact sources. Work mode preserves all supported table rows rather than silently truncating after 31. No blank default cover, remote font/logo fetch or new document renderer dependency. The proposal was rasterized visually using a QA-only temporary PDFium package; no production dependency was added.

## Secure durable storage and migration decision

Existing `kilas_ai_attachments` requires a Chat thread FK and can cascade-delete on Chat-history removal. Reusing it for independent background Work would require hidden Chat threads and couple file lifetime to the wrong product. Therefore **additive migration 0080** adds only `kilas_agent_artifact_files`: artifact_id PK/FK to the existing artifact record, native BLOB/BYTEA, bounded byte_size. Existing artifact TEXT contains bounded source/title/format metadata; it never contains base64 PDF/image bytes. No existing field, data or historical artifact is rewritten.

Binary insertion shares the existing per-job lease/revision transaction with step completion. A stale writer cannot save a file or complete the task. The existing job-owned artifact route checks authenticated owner and job/artifact association, serves the correct MIME/disposition, `nosniff`, private/no-store and a sandbox CSP. Open and Download are distinct. Legacy text artifacts still work. No filesystem path or public storage URL is introduced.

Production must apply **0080 before exposing this code**, using the existing controlled migration process; deploying code against an unmigrated production database is unsafe. No migration has been applied to production. Existing Client Hub and Cron runner would need the same release in a future separately authorized deployment. No AI Admin or new resource is needed.

## Outputs and source material

Supported new Work outputs: PDF, CSV, JSON, Markdown/TXT and configured existing image generation (PNG/JPEG/WebP). Text/source, actual PDF and images remain private and persistent. Image generation reuses the current provider/validation/quota path with a bounded Work timeout and validates returned bytes; absent configuration stays blocked honestly. No image success is claimed from a prompt alone. CSV enforces consistent rows and blocks spreadsheet formula injection. Internal file creation needs no external-action approval.

DOCX/XLSX/PPTX output is deliberately not shipped or advertised. Work returns an explicit capability limitation and suggests requesting PDF/CSV; it does not silently substitute. Office libraries would expand the quality/security surface and were secondary in the brief. Existing Chat image editing remains available; Work logo placement/image editing, OCR, arbitrary downloads, browser/computer-use and publishing are not added. Gmail and other external actions still require existing exact approval and supported capability.

Readable source PDF/DOCX/TXT/CSV can be uploaded in the Work composer using the existing validator and plan limits. Only bounded extracted text/filename are retained as source data in the existing checkpoint; originals are not persisted by this new source flow. Image logos and image-only scanned PDFs are rejected rather than pretending their content was read. Source/context truncation is bounded (4,000 extracted characters per source, bounded writer evidence); no claim of complete long-document comprehension is made.

Revisions resolve the latest PDF source in the **same owner and Work conversation**, create a new job/PDF/version, and keep old artifacts/history intact. The source ID is server-derived, not a client-selectable metadata field. New conversations do not reuse another conversation's artifact or stop existing tasks. Active-task feedback/control semantics remain.

## Exact proposal acceptance example

Request: “Buatkan proposal kerja sama untuk jasa AI customer service untuk restoran. Harga Rp5.000.000 dan implementasi 14 hari.”

Verified with deterministic provider fixture through the actual runner, renderer, database and authenticated route:

- Title **Proposal Kerja Sama**, status **Selesai**.
- `proposal-kerja-sama.pdf`, actual %PDF bytes, one A4 page, approximately 41.3 KB.
- Sections: Gambaran Layanan; Lingkup dan Hasil; Timeline Implementasi; Ketentuan Komersial; Langkah Berikutnya.
- Exactly **Rp5.000.000** and **14 hari** retained; no invented company/customer identity.
- Buka and Download in conversation/task; old version remains after revision.

This demonstrates the real end-to-end plumbing with mocked provider output. It is not a claim that a production model call or production user session was tested.

## Verification

**275 tests across 17 focused suites passed**: Work 21; cost/quality 35; Chat 8; usage 5; tools/Search/images 12; natural style 7; attachments 6; Chat PDF 4; Agent 9; Automation 17; connectors/Gmail approval 32; subscription console 4; top-ups 5; billing 2; Agent chat 43; autonomous engine 47; PR #110 results 18. Covers real PDF signature/extraction/metadata, supplied facts, tables/pagination, owner access/download/cache, background persistence, actual research-synthesis boundary, revisions/new source IDs, upload safety, registry validation, stale lease denial, CSV injection, image bytes, Luna budgets, and offline corpus.

**Eight browser scripts passed**: new Work plus PR #110 results, Agent chat, Agent, autonomous controls, shared shell, Chat/subscription/attachments and Automation. Work covers 320/360/390/820/1440 px; actual PDF open/download, 44 px targets, revisions, New Chat background continuity, result-first layout and no horizontal overflow. Screenshots/PDF were visually inspected in one batched pass plus bounded confirmation. Older expected labels were updated solely to the intentional Work rename.

Impeccable context/targeted detector ran for touched Work presentation only. Two detector suggestions about flat typography could not resolve Jinja-linked styles; rendered pages show the existing heading hierarchy. No full audit, global design fix or protected-product edit was made. Existing visual identity remains authoritative.

Native PostgreSQL migration-idempotency/BYTEA round-trip and existing Linux sandbox checks are wired to CI; not claimed as local Windows passes. CI also runs the focused Work/browser tests. The full repository suite was not run. Known older Assist/Finance/Phase 9/10 baseline failures remain out of scope; investigate new relevant failures only.

Diff reviewed: Finance/Assist/WhatsApp, payments, OAuth scopes, approval semantics, tenant isolation, PR #111 model/fair-use/QA expiry and existing production data are unchanged. `db.py` only appends migration 0080. No dependency or infrastructure change. Local tests passed; current-head CI and owner review are still release gates. **Not yet cleared for production deployment.**
