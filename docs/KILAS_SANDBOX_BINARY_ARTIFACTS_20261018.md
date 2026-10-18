# Sandbox binary artifact integration — 2026-10-18

Execution and authored-project routes now automatically add a fixed unprivileged Python exporter inside the existing isolated VM. Programs write normal files under `output/`; bounded JSON/base64 frames pass through the unchanged, previously accepted text collector. The web host validates and stores bytes; it never executes generated code or the guest exporter.

Supported validated outputs: PDF, DOCX, XLSX, PPTX, PNG/JPEG/WebP/GIF/BMP still images, safe ZIP projects, and existing text/source formats. Extensions, MIME, magic/container structure and content must agree. Active PDF content, external Office relationships, macros/OLE/ActiveX, unsafe formulas, executable files, traversal, duplicate paths, encrypted/bomb archives, nested ZIPs and malformed transport frames are rejected. SVG is text source, not an inline raster image. Publication is transactional and retains existing owner/job authorization, retention and attachment-download protections.

The unchanged collector imposes **65,536 bytes per exported file, 180,000 decoded bytes per job and at most four 45,000-byte chunks**. Original encoded/file/report limits still apply. Larger documents fail honestly; no limit was raised. ZIP bundles contain actual validated decoded files. Failed programs retain their actual exit metadata rather than being labeled successful.

Third-party generation libraries in the actual E2B template remain **unverified**. The unprivileged exporter reports import availability during an ordinary approved customer execution; this report is not trusted security attestation or proof of successful generation. Local format fixtures demonstrate validators and delivery, not remote package availability. No dependency installation, host execution fallback, new VM or paid model/provider request occurred for this release.

## Verification

- 118 focused tests passed: binary formats/transport, existing execution/runtime/entitlement/disk-boundary/acceptance fixtures, documents and selected artifacts. Log: `/tmp/kilas-binary-final.log`.
- Real local fixtures included PDF, editable DOCX, XLSX formulas and chart, PPTX, five raster formats, CSV/JSON and ZIP. Tests cover malformed/active files, framing truncation/duplicates/hash mismatch, original entrypoint admission, transactional rollback, exact PDF download bytes, authorization and repeat-publication idempotency.
- Local Chromium checks passed at 320, 768 and 1440 pixels: actual PDF download bytes, image preview, HTML opaque-origin sandbox and no horizontal overflow. Evidence: `/tmp/kilas-binary-artifact-browser/verification.json`. These were local browser checks, not authenticated production or physical-device acceptance.
- Accepted execution files and proof pins are unchanged. Current bundle fingerprint: `84f9744af2820215762ee4d60bcc9db560ef5a2ed1176cc8448fe2999e3dbd7b`; original successful proof: `6aae69eb777df047f9b4dc6891e90dc5a680a2055549eb2c02cc7b0da9b28bad`; compatibility verifier pin: `1403ac10aba25b6fa29916991add1f32e143d6a8cb59b25153e0ef70e4336d83`.

All-entitled execution admission, customer quota, global US$5 rolling-35-day reservations and previous proof ledgers remain unchanged. No environment or credential update is required. Actual model → E2B binary generation → authenticated production browser download remains deferred to the parent's separately authorized single browser task; this implementation did not consume that approval.
