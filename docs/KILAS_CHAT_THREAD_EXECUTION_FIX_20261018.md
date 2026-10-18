# Actual Chat composer dispatch correction — 2026-10-18

## Verified production failure

Thread147, owner9, operation `9115c2dfe18b2ff810571fb7396a51c9`: message487 →488, 2026-10-18 05:57:03.715–05:57:08.201Z. Requested and returned model both `gpt-6-luna`, direct OpenAI. One COMPLETE CHAT usage row:1,383 input/296 output tokens, estimateUS$0.000321; assistant metadata also records1,380 cache-write tokens. This is an application estimate, not a supplier invoice. No linked job/artifact and zero sandbox executions in05:56–05:59Z. The PC report clock05:57:48 differs from the durable server timestamps; correlation uses exact thread/operation IDs. No private transcript/audio was fetched.

Root cause: `/threads/<id>/send`, used by the real composer, only dispatched ordinary Chat/Search/PDF/image branches. Existing native PROJECT/isolated EXECUTION orchestration was reachable from the separate Agent conversation route. Enabling execution did not connect this composer to it. The earlier project-branch cost preflight did not establish actual UI routing; this real attempt exposed the gap.

## Correction

Natural creation/output intent (e.g. Indonesian `Buat laporan penjualan dan jadikan ZIP`, English report/CSV/ZIP, website/source projects) now enters the existing bounded PROJECT worker from the actual thread POST. Discussions, capability questions, negation, ordinary conversation, explicit Search and existing PDF/image routes retain their routing. Report/output jobs author Python and run it only through the existing gated E2B executor. Existing Office/PDF generation availability is not inferred from an allowlist or a nonexistent guest package.

A transaction creates the user turn, assistant placeholder, owned-thread checkpoint and one ONE_SHOT PROJECT step. Selected model, prior-thread context and owned upload references are snapshotted. Duplicate POST attaches to the same job; no ordinary Chat reservation is charged in addition to the native worker. Existing worker quota reservations, one-shot limits, leases, cancellation, customer execution debit, sharedUS$5/35day ledger and remote safety boundary remain authoritative. Capability/entitlement is checked again before starting queued output work. No new tables/environment settings are required.

Initial SSE identifies the durable job. The composer follows real job events through authenticated polling and starts work with the existing bounded worker/lease mechanism. Completion persists in the same Chat turn; file cards/downloads reconnect after refresh without regenerating. Stop fences the persisted job. Downloads require matching user AND thread AND job AND artifact, always use attachment disposition, nosniff and restrictiveCSP. Generated HTML never executes under the production origin. A text-only model reply without its required tool result is a terminal honest failure, with no VM.

The tested execution bundle/finite compatibility verifier are unchanged. Large-output acceptance remainsOFF: this correction does not validate packages, enable large files or transfer a failed proof.

## Targeted verification

- 44 routing/model/execution-entitlement testsPASS.
- 23 thread/selected-artifact/binary-format testsPASS, overlapping the original4 thread tests.
-Final5 actual-thread contract testsPASS after adding upload/context/JSON-CSRF coverage. Provider transport and SDK are mocked; all outside HTTP is forbidden. Covers actual composer POST → native Responses tool payload → one mock SDK VM → validated HTML/CSV/outputZIP → exact download bytes; same/foreign-owner thread isolation; duplicate POST/start; quota denial before dispatch; cancellation; missing tool result; prior-context/owned uploads; normal discussion; root execution proof compatibility.
- Real local Chromium at320/768/1440PASS: actual Chat selector/composer POST, real JSON+CSRF worker start, mock native/VM, inline file cards, CSV download-byte equality, reload without new dispatch, no page errors/horizontal overflow. Browser testing caught and corrected a missing JSON content type on start/stop. This is not physical Android or post-release paid inference acceptance.
- JavaScript syntax and `git diff --check`PASS.

Evidence: `/tmp/kilas-thread-project-tests.log`, `/tmp/kilas-thread-project-final.log`, `/tmp/kilas-thread-project-post-final.log`, `/tmp/kilas-thread-project-browser.log`, `/tmp/kilas-thread-project-{320,768,1440}.png`.

No new model/speech/search/VM call, package/template build, credit purchase, budget change, credential action or automatic replay of thread147 was performed. The one approved PC task was consumed by the original failed UI attempt; release verification is read-only. New paid production acceptance requires separate authorization.
