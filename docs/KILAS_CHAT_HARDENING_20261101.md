# AI Chat audit hardening — 1 November 2026

Scope: seven confirmed findings on baseline c1ef653422f83b633effff4938fc2e0a3da9dd4f. AI Chat remains primary; Copilot code/history stays retained and hidden. No provider/model/pricing/hosting-plan change and no production data reset.

## Changes

1. Hub remains one process (process-local Translator registries preserved), now a bounded eight-thread Gunicorn worker. Native Chat transports share two producer slots, held until the actual producer exits. Queue size32, first text60s, idle text45s, total180s **per provider attempt**, connect5/read30s. Consumer cancellation/deadline does not wait for a blocked provider; a blocked producer retains its slot until native transport unwinds. Never retry an uncertain dispatch. Existing per-account reservation/concurrency rules remain unchanged. Image normalization is limited to one concurrent decode to contain memory on the existing512MiB instance. This is bounded moderate concurrency, not unlimited capacity.
2. Legacy composer retains operation keys for uncertain text and attachment outcomes, including model/image-model identity. Terminal outcomes and explicit cancel permit a new operation. Server additive request fingerprints bind owner/thread/content/files/model before replay or reservation. No repeated paid call or history append on identical retry; changed payload conflicts409. Completed replay preserves accounting.
3. One policy: photo8MiB, document2MiB, aggregate10MiB; request cap10MiB+128KiB overhead on Chat endpoints only. UI and both parsers use these caps;413 returns a localized structured error. Prior100MiB promise was unusable behind12MiB HTTP cap. Existing pixel/normalization/spooling checks retained.
4. Legacy history gets cursor links for earlier/latest messages. Additive owner/thread checkpoints advance at most1024 old rows per context build; summary3000characters, recent context remains bounded. A remaining indexing gap is disclosed. Summaries reserve space for recent original quotes independently of language keywords and retain chronological ordering; expanded multilingual correction hints complement this fallback. This is selective recall, never a promise to remember every fact indefinitely. Source messages stay unchanged.
5. Absent Chat sessions return401 before invalid-CSRF parsing, without granting access or exempting authenticated actions from CSRF. UI offers explicit sign-in in another tab, retaining text/files in the current page's memory. On retry it reloads session CSRF before dispatch. Existing revocation and tenant gates remain authoritative. No persistent browser draft store or automatic upload/login.
6. Scoped Chat active-tab text #ad3d00 on peach (~5.6:1) and hint #626a7a on white (~5.4:1); Finance and audio colors unchanged. Browser checks computed colors and responsive behavior.
7. Authored Chat/interface keys now cover ID/EN/ES/ZH, including recovery, validation, history and model selection. Generated/source text, language inference, model identities and user history titles are never translated by UI locale.

## Migration / release

0112 adds only `kilas_thread_request_payloads` and `kilas_thread_context_checkpoints`, with ownership fields and thread-delete cascade. SQLite migration registry and checksum-guarded PostgreSQL targeted boot release are registered. No destructive statement or rewriting of old messages. Previous code can read the same DB; rollback means deploy prior commit and leave additive tables in place. Existing production release remains active until normal CI/review/merge/deploy succeeds.

## Evidence before CI

-100 Python tests +212 subtests passed across isolated models/recovery/quality/sent-attachments/i18n/restoration/history/new-hardening suites. Existing runner imports some files without executing unittest classes, so this release explicitly runs pytest per file.
-Node operation-state test passed.
-Actual shipped Gunicorn config, two synthetic owners processing1.5s each: both complete, health200 in0.003s, one gthread worker/eight threads. No external provider calls.
-New real Chromium composer:360/393/820/1440, four UI locales, text/photo uncertain retries dispatch once, preserved draft after401 and explicit new login, oversized photo rejection, computed contrast and zoom200%, no page errors/overflow. Existing agent recovery browser suite also passed390(scale2)/1440, cancel then new message and uncertain replay.
-Native PostgreSQL release/concurrent-binding/checkpoint rehearsal is extended in existing disposable-loopback CI job; terminal CI result must be checked before release. No production DB test writes.

