# Scoped Luna image-detail experiment

This is diagnostic infrastructure, not an established image-identification improvement. PR194's transport/provenance tests passed, but parent reports that real-photo semantic acceptance still failed. Preserve Luna, the current grounding instruction, source bytes, effort, output budget, safety and billing. No real photograph, prompt, reply, private URL or secret belongs in this repository or the diagnostic logs.

## Behavior and scope

`KILAS_AI_VISION_EVAL_THREADS` is absent/empty by default. When OFF there are no extra scope queries, image decoding, payload edits or diagnostic logs. The server-only value is a JSON object mapping at most eight positive thread IDs to `auto` or `high`; example using invented IDs:

```json
{"900001":"auto","900002":"high"}
```

Unknown values, duplicate keys, oversized/invalid JSON, malformed IDs or more than eight entries disable the entire mapping. No request parameter can set scope, model, detail, effort or configuration. The eight-thread bound limits diagnostic scope, not normal Chat usage.

Only the existing authenticated legacy Chat send route may bind an internal grant, after normal admission and an independent ownership/session/route check. The thread must contain exactly its first user turn. The final selected OpenAI payload must be Luna with a single user turn and exactly one validated raster image whose detail is omitted. Existing histories, follow-ups, Agent Chat, Voice Over scripts, other tools/models and scheduled jobs do not receive the experiment. The grant belongs to that exact in-memory context and is not inherited by copied contexts.

Auto preserves the payload exactly, including omitted detail. High copies only the image block dictionaries to add `image_url.detail="high"`. Bytes, source context and shared message objects remain unchanged. It does not modify temperature, effort, token caps, prompts, endpoint, streaming/store options, ledger, retry or moderation behavior. There is no new endpoint, UI selector, debug/admin surface, migration, access grant or credential.

## Obtain fresh thread IDs without contaminating context

The existing UI creates a thread before its first send using `POST /kilas-ai/threads`. This endpoint requires `first_message` to select a mode, but does not append it to conversation messages or invoke inference. The regression verifies an owned empty thread and zero provider POSTs. No new endpoint is needed.

The normal New Chat UI opens an empty composer without allocating a persistent legacy thread ID. Its first Send automatically creates the thread and then calls inference. There is no separate existing normal UI control that reserves an empty legacy thread. Do not send a dummy message to discover an ID: that contaminates the context.

The existing POST is a technical capability, not independent permission to issue background browser requests. The parent browser worker must first check its own supported-tool/skill restrictions. ONLY IF those permit the authenticated application request, the following setup can create eight empty QA threads. It keeps the current CSRF token in place and never prints/exports it. Do not copy cookies/session/CSRF to a shell or another environment. If this request method is unsupported, stop setup and report the specific browser-tool limitation; parent must choose a supported same-runtime setup or separately review an equally narrow server-only control before testing. This candidate has not added an alternative access/debug route.

Conditional setup for an authorized browser operator (not an executor command):

```javascript
const token = document.querySelector('meta[name="csrf-token"]')?.content;
if (!token) throw new Error('Open the authenticated Kilas Chat page first.');
const created = [];
for (const pair of ['original', 'control-1', 'control-2', 'control-3']) {
  for (const arm of ['auto', 'high']) {
    const response = await fetch('/kilas-ai/threads', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': token},
      body: JSON.stringify({first_message: 'Visual QA setup'})
    });
    if (!response.ok) throw new Error('Thread creation stopped: '+response.status);
    const item = await response.json();
    created.push({pair, arm, thread_id: item.thread_id, url: item.url});
  }
}
created;
```

If interrupted, preserve already returned IDs and inspect existing history before rerunning; do not blindly create duplicates. Do not send a greeting/dummy message to discover IDs. Do not use an existing conversation with previous answers. Parent may confirm zero message counts via authorized read-only SQL before testing. An expired session/CSRF or product-availability error must be resolved through the existing flow; do not bypass it.

## Coordinated candidate rollout and test

