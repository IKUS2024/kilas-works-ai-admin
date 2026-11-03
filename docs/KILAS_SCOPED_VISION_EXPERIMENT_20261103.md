# Scoped Luna image-detail experiment

This is diagnostic infrastructure, not an established image-identification improvement. PR194's transport/provenance tests passed, but parent reports that real-photo semantic acceptance still failed. Preserve Luna, the current grounding instruction, source bytes, effort, output budget, safety and billing. No real photograph, prompt, reply, private URL or secret belongs in this repository or the diagnostic logs.

## Default-OFF scope compatible with normal UI

`KILAS_AI_VISION_EVAL_BATCH` is absent/empty by default. OFF performs no extra admission queries, image decoding, payload edits or diagnostic logging. The server-only JSON has exactly five fields. This intentionally inactive example uses invented values; parent must obtain the existing QA owner's ID privately and set current UTC times only AFTER the candidate is verified live and the browser is ready:

```json
{"owner_id":123456,"batch":"00000000000000000000000000000001","question":"Identify this object.","starts_at":"2030-01-01T12:00:00Z","expires_at":"2030-01-01T12:20:00Z"}
```

- `owner_id`: one existing authenticated QA account, positive integer. No new account, role, credential or access grant.
- `batch`: new random 32-character lowercase hexadecimal label for this approved test, not a credential. Never auto-generate/reset it per worker, restart, request or retry.
- `question`: one exact neutral question (1–200 characters, no surrounding whitespace/control characters), identical for every arm/control. Keep the actual chosen question and QA values private. It is a server criterion, not a model/detail override exposed in request data.
- `starts_at`/`expires_at`: explicit UTC RFC3339 strings ending Z. The window must be active and no longer than 30 minutes. This expiry applies ONLY to diagnostics; it does not end free Chat/image testing or change customer limits.

Malformed/duplicate/unknown fields, wrong types/owner, inactive/overlong window, a different question, old thread, existing history, non-Chat route, other model, text-only/multiple-image input or exhausted batch leave normal Chat behavior unchanged. No public debug surface, arbitrary request knob, guessed future thread ID, background browser API request or session/CSRF export is needed.

The existing route validates admission/auth/ownership, persists the new thread's first user turn and image, then binds scope internally. The module independently checks the authenticated session/route and owned thread, exactly one current user turn and one image. The thread must have been created inside the active window. Only selected Luna on the ordinary legacy send route participates; Agent Chat, follow-ups, regeneration, Voice Over scripts, other tools/models and scheduled execution stay outside scope. A copied/repair context does not inherit a grant.

## Atomic ordering, idempotency and batch identity

Additive migration 0114 creates `kilas_ai_vision_eval_claims` with owner ID, batch label, ordinal 1–8, thread/message references and a SHA256 fingerprint of the canonical server configuration. No raw question, prompt, answer, filename, image, URL or key is stored. Primary key is global `(batch,sequence)`; owner/thread and owner/message are unique. There is no thread/message foreign-key cascade, so deleting a chat does not recycle an ordinal. Account deletion retains the existing user-cascade semantics; never reuse a batch label.

PostgreSQL claims use a transaction-scoped advisory batch lock plus the existing bounded owner-row lock; SQLite uses the existing BEGIN IMMEDIATE transaction. No lock spans inference, streaming or ledger finalization. Atomic admission order assigns 1=auto, 2=high, 3=auto, 4=high, through 8=high. It is claim order, not response-completion order or guessed thread IDs. Concurrent workers cannot duplicate or overrun slots. Parent must send sequentially within each pair; unexpected/concurrent sequence means stop and reconcile privately, not guess which photo belongs to which arm.

The first accepted claim freezes the batch's owner, question/window and scope fingerprint globally. Replacing the owner or scope under the same used label is rejected, including from another account. Repeated admission of the same first turn returns its existing ordinal. The normal operation-key retry path replays the persisted answer without a second provider call or slot; the HTTP regression verifies outer done and replay. Failures/abandoned admitted attempts consume their ordinal, with no refund/recycling. Exhaustion disables the experiment, not normal Chat. Explicit approval is needed for a separately planned repeat rather than silently starting a new batch.

A storage/migration failure leaves ordinary payload behavior intact and emits only fixed `kilas_vision_eval_scope_storage_unavailable`, never exception text. No evidence means no grade. Clearing the flag, expiry or exhausting slots prevents new grants; an already accepted in-flight grant retains its arm. A normal restart cannot reset persisted ordinals.

