# AI Chat Call — 2026-10-16

## Direction contract

THESIS: One person talks with Kilas to discuss questions, ideas and problems.
The voice conversation is separate from translation and from group meetings.

OWN-WORLD: Inherit the existing chat typography, restrained colors, logo and
phone controls. Scope new styles to AI Call; preserve Translator and VoiceOver.

STORY: Call sits beside Send. Pressing it opens a fullscreen call, prepares
audio and requests microphone permission. Connecting, listening, speaking and
failure states are explicit. End immediately releases local audio and requests
server cancellation. Leaving/backgrounding also ends the call.

FIRST VIEWPORT: Full viewport, compact title/status above the Kilas identity,
optional response captions, red End below, privacy and finite-session notice.
Keep the controls reachable within mobile safe areas and restore focus on exit.

FORM: An operating surface using the incumbent call pattern, no global redesign.
Use a native dialog for protected focus. Screenshot bytes were unavailable;
placement follows the user's explicit instruction. No screenshot-dependent claim.

FINISH: Browser-free DOM/lifecycle, protocol, ownership, budget and original
Translator/VoiceOver regression checks; exact tested source deployed with actual
runtime readiness. Android audible quality remains an external verification gap.

## Official model and transport

Use the stable conversational `gemini-3.8-live`, not the translation-only model.
The API key remains server-side in the existing Google WebSocket header flow.
No tools, grounding, provider fallback, token generation or automatic reconnect.
System instructions support discussion and answering in the speaker's language.
No transcript or raw PCM is persisted; bounded in-memory audio is cleared on End.

Sources checked2026-10-16:
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live
- https://ai.google.dev/gemini-api/docs/live-api/capabilities
- https://ai.google.dev/api/live
- https://ai.google.dev/gemini-api/docs/pricing

## Existing funding, no new allowance

Call has its own opt-in flag and immutable campaign metadata. The policy parser
reuses existing verified Gemini funding while the Translator flag remains OFF.
All `gml-%` history, including previous unknown/cancelled dispatch charges, counts
against the same lifetime cap under the existing global admission lock. Each
physical Call retains the existing conservative reservation after any possible
dispatch. An undispatched End alone releases its reservation. No history reset,
cap expansion, new key, purchase, automated paid QA or automatic paid renewal.

Bound each connection to90s,60s total input PCM,60s total output PCM and at most
four responses with1024 output tokens per response. Session context starts empty,
with no chat history/tool payload, and cannot resume. Public model audio prices
are lower than the retired translation model, but reservation accounting remains
an internal conservative envelope, not a supplier invoice or FX guarantee.

## Preserved behavior

The restored ElevenLabs Translator at7b708f4, including early-clause translation,
two-second gate, Kilas voices and existing VoiceOver implementation is unchanged.
AI Call is a separate route, client, registry and ledger operation namespace.

## Validation and release limits

Local validation:29 offline Python suites (including16 new Call cases),289
Node tests (including15 Call lifecycle/real-template DOM cases), production
CSRF/security foundation tests, Python syntax, locale JSON, workflow YAML and
Ruff E9/F. All provider sockets and microphone inputs in tests are synthetic.
PostgreSQL CI additionally races a Call and native reservation for the same
last shared allowance. No automated test dispatches a paid provider request.

An additional legacy `test_kilas_ai_agent.py` assertion rejects the word
`Connections` anywhere in the page, including the existing localization data.
It also fails on the unmodified7b708f4 baseline; no unrelated UI change is made.

Worker readiness only verifies existing configuration and SELECT-only ledger
gates. It does not establish this account's model availability or real-device
microphone, audible quality, first-audio latency or mobile layout. Those remain
unverified without a legitimate user call. No browser-based QA was performed.
