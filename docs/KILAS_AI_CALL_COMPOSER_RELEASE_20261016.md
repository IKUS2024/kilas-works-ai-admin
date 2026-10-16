# Kilas AI composer and continuous Call correction

Baseline: main / production `9422f94d5c7d2d08b26197316190f2ebf8fe8852`.
The checkout was clean and matched freshly fetched main before editing. No stale
Creative Services drafts were applied. Scope is only Kilas AI composer and Call.

## Causes and fixes

- The long localized placeholder consumed the narrow text column beside Send.
  Both chat composers now use the short localized Message/Pesan/Mensaje/消息.
  Plus remains left; icon-only Send then icon-only Call remain right. The input
  follows its computed minimum height (44px, including a full 24px line and 20px
  padding), wraps entered text, and grows within the visible viewport. The agent
  form no longer overrides bottom safe-area padding with zero. Keyboard detection
  also handles Android resizing both visual and layout viewports equally.
- Production's read-only startup report showed only 100,000 microUSD remaining
  in the shared experimental funding envelope, below its 250,000 admission
  reserve. This was the screenshot's spending-limit failure, distinct from the
  hard 90-second, four-response and cumulative audio/frame limits in code.
- Paid and already-sponsored accounts now use existing Premium capacity/topups
  and existing server-owned exemption rules. Call records AI_CALL estimated
  usage and reserves/settles owned top-up debits under existing user locks.
  Insufficient real account capacity blocks admission and renewal. No plan,
  price, invoice, purchased credit, sponsorship rule, key or environment setting
  changes. Non-entitled accounts retain the existing finite trial funding gate.
- A live Call renews its accounting envelope before the old time/audio/response
  boundaries, without disconnecting the conversation. Conservative estimates
  remain retained after possible dispatch; undispatched End releases only its
  own hold. Repeated End cannot double debit. No historical trial row is reset.
  Native/trial history still counts under its original policy. The estimates
  are internal accounting, not a supplier invoice or a verified currency quote.
- Consumed audio frames are pruned using monotonic acknowledged cursors. Input
  backlog, output backlog, protocol validation, authentication, account disable,
  campaign revocation, CSRF, ownership, concurrency and logical-start rate limits
  remain enforced. Losing the client still closes the server socket.
- Call requests the provider's supported context compression and resumption.
  Only a provider expiry warning followed by a fresh resumable checkpoint can
  trigger one handoff. Unsent input is paused and bounded. Accepted microphone
  or playback audio is never replayed; ordinary network errors do not retry.
  Repeated premature warnings or an unsafe/failed checkpoint end visibly.
  End fences late sockets and callbacks and closes microphone/audio transport.
- Fullscreen Call keeps status, optional live captions, actionable errors and
  the mobile-visible End control. Persistent descriptions, provider/privacy
  paragraph and obsolete session-limit paragraph are removed.

Official protocol reference checked 2026-10-16:
https://ai.google.dev/gemini-api/docs/live-api/session-management

## Focused validation

- Network-blocked `test_kilas_ai_call.py`: 26 tests pass, including metered
  continuation, exhausted trial vs account capacity, top-up reserve/debit,
  cancellation, retained historical spend, fresh resumption and bounded frames.
- Network-blocked `test_kilas_home.py`: 18 tests pass.
- Node Call lifecycle/player/real-template DOM and Home viewport: 33 pass.
  Synthetic viewport heights include 240px, 350px, 390px and 740px; all four
  supported locales retain the short placeholder and correct icon order.
- Scoped Ruff E9/F, JavaScript syntax, locale JSON and git whitespace checks pass.
- No browser-based tests, microphone capture or paid provider QA. Synthetic
  socket/DOM/audio-clock evidence does not establish physical Android layout,
  actual provider resumption, audible continuity, latency or audio quality.

No Translator, Voice Over, Finance, pricing, public site/Netlify, shared provider
implementation or schema changed. Only the existing Client Hub service requires
deployment; bot and automation services do not.

## Release evidence

Production preflight (read-only): 47 native journal rows, retained estimate
9,900,000 microUSD, native fingerprint `d8d7f6c7d5747d454c7390d10b856fbc`;
zero account AI_CALL usage rows. No call or reservation was created by QA.
Exact release commit, Render deployment status, served asset hashes and the
post-release journal comparison are recorded separately after deployment.