## Payload and diagnostic behavior

Auto preserves the final payload exactly, including omitted detail. High copies only image dictionaries to add `image_url.detail="high"`. Source bytes, question/context/system instructions, model, effort, output cap, transport, moderation, idempotency, existing repairs and billing remain unchanged. The validated grant belongs to that exact in-memory context. The request event records the ordinal so the operator can verify assignment privately without logging owner/thread identifiers.

## Coordinated deployment and supported UI test

1. Parent reviews final tests and exact commit. Deploy code with the flag absent/OFF through the established Hub release workflow. The existing `chat_model_routes.prepare_chat_models` blueprint startup hook now automatically invokes checksum-guarded `apply_release('0114_kilas_vision_eval')` after 0113 whenever Kilas AI is enabled, even with the experiment OFF. Confirm fixed startup marker `KILAS_VISION_EVAL_SCHEMA_READY schema=0114` and health before activation. No production shell or read-write SQL connector is required. Do NOT enable broad `RUN_MIGRATIONS_ON_BOOT`. No production migration/configuration was run by this executor. Do not resume the suspended legacy service. Runner/scheduled jobs require no experiment flag.
2. Only after verified deployment and a ready authenticated browser, parent privately configures the single QA owner, one neutral question, new batch label and short current window. Do not publish actual configuration/IDs/question in PR artifacts or logs. Avoid other testing/activity on that account during the window. Other users remain unaffected.
3. In the normal visible UI click New Chat, select the original photo, enter the exact neutral question, then Send. The app's ordinary JS creates the thread and sends the message. No preallocated ID, DevTools fetch or background setup request. Wait for completion/reload/usage checks. The first admitted request is ordinal 1 (auto).
4. Click New Chat again, upload the SAME unchanged original and enter the SAME question. The next admitted request is 2 (high). Verify logs report the expected ordinal/arm and requested/returned Luna. Compare transmitted image dimensions/bytes/count, exact effort/output cap and outer success. Do not assume provider-internal resized dimensions equal transmitted dimensions.
5. Apply grading eligibility below BEFORE scoring. Parent privately evaluates identity, physical evidence, unsupported claims and appropriate uncertainty, without giving an expected object name or previous wrong reply to the model. One result per arm is screening, not statistical/general-quality proof.
6. If the original pair completes cleanly, use the remaining three fresh pairs for preselected nonsensitive ordinary objects, e.g. a printed mug, lidded food container and handled kettle. Each pair uses the same file/question within the pair. Do not claim synthetic transport fixtures are semantic controls. Exactly eight primary test sends are planned; no blind retries. A structural repair can cause an additional separately metered default attempt and makes that sample ineligible, as described below.
7. If high alone fails, the next isolated variable would be auto detail with medium-to-high effort and all else as A. That override is NOT implemented. Do not bundle effort, crops/resizing, another prompt or another model here.
8. Clear the flag after the bounded evaluation. Rollback leaves the additive claim table/history intact; old code ignores it. Do not drop/reset production data. If a test fails or becomes ungradable, stop/reconcile; no slot refund or automatic rerun. Preserve the existing release rollback path.

No high-detail accuracy improvement is yet established. All real tests remain parent-coordinated. The local Chromium regression uses the visible New Chat/upload/Send workflow, not direct background setup calls.

## Grading eligibility: exactly one attempt and completed outer route

The existing structural guard is unchanged and can perform one separately metered repair. In `chat_quality.ChatQualityStream`, that repair builds a NEW copied ChatContext, adds repair instructions and changes the reasoning profile. The copied context correctly does NOT inherit the experiment grant. A high attempt can therefore be followed by an unlogged-by-this-feature default/auto repair whose final answer appears in the UI. Do not label that final answer as high, combine both attempts' costs as one inference, or switch off the guard to make a sample pass.

For each arm, require all of the following:

