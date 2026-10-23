# AI Call modes and characters

Baseline: `76520a9145f43b5d2ff271a450844d685181bd38` (latest main, including zoom fixes). Scope: AI Call only; no Finance, Translator, Voice Over, Creative Services, credentials, billing, authentication, permission, model or provider-flag changes. The shared base template changes only the Call CSS cache key. Locale entries are additive Call UI copy.

Before admission, choose Normal (default), language practice, roleplay, or explicitly consented Roast / Fierce. Friendly, casual and firm characters are available outside roast. Roast requires its matching character and a boolean consent; closing/reopening clears consent. Language practice offers ten target/explanation languages and three levels, corrections and conversational practice. Roleplay supports interview, airport and customer scenarios.

Server validates every enum, rejects unknown settings, malformed JSON and non-boolean consent before claiming budget. Each Call owns validated settings; initial and resumed provider setups compose the same base plus mode prompt. Learning removes the initial-language continuity rules in favor of the selected target/explanation languages. Search and substantive answers remain available. There is no persistent cross-call learning history.

Stop audio / Normal immediately uses the existing cancellation path to abort capture/polling, stop scheduled audio nodes, close the audio context and end the owned server session. It resets mode/character/consent and offers explicit Start for a new Normal call; context from the ended call is not carried over. No automatic paid replacement session. Network loss can delay server acknowledgement; existing watchdog and metering remain authoritative. Spoken barge-in is not implemented: playback still sends silence to avoid echo.

Roast prompt permits casual coarse profanity such as anjing/bangsat and natural other-language slang only for the consenting person. It forbids threats, protected-group hate and dangerous encouragement and requires dropping roast on a stop request. Provider safeguards remain; specific words, consistent angry prosody and actual voice quality are not guaranteed or tested.

Validation (local, synthetic sockets/microphone; no paid provider calls):

- 61 JavaScript lifecycle, PCM, playback, sources and rendered DOM tests pass (jsdom 26.1.0, matching CI).
- New strict settings/route/resumed-wire tests: 5 pass, 10 subtests; offline repository runner passes.
- Existing Call lifecycle Chromium scenarios pass: normal/stalled, permission denial, missing worklet and unsupported dialog.
- New Chromium mode flow passes at 320x640, 390x844, 768x1024, 1440x900 and 480x300, including 2x pinch, explicit consent, settings POST, immediate Stop/Normal, and fresh language-practice start.
- Existing Chat zoom suite: 57 checks pass, including 2x/3x pinch, desktop reflow, large text, composer placement and busy-call guard.
- Broad Python run: 173 passed +176 subtests, five failures. All five also reproduce on an isolated untouched baseline: three `test_kilas_ai_call_search_smoke.py` cases hit its existing 8192-byte setup fence; two `test_ui_english_consistency.py` cases expect retired Translator select markup. No smoke cost fence or out-of-scope Translator test was weakened.

Deployment status is recorded in the task result after verifying the real Render revision and public assets. No production AI Call is started for verification.