## Remaining acceptance limits

No paid inference, actual provider/model quality benchmark, real photo OCR/vision, physical-device microphone, Safari/Firefox/screen-reader certification, or production load test. Deadline tests use synthetic stalled/trickling sources. A provider already contacted can still bill after local cancellation; unknown usage remains conservative rather than assumed zero. Process-local stream limits and existing memory mean overload is rejected; no increase in hosting spend was authorized.

Initial baseline Actions has six failing and three successful workflows; current failures must be compared at job/assertion level. Focused green tests do not make all historical CI green.

Technical references: [Gunicorn workers](https://gunicorn.org/design/) and [Requests timeout semantics](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts).

## Baseline comparison during review

A separate read-only worktree at c1ef6534 ran the same eight failing suites under the same local environment. Candidate and baseline fail the same test identities: workspace runtime(1), Core simulator(10), WhatsApp(5), workspace/Finance labels(3), legacy Chat fixtures(5), automation(1), connectors(5), subscription lifecycle(1). Cost/quality separately matches the same pre-existing paid-offer wording failure(1); the two new concurrency errors seen in the initial candidate were fixed by preserving existing reservation policy, not by weakening those tests. Anonymous legacy Chat's CSRF-first400 assertion now sees explicit401, intentionally; authenticated invalid-CSRF remains400 and is covered by the new regression.

Existing Autonomous PostgreSQL rehearsal excludes the conversation-creating migration but still applies dependent migrations, failing with missing `kilas_ai_conversations` on baseline too(job124573231161). The focused current Chat PostgreSQL rehearsal instead applies full compatible baseline and0111/0112 twice, then checks preserved history, checksum and concurrent payload claims; it passed on the implementation candidate. Final-head CI and deployed version remain release-time checks, not inferred from this document.

HD attachment contract is updated from the impossible100MiB promise to the new8MiB/10MiB policy; separate actual HTTP and browser tests verify rejection and clear errors. Existing pixel safety and original-byte tests remain enabled.

## File capacity disclosure

The attachment chooser title and selected-file caption explicitly show photos8MiB, documents2MiB and aggregate10MiB in all four UI locales. Rejected picks keep previously selected files and draft text. An accepted-but-interrupted agent stream also keeps both for an idempotent retry; a failed history refresh does not turn a completed response into a new send.

The2MiB document cap is the existing bounded input/parser contract, not a newly implemented large-document service. Office/ZIP validation and extracted-context limits remain enforced. Large file generation/workspace-output capabilities are separate and do not prove arbitrary large input support; real large-document ingestion/OCR acceptance is NOT RUN. Raising this limit needs a separately tested bounded ingestion design rather than just raising the HTTP cap.

### Focus-transfer regression caught before release

Real CI pointer diagnostics found the recovery link moved24pixels between mousedown and mouseup: `kilas_home.js` dispatched `home:viewport` for every focus transfer, remeasuring the textarea when dimensions had not changed. The click landed on its paragraph. Layout dispatch is now keyed to real viewport dimensions/scale/keyboard/hierarchy changes; input changes still resize directly, and viewport/keyboard/zoom changes still reflow. Recovery action is also a standalone44px touch target. The browser regression asserts both navigation and stable pointer hit target, not just an existing link.


Final broad CI caught two additional regressions rather than baseline failures: same-dimension viewport events stopped following the latest message, and the added capacity caption overlapped pending-file controls in a320px/300px visual viewport. Scroll following is now independent of textarea remeasurement. Capacity remains on the chooser; the repeated selected-file caption is hidden only while the keyboard is open. A paired synthetic320px probe passed on baseline but failed on the candidate before this fix. The six existing viewport Node tests are now included in the focused gate. Full keyboard cycles, the genuine login-click browser regression and final CI must pass after these corrections. No tests were weakened to mask either issue.