1. Parent reviews the draft and final tests, then coordinates normal release of its exact commit. This executor does not merge/deploy. Leave the flag absent during deployment; the suspended legacy service is untouched. No provider payment, model, credential, hosting or permission changes.
2. Build the server mapping from the actual empty QA IDs above. Activate only on the existing Hub using the normal authorized configuration workflow. Runner/scheduled execution requires no flag and remains unaffected. Verify the exact active commit/configuration; do not publish the IDs or account details in PR artifacts.
3. Through the authenticated UI, submit the same original image and exact same neutral question to the original pair, with identical app locale and no prior messages/search/tools. First run exactly one request per arm, without retries or duplicate executor calls. Inspect matching request/response diagnostics to prove actual payload detail and requested/returned Luna. Confirm same source byte count/dimensions, image count, effort and output cap across arms. Transmitted dimensions are not evidence of provider-internal resized dimensions.
4. Apply the single-attempt/outer-success eligibility checks below BEFORE grading. Parent privately scores only eligible answers for identity, visible physical evidence, unsupported claims and proportionate uncertainty. Do not give the model an expected object name or prior incorrect answer. Record scores in nonsensitive summaries; keep original photographs/replies private. A single result per arm is screening, not reliable statistical evidence.
5. If appropriate, evaluate the three preselected ordinary-object controls in the other fresh pairs: e.g. a printed mug, a lidded food container and a handled kettle. Select nonsensitive consented photos independently of results, preserve the entire object, and use the same question within each pair. No generated answers or synthetic pixel transport assertions count as actual semantic evaluation.
6. If high alone fails, the next isolated variable is medium-to-high reasoning with auto detail and everything else as A. That effort override is deliberately not implemented here. Do not combine higher effort, image crops, altered prompts or a different model into this experiment. Further experiments need separate coordinated scope.
7. Clear/remove the mapping after the bounded evaluation. New requests immediately return to normal behavior; an already bound request finishes with its accepted variant. Do not delete conversations or source images. No database rollback is needed. Retain the existing release rollback path.

Changing only detail may improve, worsen or leave the result unchanged. Do not roll out high globally from one passing object. There is no guarantee of correct recognition.

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

- Request: arm, requested Luna, image MIME/width/height/byte count, image count, effective detail plus whether explicit, exact reasoning effort/output cap.
- Response: validated returned model (or `unreported`), sanitized provider request ID, HTTP status, finish reason/status, provider-stream duration/TTFT, numeric input/output/cached/cache-write usage. Missing usage is unknown/null, not fabricated zero.

Diagnostic `status=finished` means ONLY that this provider iterator observed a recognized finish frame (`stop`, `length`, `refusal` or `content_filter`). It is not an outer-route success signal and is not an acceptance result. Structural validation, a repair, later stream delivery, persistence or usage finalization can still fail after that frame. Refusal/content-filter, truncation/length and any later route failure must be marked and excluded as appropriate, rather than treated as a successful high answer. Use the outer `done`/persisted status/usage checks above.

No prompt, answer, filename, private URL, base64/pixels, full EXIF, key, header dump, full provider body, account ID or thread ID is logged. Error/cancel/incomplete streams remain observable without raw exception text. No extra provider attempt is added. The metadata parser validates existing in-memory data only; it never changes/resizes/compresses the image. It is optional and no extra stored image is created.

## Validation and known gaps

Local scoped gate:21 targets,252 tests +397 subtests passed. The final experiment suite was also rerun after enabling production CSRF validation explicitly in the new auth test:13 tests +21 subtests passed. Fixtures are synthetic, native provider calls mocked and general network transport forbidden by the existing harness. Tests cover exact A/B payload difference, scope/auth/ownership/first-turn boundaries, malformed configuration, bytes/dimensions, logging allowlists, no raw error echo, no retries and empty-thread setup. Existing image/moderation/usage/recovery/quality suites remain included in the managed gate. No UI redesign.

Zero paid calls or image uploads by this executor. No actual high-detail semantic result is claimed. Historical direct read-only database evidence established returned Luna and identical original/QA stored bytes; final payload detail/effort/image count were not historically persisted. This feature supplies future request-boundary evidence, not retrospective proof.

## Official API references

- [GPT6Luna](https://developers.openai.com/api/docs/models/gpt-6-luna): image input, supported reasoning efforts, current model rates.
- [Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): image_url.detail schema.
- [Vision guide](https://developers.openai.com/api/docs/guides/images-vision?api-mode=chat): omission defaults to auto. Current sizing table has no explicit GPT6Luna row; do not assume auto=low or borrow another model's patch multiplier. High does not necessarily retain more resolution than auto.
- [Pricing](https://developers.openai.com/api/docs/pricing): record actual usage/cache writes and processing tier; image byte size is not a billable-token estimate. The Sep25 encoding fix in the [changelog](https://developers.openai.com/api/docs/changelog) predates the reported failure and is not proof of its cause.
