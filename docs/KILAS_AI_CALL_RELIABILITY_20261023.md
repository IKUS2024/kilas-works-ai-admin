# AI Call reliability and recovery

Baseline/live source before this change: `0bcea195983103e1892dd49de6945c075d0a2701`. Scope remains AI Call. No Finance, Translator, Voice Over, Creative Services, account roles, billing amounts, credentials or provider flags are changed. Existing Chat zoom/composer layout is retained.

## Evidence and limits

The two recent production Call records (21:58:07 and 21:59:10 UTC) ended after 63s/33.1s input and 4/2 turns, both with `call_ended`. The old client sends every terminal fault through the same End path, so those logs cannot establish the specific user's disconnect cause. The screenshot's generic microphone/network text is not evidence of a microphone/network problem.

Verified defects addressed:
- A transient failed PCM HTTP response immediately closed the call. Retrying safely was impossible because the server rejected duplicate indexes.
- The server's 8s browser heartbeat was as short as one HTTP timeout, while polling retries could take longer.
- Valid provider checkpoints were discarded unless received after GoAway; transport loss never attempted supported resumption.
- Any non-running mobile AudioContext state immediately ended the call.
- AI Call inherited Chat's CLIENT_OWNER/trial route gate even though its account admission policy supports authenticated non-owner roles. An actual CLIENT_MEMBER route test reproduced 404.
- End remained visible after termination; settings were visually sparse with weak label contrast.

## Behavior

PCM uploads retry only transient network/timeouts/502–504 twice with 300/600ms backoff, the same index and identical bytes. Server acknowledges only an exact hash match for the immediately preceding chunk, without enqueueing or metering twice. Older/different payloads fail. No auth, budget or malformed-response retries. Browser input buffering is capped at 20s; server at 20s/128 packets. The browser absence deadline is 30s, preserving bounded cleanup and normal funding/authorization checks.

Provider recovery retains the latest valid resumable handle; false/revoked handles clear it. Socket send/receive loss can resume the same session with at most two recoveries per minute and two pre-setup connection attempts. Settings, capability and base/mode prompt remain unchanged. No new budget claim/dispatch or automatic fresh call. Uncertain sent PCM is never replayed; incomplete latest speech may need repeating. Recovery clears stale audio and cancels the active search job without disabling later searches. No retry after an uncertain setup send; missing/revoked checkpoints fail honestly. Normal GoAway handoff uses the latest valid checkpoint. Implementation follows Google's session-management contract: https://ai.google.dev/gemini-api/docs/live-api/session-management .

Temporary AudioContext suspension holds existing playback and incoming PCM and tries resuming that same context, bounded to 3.5s. It does not reacquire the mic. Real capture loss/frozen audio still fails. End cancels timers, buffered audio, capture, retries and the owned session; it never restarts automatically. Closed/hidden page behavior remains privacy-preserving. Diagnostic End reasons are allowlisted codes only, with no audio/text/secrets logged.

Only exact Call endpoints receive the authenticated-role gate correction; Chat and other product routes retain their prior restrictions. Call admission, disabled accounts, CSRF, ownership and capacity checks remain authoritative. A dedicated authenticated `/kilas-ai/call` page provides access without opening owner-only Chat routes.

Settings now occupy a compact high-contrast card with a nearby primary Start action. Active calls show mode/character and active controls; ended calls hide End and retain choices with a retry action and specific failure messages. Close remains available. Roast adds bold, animated emphasis/optional raised-voice guidance where supported, without volume changes, unsupported emotion flags or guarantees; consent, stop and sensitive-context rules remain.

## Validation

No paid provider calls or production call sessions were started.
- 167 focused Python tests +176 subtests passed; the final added worker-resumption test also passes in the 9-test offline recovery suite. Ten legacy search-smoke tests are excluded from this focused run; their existing size-fence failures were reproduced on baseline during the prior release and have not been weakened.
- 66 JavaScript tests pass, including identical upload retry, abort during backoff, no retry for auth/validation, paused playback/drain and no late playback after End.
- New 9-test Python recovery/access suite passes through the repository network-blocked runner: actual worker socket recovery, capability/dispatch preservation, invalid/absent checkpoints, bounded retries, deliberate End, diagnostic allowlist, account-role matrix and cross-account denial.
- Five local Chromium sizes (320x640, 390x844, 768x1024, 1440x900, 480x300), including 2x pinch: settings, consent, synthetic failed upload ACK/retry, same-context audio suspension/resume, immediate Stop/Normal, ended controls and retained language settings pass.
- Existing four Call lifecycle scenarios pass; existing 57 Chat zoom checks pass (including 2x/3x pinch, desktop reflow, large text and bottom composer).

Actual Android device/network behavior and Gemini voice/prosody are not certified by these mocks. Zero-error operation cannot be guaranteed. The prior environment proxy CONNECT 403 blocks production HTTP/asset checks; no bypass is attempted. Deployment revision and startup are verified through Render, with final evidence in the task result.
