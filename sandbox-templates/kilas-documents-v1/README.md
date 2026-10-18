# Document-runtime preparation — not built or activated

Current production remains unchanged: small execution ON, large execution/proof OFF. This directory is an **unbuilt, locally checked preparation**, not a verified remote template. It creates no E2B resource, reads no API key and is not imported by the application.

## Verified diagnosis

Execution 5 used `template='base'` and the fixed `/usr/bin/python3` runner/child. In that confined interpreter, `find_spec` returned false for reportlab/docx/openpyxl/pptx. Exact guest Python version and other interpreter/package locations were not captured. This proves a packaging gap for the selected runtime; it does not prove a VM-wide absence or an alternate-interpreter mixup.

Official [base-image documentation](https://docs.e2b.dev/template/base-image) describes `base` as Debian/common tooling, while the [Code Interpreter documentation](https://docs.e2b.dev/code-interpreting/customize-template) identifies a separate `code-interpreter-v1` template. Its package promises cannot be assumed for this deployment. The public base Dockerfile linked from the docs returned 404 during inspection. We did not switch templates or interpreters to guess around the failure.

## Prepared recipe

- `requirements.lock`: ten exact direct/transitive packages with SHA256 hashes of official PyPI binary wheels. No source distribution, optional NumPy, per-request pip or dependency-resolution fallback. Pins are the versions used in local feasibility tests, not a claim of latest/security certification.
- `plan.json`: CPython 3.12, x86_64, glibc >=2.28; local test Python 3.12.14. **Immutable base digest is intentionally missing**. The existing E2B base ABI/venv-module support is unverified. This wheel lock must not be used blindly with another ABI/OS/architecture.
- `template.py`: definition factory only; no `Template.build`, sandbox creation or credential access. Requires an immutable image digest, checks the base interpreter/ABI, creates `/opt/kilas-document-python` from `/usr/bin/python3`, installs hash-locked binary packages at build time, checks dependency closure and root ownership/non-writable permissions, then runs fixed verification as `nobody`. Explicit file copies exclude the application, .env files and keys. Plan resources are 2 CPU/512MiB and no requested disk growth.
- `verify_runtime.py`: checks actual interpreter/prefix/version/architecture, isolated environment/user-site flags, package versions/import locations and root-owned library permissions. `smoke_documents.py` generates/reopens actual PDF/DOCX/XLSX formulas+chart/PPTX using fixed synthetic data.

No runtime library search path is widened. A future large-only integration must explicitly select the reviewed venv interpreter and immutable template/build ID, retain isolated flags/read-only mounts and account for the changed source fingerprint. Small execution must retain its current interpreter. Before a new proof, align large-profile authoring limits with 8MiB/file and 16MiB/job rather than its current small-export instructions. None of those production changes is made here.

## Local checks performed

All ten wheels downloaded from `https://pypi.org/simple`, hashed, then installed **offline** into a fresh venv with `--no-index --require-hashes --only-binary=:all:`. `pip check` passed. Both `-I -B` and `-B -E -s` preserved the dedicated venv package imports and successfully generated/reopened the four real formats, including XLSX formulas/chart. Three recipe-contract tests passed, covering pins, immutable-base rejection, no remote build/create calls and fixed root/nobody build commands.

Local venv files are owned by UID1000. The selected executor's base Python binary is UID65534-owned, so the **final strict ownership verifier intentionally rejects this local executor**; the guard was retained. Separate flag/import/generation smoke checks passed and are marked `root_ownership_acceptance=false` in their evidence. They do not prove root-owned installation, nobody execution, E2B kernel support or remote confinement. The prepared build uses default owner 0 and runs verification as nobody, failing if unavailable. No Docker/E2B image build was run; no immutable base image was available locally.

Local evidence: `/tmp/kilas-doc-preparation-install.log`, `/tmp/kilas-doc-prepared-runtime.json`, `/tmp/kilas-doc-prepared-runtime-es.json`, `/tmp/kilas-doc-template-tests.log`. Wheels/fresh venv are temporary local QA assets, not committed binaries.

## Exact remaining external actions and approval boundary

1. Obtain/verify an immutable base image digest providing CPython 3.12 at `/usr/bin/python3`, venv support and compatible glibc/x86_64. Alternatively revise/review the lock for the actual verified ABI before building. `plan.json` remains blocked until this input is real.
2. Establish a bounded **remote template-build** cost/duration/abort policy before authorizing one build. [E2B build documentation](https://docs.e2b.dev/template/build) documents resource settings, but does not give a per-build charge or hard server-side timeout/cancellation guarantee. [How builds work](https://docs.e2b.dev/template/how-it-works) says a sandbox is started/snapshotted. The installed SDK's HTTP timeout does not establish a provider billing deadline. Therefore this preparation cannot truthfully quote an exact capped remote-build total. Existing US$5 provider blocking of new requests is not proof that an already running build is killed at the limit.
3. Only after that scope/cost approval, create one versioned template from this explicit file context, capture immutable template/build IDs and verified package/interpreter manifest. Use existing secure authentication without copying credentials into this repository or build context. No remote build is authorized by the consumed US$0.02 proof approval.
4. Review large-only runtime wiring and its new full fingerprint, then obtain a **distinct** bounded actual acceptance approval. All generation, 8MiB/16MiB transfer, storage/download, memory/deadline, confinement and cleanup requirements remain mandatory before activation. Do not reset the consumed key or inherit its failed record. The separate browser allowance is unrelated and was not consumed here.
