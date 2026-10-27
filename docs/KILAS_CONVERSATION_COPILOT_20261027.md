# Conversation Copilot — cloud implementation

The owner approved a voice-input-only Copilot as the primary experience, keeping
AI Chat hidden and recoverable, Finance and Creative Services available, and
continuing through the existing Client Hub production deployment. No desktop
machine, new credentials, subscription changes or destructive migrations are used.

## Behavior and preservation

`/products/start` and `/kilas-ai` render Copilot. The microphone starts OFF, with
no transcript or detected language. A checked processing-consent control and an
explicit tap request browser microphone permission. The second tap stops capture
and submits one bounded mono PCM16k WAV; no provider is called during capture.
The 60-second limit stops capture locally and waits for an explicit process tap.
Results stream as clearly labelled AI suggestions. New recording always requires
another tap. There is no typed conversation composer, TTS, phone integration,
native app or overlay in Copilot.

Permission denial, missing device, silence, empty transcription, invalid audio,
quota denial, network failure, cancellation, pending permission, duplicate
submission, interrupted streams, navigation, hidden tabs and unmount/page exit
are handled without automatically resubmitting or rearming the microphone.
Failed/incomplete text and cancelled transcripts do not enter visible history.
Cancellation tombstones fence requests arriving later or on another worker.
Active operation state expires after four minutes; owner concurrency is bounded.

Translation starts OFF. OFF renders only suggested replies, including history.
ON reveals full language names, heard speech and its translation, plus the
suggested reply and its translation. Translation never selects the primary reply
language: it follows the latest intelligible spoken utterance. Older turns made
with translation OFF show that no translation was created, without starting a
new paid request. Prior suggestions are explicitly unconfirmed in the prompt;
they cannot establish the owner's personal facts, qualifications or commitments.

Existing account-owned threads hold only new Copilot metadata and completed
suggestions. Raw WAV bytes are transient and never written to the database.
Legacy Chat implementations, send handlers, routes, historical messages, files
and account authority remain intact. The legacy primary page remains directly
addressable with `?legacy=1`; `KILAS_COPILOT_VISIBLE=false` reverses navigation.
Neither mechanism has a visible primary UI link. Default sidebar history and its
pagination expose only Copilot sessions. Library downloads retain their existing
handlers; its legacy chat-reuse shortcut is hidden. No historical rows are purged.

Copilot, Translator and Voice Over share the simple orange active tool pill and
existing drawer/Profile shell. Translator/VO capture, processing, billing and
core controls are unchanged. Profile starts closed and retains Credits & Usage,
App Language and Sign out. Finance implementation/routes/styles/ledger have no
changes. One Finance shell test seeds Copilot session history to reflect the
approved visible-history choice while preserving ownership and read-only checks.

## OpenAI and metering

The existing server-owned OpenAI key is used only server-side. Speech uses the
existing documented `gpt-4o-mini-transcribe` identifier and JSON transcription
contract. Text uses exactly `gpt-6-luna`, low effort and 1,024 completion tokens,
through the existing OpenAI streaming adapter. There are no tools or expensive
fallbacks. Official model/API documentation was inspected on 2026-10-27:

- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe
- https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create/

The legacy transcription provider's disabled funding guard and historical QA
grants are untouched. Copilot has a separate admission path through the existing
SMART account reservation, without a profile override or allowance increase.
Its existing USD 0.18 conservative estimate covers one bounded STT request, one
reply and optionally one bounded translation request. It is an internal capacity
estimate, **not measured supplier cost or a new customer invoice price**.

Dispatch intent settles this estimate durably before provider IO. A worker crash,
timeout or cancellation cannot erase it through normal PENDING-row expiry.
Existing topup settlement retains the dispatched estimate on failures too. Only
the status is promoted after a completed result; plans, balances, invoices,
exemptions and allowance limits are not reconfigured. Insufficient capacity
rejects before transcription. Real audio and paid-provider tests are NOT RUN.

## Evidence

- `test_kilas_copilot.py`: 19 offline tests PASS, real revocable auth/CSRF,
  SQLite ownership/preservation, quota admission, durable dispatch, cancellation,
  duplicate prevention, concurrency, context labels and history pagination.
- `test_kilas_copilot.mjs`: WAV framing, split UTF-8/SSE, HTTP/provider errors and
  incomplete response contracts PASS.
- Existing usage: 5 PASS; Finance onboarding shell: 4 PASS; translator language
  contracts: 10 PASS; Voice Over edit: 4 PASS. Each file runs in isolation.
- Chromium synthetic microphone/provider QA: 360/768/1440px; idle/start/explicit
  stop, no calls before stop, no rearm, translated/nontranslated results/history,
  consent, permission failure, pending permission cancellation, in-flight cancel,
  drawer/Profile, navigation cleanup, Translator/VO controls and no overflow PASS.
- Python compilation, JavaScript syntax and diff whitespace checks PASS. This is
  a Flask/Jinja/plain-JS application; package.json has no application build/lint.
- The original Home/sidebar compatibility fixture explicitly selects the retained
  legacy visibility mode. Its existing assertions and engine coverage remain;
  the Copilot suite separately checks the default primary UI and hidden legacy
  entries. This prevents obsolete visible-Chat expectations from redefining the
  owner's approved default experience.
- Existing `test_kilas_ai_chat.py` direct run: 5 failures/8 tests. Identical 5/8
  failures reproduced on untouched `1a529a13`, from obsolete auth fixtures.
- Existing translator consent suite: 3 failures/4 tests. Identical 3/4 reproduced
  on untouched `1a529a13`; its mock rejects existing language-model discovery.
  Neither suite is claimed green or weakened by this change.

Local logs: `/tmp/kilas-copilot-*.log`. Synthetic browser screenshots and report:
`/tmp/kilas-copilot-browser/`. Dedicated CI: `kilas-copilot-qa.yml`. No physical
phone, Safari, real microphone or paid API acceptance is inferred from mocks.

## Visual and release limitations

All six supplied Library IDs resolved to image transfers, but no original bytes
could be downloaded in this executor. The supported helper returned exactly
`library file transfer failed: download failed` (exit 1), including a bounded
retry to explicit `/workspace/copilot-references-retry/` and
`/workspace/copilot-owner-reference-retry/` destinations. No permission denial
was reported. The executor inspected its own Chromium output, not original
reference pixels. Original-design comparison is delegated back to the parent,
which has inspected the originals. No pixel-match claim is made here.

Baseline remote main and Render LIVE: `1a529a13ba83cff1341add371af3b5632d52cb27`,
Client Hub `srv-da7ti2psrm7s73dh9i2g`, workspace `tea-da34t2gu01pc73ft7uf0`,
automatic deploy OFF. Existing startup logs confirm OpenAI key presence only;
they do not prove model access or paid connectivity. Publication, exact-commit CI
and terminal Render LIVE verification are pending this checkpoint.
