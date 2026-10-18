# Third approved sandbox acceptance — 2026-10-18

## Actual remote outcome: FAILED, cleaned, execution OFF

Owner explicitly approved one30-second/no-retry synthetic VM at03:14:50UTC. Reviewed wiring commit `9e17a19de30b2d09fdc85e3cc805fac57e374ca3` deployed as `dep-dba3lk6q1p3s73a6hv70`, LIVE03:21:00.055110UTC. Only the named nonsecret proof approval and general-OFF setting were merged; no key was read/changed. The merge started the deploy, so no duplicate deploy was triggered.

Exactly one new durable operation `execution:boundary-acceptance-proof-v1` was reserved, run3/job25, created03:21:03.858570UTC. It returned exit1, timed_out=false, stateFAILED, cleanup_confirmed=1. The proof job recorded terminal failure03:21:06.392440UTC (2.534seconds from ledger reservation; not an invoice/runtime measurement). No fourth VM/retry/model/customer-file operation occurred.

The proof approval was immediately cleared and general approval kept empty. OFF deployment `dep-dba3mceq1p3s73a6lgog` went LIVE03:22:28.450601UTC, with proof_requested=False, general_requested=False, proof_passed=False and host_execution=False. The consumed third key remains fixed; neither restarts nor this local fix can retry it.

## What was verified and what was not

Provider CPU/RAM/network/lifetime attestation passed before upload. The trusted runner successfully installed the corrected boundary in a real E2B VM:

- Root ext4 total23,113,342,976bytes is diagnostic only.
- Dedicated writable tmpfs total67,108,864bytes and4096 inodes.
- Private mount/IPC namespaces, root read-only, scratch writable, all capability sets zero, seccomp2 and no_new_privs.

The actual fixed child passed `identity` and `environment`: reviewed UID/GID values, zero capabilities, no_new_privs/seccomp, read-only root, denied setuid0/private-root read and stripped environment. It then failed the `descriptors` phase. The bounded partial proof is exactly:

`{"failed_stage":"descriptors","checks":["identity","environment"],"evidence":{}}`

No actual aggregate ENOSPC data/inode overflow, outside-write/procfd alias, forbidden-syscall/x32/network, descendant, memory/file/CPU probes or answer42 were reached. A mounted/capped filesystem is not a passed overflow test. Overall security/execution acceptance therefore remains FAILED, with no owner/public activation.

## Retrieved synthetic evidence

Both owned job25 artifacts were retrieved through read-only SQL after VM destruction, byte-size and SHA256 verified, ZIP content inspected:

- `execution-result.json`:1060bytes, SHA256 `8558d5d23b70bcb907f142c58858fbc17e1c84ef4245e0f4c72414d9b486a80e`; stdout empty; stderr `KILAS_ACCEPTANCE_FAILURE:descriptors`.
- `execution-output.zip`:194bytes, SHA256 `3f8a88e880f75397345e55dce0bcf9f5cbcefd8a7a67e4ef0ef6a73f1724b001`; contains only the86-byte partial `proof.json`. No answer.txt or successful result was produced.

Local copies: `/tmp/kilas-sandbox-third-proof/`. No customer audio/transcripts/files or credential values were inspected.

## Evidence-backed local correction; no weakened assertion

The trusted runner used `subprocess.DEVNULL` for stdin. CPython's actual `_get_devnull` opens `/dev/null` with O_RDWR, while the reviewed fixture correctly requires fd0 O_RDONLY. A fixed, unprivileged local child reproduced O_RDWR with DEVNULL and O_RDONLY after supplying an explicitly opened `os.O_RDONLY|os.O_CLOEXEC` descriptor; stdout/stderr remained FIFO pipes. The parent descriptor closes both after launch and on exceptions. The remote artifact did not emit the exact descriptor value, so local reproduction establishes a concrete source-contract mismatch, not a direct reading of remote fd flags or proof that no later check will fail.

The runner now supplies that explicit read-only descriptor to Popen with the existing close_fds/pass_fds policy. The fixture assertion is unchanged. Setup pipe closure, bounded64KiB stdout/stderr, read-only mounts, procfd restrictions, caps/seccomp, quotas and cleanup remain. No local generated-code execution facility or production-host fallback was added. The accepted fingerprint changes, but the consumed proof key does not; general stays OFF.

**66 targeted local tests PASS**: existing execution/runtime/boundary/fixture contracts plus actual fixed local-child access-mode/pipe checks and descriptor cleanup on launch error. Log `/tmp/kilas-sandbox-third-stdin-fix-tests.log`. These do not substitute for a new real VM acceptance.

## Accounting and next minimum action

All three consumed rows are preserved and cleanup-confirmed: initialUNKNOWN, diagnosticFAILED, thirdFAILED. Reservations total **US$0.026640** (3×US$0.008880). Compute upper estimates total **US$0.002530**; run3's estimate is **US$0.000184**, based on accepted resource ceilings plus conservative duration rounding and kill acknowledgement. These are estimates, not an authoritative provider invoice or verified console debit. Each proof is customer_metered=false; no customer execution debit was admitted. SharedUS$5/35day/provider controls remain unchanged.

No PC security setting is needed: the real VM now demonstrated the required mount/kernel/capability setup. Remaining work is acceptance of the corrected stdin contract and all unreached probes. The next meaningful action would require **separate explicit authorization** for one fresh bounded fixed acceptance operation with this correction, preserving all three consumed keys/reservations. None is requested/dispatched automatically here. Do not activate execution from VM creation, boundary setup or local tests alone.
