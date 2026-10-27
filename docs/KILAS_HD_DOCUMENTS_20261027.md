# Native image quality and illustrated documents — 2026-10-27

Source baseline: remote main d4f995ab4cf5de4f03c8dc4abfa975cacd49a89e (PR167). Current open PRs inspected; no overlapping image/document implementation. Existing model selection, tenant/auth/CSRF, accounting, input resource limits and responsive composer preserved. No Finance, Assist, WhatsApp/payment configuration, credentials, service plans or schema changes.

## Confirmed diagnosis

`selected_image.generate` forced OpenAI `quality=low`, Gemini `imageSize=1K`, rejected high/2K/4K requests and rejected generated output above four million pixels. Legacy configured image requests also forced low and truncated prompts. Artifact downloads already stream stored binary bytes; no download recompression was found. Ordinary image uploads up to5MiB/20MP remain byte-preserved; larger uploads use the existing bounded normalization, which is unchanged. Native generated originals are separately admitted up to32MiB/20MP, without resizing/reencoding. Existing archive, document, upload and execution bounds remain.

PDF already used real ReportLab output, but body images and brochure intent were missing. It could attach a small logo only. This change adds owned body images, explicit page breaks, image-preserving revisions and brochure routing before image editing. It does not claim autonomous remote fetching or unlimited graphic design capabilities.

## Native settings

- GPT Image2/2.5: default high,2048×2048; prompt ratios and valid custom dimensions.4K landscape3840×2160 (portrait2160×3840); the provider caps each edge at3840 and total pixels at8294400, so an OpenAI4096×4096 request fails explicitly. Other ratios fit within these native limits. No thumbnail is enlarged.
- GPT Image2.5 Sunburst/Flare: low/medium/high/xhigh/max/auto; GPT Image2: low/medium/high/auto. Mini retains its supported1024 square/1536 rectangular sizes with high quality by default.
- Gemini3 Pro Image: native2K default,1K/4K supported through `imageConfig`. Flash Lite remains1K only;2K/4K requests fail before generation. No model substitution.
- Requested and actual dimensions, quality and original-byte metadata persist on modern artifacts; the existing image card displays actual settings and identifies the scaled display as a preview. Downloads return the original bytes.
- Per-request conservative capacity forecasts scale with native quality/resolution; existing quota, shared premium allowance, reserve/settle and unknown-cost retention stay authoritative. Forecasts are admission estimates, never a provider-enforced spending ceiling or exact price quotation. Historical catalog low/1K estimates are labeled as such and are not displayed as high-quality quotes. Native usage rates remain unchanged.

## PDF/brochure behavior

The selected author writes the document with selectable text. Original uploads on the originating turn and explicitly requested previous generated images are owner/conversation-scoped. The author can position them through local `![caption](image:1)` identifiers. No URL, filesystem or arbitrary artifact resolver is exposed. Brochures use a supplied hero image even when the author omits an image marker. Images keep aspect ratio and native embedded pixels; margins, repeated table headers, heading keep-with-next, captions, page numbering and explicit page breaks remain bounded within A4. PDF validation rejects active content and malformed files before publication. No extra paid image call is added to a PDF request; users can generate a visual first, then request its brochure/PDF.

## Validation and limits

New offline tests exercise provider-specific high/4K payloads, original edit inputs, original outputs, low-resolution response rejection, native capability limits, admission estimate scaling, actual two-page PDF generation, embedded2048×2048 image, selectable prices/text, explicit page break, local-only image rejection, queued image-to-brochure routing, MIME/disposition, SHA256 download equality and cross-account denial. Provider transport is mocked; the PDF/image fixtures are synthetic, with no private data. CI uploads the real synthetic brochure PDF for inspection.

Live provider acceptance is unverified: this cloud environment has no OpenAI/Gemini key. No key is created or extracted, and no paid provider inference is claimed. Production browser/Render status and exact remote release evidence must be recorded separately after the applicable CI/review gates pass. Render workspace confirmation was requested because the connector had no selected workspace.

Official contracts checked2026-10-27:
- https://developers.openai.com/api/docs/guides/image-generation
- https://ai.google.dev/gemini-api/docs/image-generation
- https://ai.google.dev/api/generate-content#ImageConfig

Initial focused local runs passed native/PDF17 tests (including inherited selected-artifact regressions), selected artifacts10, answer model audit9, work documents, existing PDF/tools, image follow-up, thread documents, PDF boundaries and protected Finance baseline. Four additional suites failed identically on an extracted unchanged `main`: attachments, usage, unified history and Assist connection HTTP. Their fixtures now use the existing `auth_test_helpers.authenticate` to obtain real revocable test sessions, and history supplies a real submitted message before expecting it in meaningful history. No middleware, security assertion or production auth was changed. All four suites then passed. Repeated document revisions now persist their owned image-source context and retain the native embedded image across two revisions.

Draft PR168 first head4f6a39009b5b828db98a903971146e38173e6222. Initial CI proves native/PDF contracts/rendering pass; the new workflow then stopped at the historical usage fixture (fixed in the next commit). Broad legacy Assist/WhatsApp/release/UI jobs also report historical login/onboarding fixture failures; these remain distinct from the image/document changes and require release disposition. No merge or deploy is claimed while gates remain unresolved.

Native Gemini dimension tables were checked against the official Generate Content image guide (updated2026-10-26), rather than inferred from the 1K legacy Flash2.5 table. For the app's supported Pro contract,16:9 is2752×1536 at2K and5504×3072 at4K;3:2 is2528×1696 at2K and5056×3392 at4K. Square4K is4096×4096. Native-size requests and bounds do not use image upscaling. Source: https://ai.google.dev/gemini-api/docs/generate-content/image-generation#aspect_ratios_and_image_size . Requests beyond supported1K/2K/4K fail explicitly rather than silently receiving a lower tier. A high-entropy2048×2048 PNG above8MiB additionally proves original-image admission under the32MiB limit while the8MiB non-image bound remains.

Local Chromium card/preview QA passed at320/390/820/1440px with no horizontal overflow and actual nativeWidth2048. PDF page1 was visually inspected after real PDF rasterization. The public production request from this cloud runtime currently fails at proxy CONNECT403 (HTTP000); this does not establish an application failure or successful live QA.
