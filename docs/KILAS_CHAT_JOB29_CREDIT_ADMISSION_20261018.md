# Thread 149 / job 29: credit admission before authoring

## Production evidence (read-only)

Exactly one user submission exists in thread 149: user message 491, assistant
492, job 29, step 33, operation `98d9cdb8550c8e90f69cd37b4a9252f7`.
The job was created at 2026-10-18 06:39:06.423733 UTC and failed at
06:39:29.098474 UTC. No replay, resume or replacement request was made.

OpenAI returned the selected `gpt-6-luna`. Usage 707 recorded 630 input and
2,471 output tokens, estimated $0.001298. This is an application estimate, not
a verified supplier invoice. The model generated source successfully; events
reached VERIFYING and PACKAGING, with no STARTING_SANDBOX/RUNNING_CODE event.
No execution row exists for job 29, so no new VM or associated cleanup occurred.

The two artifacts are source-only: artifact 25 `source-project.zip` (3,066 B,
SHA256 `60a128b314eb730745f868dd547f0ef3272dd97f05d392698b59f62c900d2360`)
and artifact 26 `main.py` (5,841 B,
SHA256 `60abd233c918f30b280e21d5a60bca6949ff4186d17afac307ef9145adc8d024`).
They are not the requested generated HTML/CSV/report ZIP. The owned ZIP route is
`/kilas-ai/threads/149/jobs/29/files/25`; no authenticated production download
was attempted during this diagnosis.

## Reproduced funding blocker

The retrieved synthetic source passes the actual source/ZIP parser, Python AST
syntax check, entrypoint selection, export wrapper and repeated execution input
admission. Its contents were never executed on the application host.

The actual customer reservation function deterministically raises `UsageLimit`
with the existing Premium Capacity insufficient message for the persisted
account shape: no paid subscription, no top-up credit lots, app sponsorship
eligible, and historical counted premium exposure $12.511476. That exposure was
replayed from owner-scoped usage metadata at dispatch, using the actual
`capacity.spent` function. It includes historical estimates/reservations,
including previous sponsored/QA usage; it is **not an invoice or debt**.
At the code's existing default FX (Rp17,000/USD), the shared allowance is
Rp35,000 / 17,000 = $2.0588235294117647, leaving zero usable base capacity.
The requested existing VM reservation is $0.008880. No runtime FX override
was fetched or assumed verified.

Sponsorship admits the account and model authoring, but the unchanged execution
credit reservation still enforces shared customer capacity. This is sufficient
to explain the pre-reservation failure and is reproduced with the real credit
function. The historical exception was swallowed by a generic ValueError catch;
the original traceback/code was not retained, so no recovered production
traceback or exclusive historical exception match is claimed. Job 29's original
generic metadata and ledgers remain unchanged.

## Scoped correction

- `workspace_execution_admission.py` invokes the **existing** customer reservation
  function in an always-rolled-back transaction before model authoring. The normal
  executor still repeats its real atomic reservation before SDK creation.
- Both BASE and TOPUP prechecks leave no usage/debit rows or changed balances.
  PostgreSQL may retain ordinary sequence-number gaps after a rollback; no
  financial row or credit is committed by the precheck.
- Fixed sanitized diagnostic phase/code are retained in step output, step error,
  job last_error and bounded logs. Known capacity failure becomes
  `customer_reservation / execution_quota_exhausted`. Other phases distinguish
  entrypoint selection, export preparation and execution dispatch. Arbitrary
  exception messages, source text and credentials are excluded.
- A race where capacity changes after authoring remains blocked by the actual
  reservation; source-only files are honestly retained and the job fails without
  an SDK call or automatic retry.
- Existing capacity errors already have ID/EN/ES/ZH translations. No UI layout,
  pricing, trial allowance, subscription, customer credit, history or budget changes.

The proven small-execution bundle, exact compatibility pins, customer accounting,
network/resource/cleanup restrictions and shared $5 limit are unchanged. Large
outputs remain OFF; their unaccepted source fingerprint changes naturally with
the project module and is not repinned or enabled.

## Targeted local verification

24 tests passed: seven new job-29 admission contracts, seven existing thread
composer/native/artifact contracts and ten execution-entitlement/proof-pin
contracts. Command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=client-hub:client-hub/tests \
  /tmp/kilas-call-venv/bin/python -m unittest \
  test_kilas_job29_execution_admission test_kilas_thread_projects \
  test_kilas_workspace_execution_entitled -q
```

Coverage includes the exact saved source/hash, real Chat POST to worker and
mocked provider/SDK, funded nonowner success and owned download bytes, foreign
download denial, no duplicate execution/debit on restart, unfunded account
stopping before the model, BASE/TOPUP rollback, post-authoring funding race,
sanitized unexpected failures and unchanged strict proof compatibility.
The test ZIP contains only the previously approved synthetic sales source.
No generated source, real model call or real VM was executed. Local evidence:
`/tmp/kilas-job29/targeted-final.log`; metadata replay is local-only in
`/tmp/kilas-job29/accounting.json` and is not committed.

## Remaining owner decision / acceptance

The application correction does not fund this account. Real execution for the
affected unfunded account remains unavailable until an existing funded
plan/top-up or a separately approved, finite funded sponsorship is provided.
The historical exposure is not an amount to pay. No funding grant, ledger reset,
paid retry or new browser acceptance is authorized or performed by this release.
Production functional execution/download after this change remains untested;
release verification is non-generating startup/read-only evidence only.
