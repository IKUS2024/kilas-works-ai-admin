# Single approved large-output proof: FAILED, safely OFF

Owner approval: 2026-10-18 05:22:53 UTC, one synthetic VM, at most 60 seconds/US$0.02 existing free credit, no retry/install/model call/purchase, conditional activation only after every mandatory check passed.

Runtime code: `319334c4aaf697f7908be22dad5a84645ddd3f24`. Proof deploy `dep-dba5krdg1s2s73asdc90` became LIVE at 05:35:40.194572 UTC. The stable `large-document-acceptance-v1` operation was consumed once as execution **5**, synthetic job **27**. Exact dependency fingerprint: `1ca87b7bb85eb554c6015ae86864953528788761dc22388364ccd8364e43e879`.

## Actual result

- **FAILED at `packages`**. `find_spec` reported `reportlab=false`, `docx=false`, `openpyxl=false`, `pptx=false` in the confined `/usr/bin/python3` runtime. These libraries are unavailable on that import path; other interpreters/VM-wide installations were not inspected. Exact guest Python version was not recorded.
- Guest exit **1**, `timed_out=false`, elapsed **3,422ms**. Termination was acknowledged, `cleanup_confirmed=1`; no replacement VM.
- All 13 actual confinement/resource checks completed: identity, environment, descriptors, outside writes, syscalls, network denial, descendant inheritance, memory limit, new 8MiB file overflow, CPU limit, data ENOSPC, inode ENOSPC and answer 42. Data: 67,088,384 bytes written/available, 67,108,864 requested, errno 28. Inodes: 4,090 created/available, errno 28.
- Trusted post-stop collector self-tests rejected over-file, over-job and five-file inputs; private staging/post-stop evidence returned.
- **Document generation, 16MiB transfer, four-document validation/download and large-workload RAM/throughput acceptance were NOT reached.** Zero document bytes retrieved. Host cgroup peak 196,644,864 bytes does not establish large-workload capacity.
- Only **2,282-byte diagnostic artifact 24** retained, MD5 `4d2f7bff7f375791b6fd30194b8b9575`. It contains fixed synthetic evidence/library flags, not customer content or credentials.

## Safe final runtime

Both large proof/general approval flags were cleared by a two-key merge preserving other configuration. OFF deploy **`dep-dba5lim1egvs739f4q70`**, same runtime SHA, became LIVE at **2026-10-18 05:37:07.394661 UTC**. Startup confirms large proof/request/acceptance false; original small execution remains ON for entitled nonowner accounts, with matched proof, customer reservations and US$5 rolling-35-day guard.

Read-only SQL: five attempts/five cleanup confirmations; maximum reservations **US$0.044400**. New conservative compute estimate **US$0.000230**; combined estimate **US$0.002990**. These are not verified invoice amounts. New proof customer-charge rows: **0**. Storage reservation released by transactional diagnostic publication. Four original outcomes/keys preserved. No retry/activation is authorized by the consumed proof.

Local preparation: 101 targeted regressions passed, then final 15-case proof suite passed. The local 16MiB fixture succeeded under 256MiB AS/10s CPU, but did not establish remote library availability. No model/speech/search call occurred. Separate US$0.15 parent browser task remains unconsumed; no external authenticated-browser acceptance claimed.

## Minimum next dependency

Prepare/review a **versioned E2B generation template exposing pinned reportlab/python-docx/openpyxl/python-pptx to the confined interpreter**, preserving the boundary and zero network/package installation during customer jobs. Template preparation/provisioning/cost needs its own concrete scope approval; none performed. After offline validation, request a distinct bounded actual acceptance. Do not repeat this consumed proof or enable large exports on the current runtime.
