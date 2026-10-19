# Document runtime: locally verified; E2B build and acceptance pending

Application release `246d82b` remains the deployed PDF/PPTX routing repair. Small execution remains ON; large execution/proof remain OFF. This directory is a preparation recipe and is not imported by the application. `template.py` constructs a definition only: no build, VM creation, credential read or automatic activation.

## Verified runtime preparation — 2026-10-19

- The official Docker Hub `python:3.12.14-slim-bookworm` index resolved to the Linux amd64 manifest `docker.io/library/python@sha256:1aaa65a85fda306ffb8b910824d4e93bdce61e212c7e87168123ea3073b41a1a`. The actual pinned image was pulled and built locally. The factory rejects another digest, including another syntactically valid immutable image.
- Its interpreter is **`/usr/local/bin/python3.12`**, not `/usr/bin/python3`. The recipe creates `/opt/kilas-document-python` from that explicit interpreter and requires exact CPython **3.12.14**, x86_64 and glibc >=2.28. Existing application runners still use their original interpreter; no runtime wiring or proof-pin replacement is made here.
- The ten direct/transitive binary wheels in `requirements.lock` retain their exact SHA256 hashes. They were downloaded with hash verification, installed offline into a fresh venv, and passed `pip check`. No per-job network installation or host fallback is added.
- A **local Docker build with `--network=none`** installed only those local wheels. The final verifier ran as UID65534 (`nobody`) and passed the existing strict root-ownership checks, including the base binary, venv/package permissions, isolated flags, exact package versions and import locations under the dedicated prefix. This supersedes the earlier executor-only ownership limitation; it does not establish E2B provisioning or kernel compatibility.
- `Dockerfile.local` reproduces that offline build from a disposable context containing exactly the four recipe files plus the downloaded `wheels/` directory. It copies recipe files with mode 0644 into an explicitly mode 0755 directory, matching the E2B factory. Never use the repository root, `.env`, application files or credentials as its context.

## Fixed synthetic generation

`verify_runtime.py --smoke --representative` checks the runtime, then applies the existing 10s CPU, 256MiB address-space and 8MiB file-size limits. `smoke_documents.py` generates four actual PDF/PPTX files: one-page small PDF, one-slide small PPTX, 12-page PDF with a synthetic image, and 15-slide PPTX with that image. The large files exceed 64 KiB; every file is <=8MiB and all four fit within 16 MiB. PPTX files reopen with python-pptx; host tests also reopen both PDFs with pypdf and verify the synthetic profit 184000 on every page.

The separate small smoke still generates DOCX and XLSX formulas/chart as well. No model source or customer content is executed. These are **package/generation checks**, not a substitute for actual remote confinement, streamed storage/download, leases, accounting and VM cleanup acceptance.

The read-only cost/access findings are recorded in `budget-evidence.json`; it is evidence only, not an executable approval or account-limit change.

Local evidence lives in `/tmp/kilas-runtime-usd1-*.log`, `/tmp/kilas-runtime-usd1-output/` and the disposable local Docker image. Temporary wheels and images are not repository deliverables.

## US$1 task budget: paid dispatch remains blocked

Owner authorized a total maximum US$1 for runtime preparation and E2B tests, conditional on proving that ceiling. No E2B build or VM was started in this preparation: new E2B spend is US$0.

Official [build limits](https://docs.e2b.dev/template/quickstart#build-limits) specify termination after one hour. Official [pricing](https://e2b.dev/pricing) gives per-second CPU/RAM charges. Arithmetic at the requested 2 vCPU/512 MiB is US$0.1089/hour; at the Hobby 8 vCPU/8 GiB ceiling it is US$0.5328/hour. **Neither is a verified total build/provisioning quote.** The documentation does not explicitly bound all build-stage charges with these sandbox rates. The installed SDK 2.56.0 build request exposes CPU/RAM/disk parameters but no per-build monetary limit or build-duration option. HTTP request/upload timeout is not a provider billing deadline.

The [billing documentation](https://docs.e2b.dev/billing) describes dashboard spending limits, but the existing account's value and its enforcement against an already-running build have not been inspected. The selected executor has no E2B credential, connected E2B tool, SSH agent or authenticated dashboard session; no connected desktop device is available. The production key's presence is not permission to copy it out. Do not create a credential, change billing/security settings or increase an account limit to bypass this blocker.

## Remaining external work

1. Through an existing authorized provider connection, establish the complete build/provisioning tariff and a real combined task ceiling <=US$1, including tests and any already-incurred cost. Keep one durable operation/cost record and no automatic retries. If the ceiling cannot be proven, keep paid dispatch blocked.
2. Only then perform one versioned E2B build from this explicit context, preserving 2 vCPU/512 MiB and no requested disk growth, and capture immutable template/build IDs plus actual interpreter/package/kernel evidence. The local Docker digest is not an E2B build ID.
3. Review dedicated document-profile wiring to the exact venv interpreter, preserving the proven small executor and all network, tenant, quota, process, scratch and cleanup boundaries. No widening to user-writable library paths or execution on the web host.
4. Use a distinct authorized acceptance operation for actual small and large PDF/PPTX, authenticated artifact storage/download, interruption/rollback, resource evidence and confirmed VM termination. A single <=60s VM has a conservative application compute envelope US$0.008880; this excludes build costs and is not an invoice. Do not reset a consumed proof key.
5. Keep large OFF until every acceptance condition passes. Any required configuration/activation change must be separately identified and authorized; a local package smoke never grants it.
