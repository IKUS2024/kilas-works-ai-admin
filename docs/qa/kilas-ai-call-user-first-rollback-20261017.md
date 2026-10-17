# AI Call user-speaks-first rollback

Requested on 2026-10-17 at 07:59 UTC, with a follow-up request for natural,
knowledgeable speech and preserved search. This release targets only Call.

## Restored behavior

Targeted reversions of greeting/barge-in commit `511af5b` and diagnostic merge
`ad8b543` restore the Call audio implementation from `8ffa866`. The repository
was not reset. Automatic greeting, forced initial guiding question, client
opening handshake, and the diagnostic page/modules are removed. No user data
was deleted. The earlier search repairs remain byte-for-byte unchanged.

The previous provider `NO_INTERRUPTION` policy and browser playback microphone
handling are restored together, as requested by the rollback to that default.
The person speaks first; Kilas answers; after playback drains, the microphone
resumes for the next question. End, output jitter buffering, funding, duration
behavior, PCM encoding, previous input conditioning and session resumption
remain the earlier implementation. This is an explicit restoration of the
previous flow, not a newly inferred echo correction.

Three short system-policy sentences implement the user's latest speaking-style
request: direct natural short answers, relevant facts/examples, uncertainty
calibration and context-aware clarification only when needed. They add no
opening or compulsory follow-up. Model, voice, output cap, provider setup,
search tools, source/freshness validation, search timeout and one-tool cap are
unchanged. Naturalness/semantic quality is a policy change, not a verified new
model capability.

Call-only module URLs are cache-busted for this rollback. Startup reporting
identifies configured contract `user-first-v1`, `automatic_opening:false` and
the preserved search contract `activity-public-fx-v3-capped-complete`.

## Actual checks

- 104 Python Call tests passed, including four new rollback regressions:
  connected idle session sends setup only, no opening/diagnostic endpoints,
  previous audio policy and context-aware prompt, and preserved search contract.
- 41 frontend tests passed. New coverage verifies no automatic opening request,
  preserved initial microphone bytes, and playback only after a provider frame.
- Actual Chromium used synthetic getUserMedia, AudioWorklet, CallCapture,
  CallSession and CallPlayer with local injected transport and no provider IO.
  It observed zero automatic-opening requests, no output before the synthetic
  reply, successful playback drain, microphone resumption for the next question,
  and zero post-End uploads. Results are in the adjacent browser JSON.
- The engine, capture, public-search adapter, response-contract normalizer and
  shared tool helper are byte-identical to `8ffa866`. Beyond the targeted
  reversions, runtime differences are the three prompt sentences, startup
  contract metadata and module cache URLs.
- Production preflight found zero recent active Call operations. No service,
  environment, provider/model, quota, balance, pricing or unrelated product
  configuration was changed. No paid provider test or private-audio inference
  ran. Finance, Translator, Voice Over, Group and Creative Services are untouched.

## Limits

Physical Android audio and real-provider semantic quality remain unverified.
The earlier real public-search smoke did not establish a successful sourced
news answer. This rollback preserves its subsequent code correction and honest
failure safeguards; it does not claim that real-provider search is fully
verified or that all audio complaints have been resolved.
