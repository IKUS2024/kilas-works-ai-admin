# Package-entitled sandbox activation — 2026-10-18

Owner explicitly authorized execution ON for all accounts with existing package entitlements at04:03:08/04:03:32UTC (Sentinel_29336849eddc819183843ed5ddf3e06e). This supersedes owner9-only staged rollout. It does not grant free unlimited capacity, change package prices, increase the sharedUS$5 sandbox budget, create credentials/infrastructure, or authorize a fifth QA VM/model/audio call.

## Admission and accounting

The previous capability gate required a numeric owner allowlist even for an otherwise entitled account. The new explicit server policy is `KILAS_EXECUTION_AUDIENCE=entitled`; it does not interpret `*` or a guessed wildcard. Normal allowlist behavior remains for the separate `allowlist`/empty mode, with package entitlement required. Unknown modes fail closed.

Entitlement reuses a valid ACTIVE existing non-FREE package within its paid period, or the existing app's server-owned fixed-end sponsorship (`free_test.eligible`, unchanged12December/11December local-date boundary: exact end2026-12-11T16:59:00Z). Inactive/expired packages without valid sponsorship, ordinary unentitledFREE accounts, unknown users and anonymous requests are denied. No subscription, paid period, sponsorship end, balance or quota is created/reset. Existing eligible trial/sponsored accounts still reserve finite premium capacity; this path does not use the generic QA quota exemption to bypass metering.

Each actual customer execution must pass the unchanged locked customer reservation before SDKcreate: burst/hourly/concurrent guards, fullUS$0.008880 forecast from current premium capacity or existing top-up units, idempotency and owner-scoped settlement. Exhaustion denies before global/provider allocation. Unknown costs retain conservative exposure. Existing artifact/job ownership, user/job operation keys, finite globalUS$5/35day budget with in-flight maximum reservation,10daily runs/shared concurrency1, runtime/CPU/RAM/disk/inode/network restrictions and destruction remain. No production-host code fallback exists.

## Finite compatibility with the actual fourth proof

Original real accepted bundle remains **6aae69eb777df047f9b4dc6891e90dc5a680a2055549eb2c02cc7b0da9b28bad**, run4/job26. Its original PASS/fingerprint/outcome is never rewritten. Reconstructing the four originalf9eeffc7 files locally reproduced that exact hash.

Only `accepted()`/`capability()` in execution.py change; all other execution source bytes are identical to the proven source. The current full source fingerprint is **84f9744af2820215762ee4d60bcc9db560ef5a2ed1176cc8448fe2999e3dbd7b**. It is not presented as a newly VM-tested bundle.

The explicit deployment pin **KILAS_EXECUTION_COMPATIBILITY_SHA256=1403ac10aba25b6fa29916991add1f32e143d6a8cb59b25153e0ef70e4336d83** binds the exact compatibility verifier bytes, checked BEFORE import. The verifier pins the complete exact reviewed new execution.py, exact original guest/proof/fixture files, new entitlement/accounting modules, original actual proof fingerprint and non-gate execution source-byte digest. Excluding the exact two function source spans is only an additional equivalence check: full-file hashes also pin those functions, so future accepted/capability changes fail. Verifier/constant/file changes fail the external configuration pin. Missing/wrong pins fail closed. No open-ended future function exemption or fabricated new proof exists.

Acceptance still requires the durable original execution stateSUCCEEDED, cleanup-confirmed and artifact jobCOMPLETED. A changed boundary, runner, reserve, network, resource, cleanup, proof or fixture requires separate reviewed acceptance rather than automatic compatibility. This finite transition covers only the explicitly authorized admission policy change.

## Exact nonsecret activation configuration

- `KILAS_EXECUTION_AUDIENCE=entitled`
- `KILAS_EXECUTION_APPROVAL=e2b-hobby-60s-5usd-v1`
- `KILAS_EXECUTION_PROOF_APPROVAL=` (OFF)
- `KILAS_EXECUTION_COMPATIBILITY_SHA256=1403ac10aba25b6fa29916991add1f32e143d6a8cb59b25153e0ef70e4336d83`

Only these keys are merged with replace:false; no API-key value or unrelated variable is read/changed. Existing numeric allowlist is ignored only in the explicit entitled policy. Provider/appUS$5 guards remain unchanged. Production readiness logs report actual nonowner entitlement/capability using read-only checks, never create a sandbox and never log identities/secrets/customer content.

## Focused validation and limits

**66 local tests PASS**:10 new package/finite-pin tests and56 existing execution/disk/fixture contracts. Mocked SDK only. Covers nonowner paid without allowlist, fixed-end sponsored/trial entitlement, finite sponsored exhaustion, expired paid package, unentitled/unknown/anonymous denial, actual compatibility-path nonowner readiness, no SDK call for these readiness reads, original proof row untouched, wrong/missing pin, failed/uncleaned/noncomplete proof, altered accepted/capability/runtime/network/resources/reservation/cleanup/fixture/access/accounting bytes and changed verifier/constants all rejected. Existing tests preserve cross-owner/conversation artifact authorization, no duplicate debit, ambiguous-cost retention and global concurrency/budget. Log: `/tmp/kilas-sandbox-entitled-final.log`.

No fifth VM, paid model/speech request, customer generated-code E2E or physical-device QA was run for activation. Real remote proof remains the fourth-attempt evidence documented in `KILAS_SANDBOX_FOURTH_ATTEMPT_20261018.md`. Post-deploy verification must distinguish effective ON/read-only nonowner admission from a new production customer execution. Production HTTP remains executor CONNECT-proxy blocked; connected Render deployment/startup logs and read-only SQL supply revision/gate/unchanged-ledger evidence. Exact final release metadata is retained in `/tmp/kilas-sandbox-entitled-release.json`.

## Interpreter-portability correction

The first activation deployment76096c42 remained safely unavailable: general requestedON but acceptance_verified=False. Local Python3.12.14 and Render build Python3.14.3 differ. An identical original source serializes through ast.dump to0c9267… on3.12 andce97a5… on available3.13, reproducing the version-dependent comparison flaw locally. Original production proof row/fingerprint/digest remained unchanged.

The supplementary equivalence check now hashes exact remaining source bytes after removing ONLY the two known gate function line spans. AST is used only for source positions, not version-specific field serialization. The digest is0a31b1ae569466aac9ed192072ff5b0f7995b40ca0ceb6f6cb0e0f649a88fcf2 on both local3.12 and3.13. Full exact execution, verifier/configuration, guest/proof/fixture/access/accounting pins remain mandatory, so both gate functions remain fully pinned and no boundary restriction was relaxed. New startup diagnostics expose only compatibility_pin_matches, fixed source reason and Python minor; no secret/config values or customer data.

Correction tests:10 targeted entitlement/mutation/actual compatibility-path tests PASS after the portability fix, plus successful same-source compatibility probes on Python3.12 and3.13. Actual Render3.14 acceptance will be verified through non-generating startup logs; no new VM/proof is dispatched.