- Exactly one intended UI send with no manual retry, and one matching diagnostic request/response pair for the first provider attempt, ending with `finish_reason=stop`. The returned model, original bytes/dimensions, effort and output cap must meet the pair's held-constant checks.
- No SSE `reset` event, replacement/restarted answer, or `KILAS_CHAT_VALIDATION` event for the operation/window. That existing content-free log records `model`, `attempt`, `finish`, and issue codes. Any structural validation/repair makes the sample ineligible, even if its final answer looks good or the repair was blocked.
- Authorized read-only usage reconciliation must find NO reservation/usage operation with the initial operation key plus `:quality-retry`, regardless of its eventual status. Check the existing original operation and its usage, without publishing user IDs, keys, prompts or answers. Multiple accounting rows for one operation are not a provider-attempt count; distinguish operation keys and usage types. A single diagnostic pair alone cannot exclude an uninstrumented repair.
- The browser received the outer `done` event without `error`, cancellation, disconnect or truncated delivery; reload confirms the assistant message is persisted with `status=complete`, and original usage finalization is terminal/successful. Reconcile that attempt's provider usage with existing persisted usage (unknown/missing data is not proof of success).
- If the attempt count, guard/reset evidence, final persistence or usage cannot be established, mark the result **ungradable/attempt provenance uncertain**, not an auto/high semantic result. Preserve evidence privately and coordinate a fresh thread for any separately authorized repeat; do not silently retry an arm or overwrite a failed run.

These checks deliberately leave existing quality repair and billing behavior intact. A repaired run may still be useful for product-level diagnosis, but is excluded from the controlled one-variable A/B comparison.

## Content-free diagnostic contract

Only the configured QA request emits `kilas_vision_eval` JSON events to module logging. A random run token correlates two events without account/thread identifiers.

- Request: arm/ordinal, requested Luna, image MIME/width/height/byte count, image count, effective detail plus whether explicit, exact reasoning effort/output cap.
- Response: validated returned model (or `unreported`), sanitized provider request ID, HTTP status, finish reason/status, provider-stream duration/TTFT, numeric input/output/cached/cache-write usage. Missing usage is unknown/null, not fabricated zero.

Diagnostic `status=finished` means ONLY that this provider iterator observed a recognized finish frame (`stop`, `length`, `refusal` or `content_filter`). It is not an outer-route success signal and is not an acceptance result. Structural validation, a repair, later stream delivery, persistence or usage finalization can still fail after that frame. Refusal/content-filter, truncation/length and any later route failure must be marked and excluded as appropriate, rather than treated as a successful high answer. Use the outer `done`/persisted status/usage checks above.

No prompt, answer, filename, private URL, base64/pixels, full EXIF, key, header dump, full provider body, account ID or thread ID is logged. Error/cancel/incomplete streams remain observable without raw exception text. No extra provider attempt is added. The metadata parser validates existing in-memory data only; it never changes/resizes/compresses the image. It is optional and no extra stored image is created.

## Validation and known gaps

Local scoped gate: 21 targets, 259 tests + 404 subtests passed. The experiment suite includes 20 tests + 28 subtests, with production CSRF validation explicitly enabled in its auth test. Fixtures are synthetic, native provider calls mocked and general network transport forbidden by the existing harness. Tests cover exact A/B payload difference, scope/auth/ownership/first-turn boundaries, malformed configuration, bytes/dimensions, logging allowlists, no raw error echo, no retries, normal-UI-compatible admission, SQLite concurrent cap/idempotency/expiry/configuration fences and no recycling after deletion. A focused startup test proves automatic 0114 selection with broad migrations forbidden and no experiment activation. Disposable native PostgreSQL 16/18.4 tests exercise the real new startup helper and checksum idempotency, 12 simultaneous claims/8 slots, stable retry, ownership/expiry fences and unchanged existing usage. Older startup releases are stubbed only in that focused native test; the new 0114 helper executes against real PostgreSQL. Chromium tests 4 fresh UI pairs (393/1440 × EN/ID), 8 mocked native calls, exact payload comparison and persisted reload. Existing image/moderation/usage/recovery/quality suites remain included in the managed gate. No UI redesign.

Zero paid calls or image uploads by this executor. No actual high-detail semantic result is claimed. Historical direct read-only database evidence established returned Luna and identical original/QA stored bytes; final payload detail/effort/image count were not historically persisted. This feature supplies future request-boundary evidence, not retrospective proof.

## Official API references

- [GPT6Luna](https://developers.openai.com/api/docs/models/gpt-6-luna): image input, supported reasoning efforts, current model rates.
- [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): image_url.detail schema.
- [Vision guide](https://developers.openai.com/api/docs/guides/images-vision?api-mode=chat): omission defaults to auto. Current sizing table has no explicit GPT6Luna row; do not assume auto=low or borrow another model's patch multiplier. High does not necessarily retain more resolution than auto.
- [Pricing](https://developers.openai.com/api/docs/pricing): record actual usage/cache writes and processing tier; image byte size is not a billable-token estimate. The Sep25 encoding fix in the [changelog](https://developers.openai.com/api/docs/changelog) predates the reported failure and is not proof of its cause.
