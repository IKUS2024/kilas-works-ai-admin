# Kilas AI owner revisions — 2026-10-11

Owner authorized scoped implementation, direct main push and existing Client Hub production deploy. No Trading, Finance internals, billing rules, provider plan purchases or new credentials are in scope.

## Verified starting state

- Local source and remote main: `1a4d3d1fdbafed3b21f5d7cecd9a0d08b2a98696`.
- Client Hub `srv-da7ti2psrm7s73dh9i2g`, workspace `tea-da34t2gu01pc73ft7uf0`: LIVE deploy `dep-db5ruru7bikc73dru420`, same SHA. Auto-deploy remains OFF.
- Read-only production voice inspection verified the existing `irvan Voice` and `putri voice` records and their exact provider IDs privately. The branded aliases resolve those exact saved records server-side; personal names/settings are unchanged. No voice was cloned.

## First release candidate

1. AI sidebar structure: New Chat, My Library, existing owned conversation history, profile at bottom. No Finance or Projects entry in this sidebar. Exact reference appearance is blocked below.
2. Feature order: AI Chat, unavailable Translator indicator, Voice Over, existing Finance entry. Voice Over has no conversation sidebar and retains feature navigation/profile access.
3. Profile menu: Account with current email, Subscription, App Language, Logout. Existing account, language and subscription handlers are reused.
4. Empty chat text is exactly `How can I Help you?`. Exact supplied K logo is blocked; no substitute logo was generated. Existing conversations remain intact.
5. Existing composer appearance, keyboard handling, message bubble sizes, typography and copy/font controls are preserved. Exact composer reference restyle is blocked.
6. No separate Video Plan feature tab. AI Chat reuses the existing director's creative instructions for concepts, timed storyboards, continuity and production prompts. Existing video routes/results remain accessible through My Library; no stored plan is migrated/deleted.
7. Video ke Naskah removed from ordinary Voice Over UI. Audio balance/purchase controls hidden on the workbench and subscription/account entry. Underlying credit reservations, accounting, provider costs, checkout handlers and privacy policy remain.
8. Kilas Male/Female are aliases for the privately verified existing voices; Male is default. Missing Male is shown unavailable rather than silently mapped to another provider voice. The personal library and its settings are retained.
9. Naskah dictation code: explicit processing consent, browser mic permission, start/stop/cancel, existing ElevenLabs STT adapter and existing finite campaign ledger, direct text append to editable Naskah, undo guarded against later edits, no transcript box, no automatic TTS. Gate remains OFF; no live provider success is claimed.

## Local evidence

All paid transports are mocked/synthetic. Passed: revisions 6, Audio 52, existing STT/video budget backend 18, personal voices 17, unified Chat 24, Home 15, automatic Search 10, Chat 8, foundation 5, Finance boundary 4, public privacy pages 2. Node recorder/dictation: 9 passed.

Chromium plus local Flask: responsive revisions passed at 320/390/820/1440 px, covering old/new chat, reload/back/forward, library, profile/language, audio navigation, default/selected branded voice and synthetic dictation append/undo/cancel/error without real microphone/provider access. Existing composer-focus QA passed at 320/360/390/820/1440 px, including controlled keyboard viewport, submit blur, Shift+Enter and Stop. Existing chat-bubble browser QA passed (long Markdown/URLs/code/tables/files/copy/streaming/keyboard/reload). Python compile, changed JavaScript syntax and git diff checks passed.

Local logs: `/tmp/kilas-*.log`; browser evidence: `/tmp/kilas-revisions-browser/verification.json` and existing QA output directories. These are local evidence, not production browser evidence.

## Exact blockers and limits

- All eight Library identities resolved successfully, but supported local materialization failed for every signed transfer. One fresh preparation/helper retry also failed; no readable local reference images exist. No guessed URL, raw download bypass, replacement logo or claimed reference match.
- Public production HTTPS request failed with proxy `CONNECT tunnel failed, response 403`. A Render LIVE SHA proves deployment state, not successful production browser/HTTP acceptance.
- No production STT campaign rows exist. Existing feature/campaign caps/expiry/price-version admission is required; broad owner permission supplies no new paid-test budget. No flag, allowance, overage, plan or balance was changed.
- Provider keys are not available to this cloud shell. ElevenLabs account/model support and actual OpenAI Luna model access cannot be verified here. Existing server configuration selects `gpt-6-luna`; this is a configured model name, not evidence of current account support. No new model ID is invented and no provider activation is claimed.
- Live Translator is the final stage and is not exposed as available. Its paid end-to-end verification and exact orb reference are not yet satisfied.

Costs incurred by this task: no paid provider calls, clones, top-ups, purchases or overages ($0).

## Release evidence

Pending remote main/CI/manual Render deploy verification for this candidate. A push alone is not a production release.

## First release regression follow-up

Candidate `5a8a263560c0c30596e158198c9d5e775cba3590` passed the new revisions workflow (`38162918261`). Existing CI exposed retired UI assertions and two regressions: audio polling dereferenced the hidden balance element, and removing the video upload partial disabled archived audio reconstruction. Both are fixed; reconstruction controls appear only for the retained owned history action, with the video upload UI absent. Profile language controls now fit narrow drawers. Tests now enter archived Video Plan/upload translation routes directly, select personal voices explicitly, and check hidden purchase UI while retaining backend accounting tests.

Local follow-up: 124 backend tests and 326 subtests passed; 59 isolated content tests passed (1 optional skip, 5 browser cases excluded in that invocation). Responsive Home, canonical chat, saved sidebar, revisions dictation, archived video results, Audio downloads/Edit/Bantu AI/error controls and legacy reconstruction passed. Paid calls remain zero. Exact references still unavailable. The exact signed-download transport status was not preserved in the execution record; Library preparation returned no unavailable items and no permission-denied response. Repository inventory has only the existing `kilas-logo-login.jpg`, not supplied `1000327810.png`.
