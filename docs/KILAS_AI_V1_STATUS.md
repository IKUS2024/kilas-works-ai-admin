# Kilas AI V1 production checkpoint

Updated: 2026-09-29 (Asia/Bangkok). Production runtime commit: `fdb0550deb9ef3d2e74584f2ed8d4ef11ad6f05d` (documentation-only successor to tested code `4fa1b4e`).

Kilas AI V1 is live on `kilas-works-client-hub` as an account-level fourth product. The feature flag `KILAS_AI_ENABLED` is ON in Client Hub; its code default remains OFF. AI Admin was not deployed. Existing Kilas Assist, Finance, and Services implementation files were not changed by the Kilas AI commits.

## Delivered

- Account-scoped chat with Fast, Smart, and Expert modes; independent OpenAI/Anthropic adapters; streaming, history, rename, deletion, retry protection, and read-only revocable sharing.
- PDF, DOCX, TXT, CSV, JPEG, PNG, and WEBP attachments; extracted document text and image understanding; owner-only durable file storage and downloads. Free/Plus/Pro/Max allow 2/3/4/5 pending files respectively, at most 2 MB each. Image-only PDFs are rejected with a clear message.
- Web search with actual source URLs, image generation and editing, and durable generated images.
- Account-level Free/Plus/Pro/Max limits and usage ledger. Published standard token-rate estimates are configured for the selected text models; unknown costs remain null.
- Manual-transfer checkout using the existing BCA details, private proof upload, admin review, and activation only after verified payment.
- Scoped Kilas AI visual polish and responsive checks. Impeccable's scoped detector reported three heading-size false positives because it could not resolve a Jinja-generated stylesheet URL; the stylesheet itself defines distinct heading sizes. No whole-product audit or automatic design rewrite was run.

## Validation and deployment

- [Focused GitHub Actions run 36457266129](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/36457266129) passed on `4fa1b4e`, including foundation, chat, attachment/provider-context, tools, usage, billing, desktop/tablet/mobile Chromium checks, and a disposable PostgreSQL migration rehearsal. Local `git diff --check` passed. The Windows host has no usable local Python runtime, so focused Python checks ran in CI.
- Only additive Kilas AI PostgreSQL migrations `0071` and `0072` were applied to production in one transaction with an advisory lock. Release records have matching SHA-256 checksums. No historical migration chain, data reset, or Finance migration ran; `RUN_MIGRATIONS_ON_BOOT` stayed off. Read-only checks confirmed all 30 existing Finance tables remained present.
- Final Render deployment `dep-data83gjo6nc73esgu10` of Client Hub is **live**. Production `/healthz` returned HTTP 200.
- A labeled QA account, `kilas-ai-release-qa-20260928@kilasworks.test`, signed up with no business membership and entered Kilas AI from the four-product picker. Real Fast and Smart text streams were saved to history; Free Expert was correctly rejected by its quota. A controlled Fast-mode provider check returned a real Claude Haiku response recorded as `anthropic` in the usage ledger; OpenAI was then restored as the Fast primary and confirmed by another real response. Web search returned a real source citation. Image generation, image understanding, and image editing worked, with generated files stored durably.
- A production PDF initially produced an incorrect refusal even though its extracted text was stored. The focused `4fa1b4e` fix made the extracted-document context explicit and raised the context cap to five attachments. After deployment, the assistant accurately quoted the PDF's `Dummy PDF file` text. TXT and CSV live requests also answered from their uploaded content.
- The QA account created one pending Plus invoice. The invoice showed the correct plan, transfer details, and proof form, and appeared in the account's invoice list. No proof was submitted, no payment was approved, and the account remains Free. Production chat rename worked; a shared read-only link loaded anonymously and returned 404 after revocation.
- A production headless Chrome session measured the populated chat, usage page, invoice page, and product picker at 1440, 768, 390, and 320 px. In every case, document/body scroll width did not exceed the viewport. The product picker still opens Assist (`/products/assist`), Finance (`/products/finance`), and Services (`/products/services`) for the QA account, each returning HTTP 200.

## Remaining verification limits

- Paid Expert/Plus/Pro/Max quotas were not exercised in production because the QA account is Free; quota and billing paths passed focused tests. No fake transfer was marked paid to force an upgrade.
- Production proof submission and admin verification were not exercised with a real bank transfer or admin session. The QA invoice remains pending; focused billing tests cover those transitions.
- The QA account has no Assist/Finance business workspace, so their authenticated business pages were not traversed. Their existing implementation files did not change, and their product entry pages loaded successfully.

## Configuration

`KILAS_AI_ENABLED` defaults OFF in code. Client Hub holds the configured provider/model IDs, existing `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, and optional token-price estimates. No provider key value was inspected or exposed. The separate Kilas AI schema is declared in `0071_kilas_ai_v1_*` and `0072_kilas_ai_usage_status_*`; no existing product schema was altered.
