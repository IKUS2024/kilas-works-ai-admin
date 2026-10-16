# ElevenLabs Translator restoration — 2026-10-16

The owner explicitly requested restoration through LIVE at 08:39:26 UTC. Base
main is 6e4a0a01e7ac8c3025fd46f7143b45d51c57c493. This is a scoped provider
selection, not a repository rollback. VoiceOver and unrelated fixes stay intact.

## Retained implementation and selection

History identifies the last pre-Gemini-pilot tree as
28aade72b83705b126d6748d47ccbe06cecb7cda (parent of fc040b8). The latest
ElevenLabs pipeline change before the pilot was a37ba701dd0f629530ded0ef8ca823404c2e576a:
committed-clause work while speaking with complete final reconciliation. Those
files already remain in current main; no old app/template blobs are restored.

Ordinary Translator defaults to ElevenLabs. Gemini default navigation now needs
the explicit KILAS_TRANSLATOR_PROVIDER=gemini selector; it can no longer replace
Kilas voice selection merely because its rollout flag is on. Production selection
is elevenlabs and KILAS_LIVE_GEMINI_ENABLED=false. All other native code,
configuration, accepted cost history and saved records are retained. Existing
owned sessions still require their user's explicit End; navigation cannot end or
rewrite another session.

The approved server-owned Kilas Male/Female aliases still resolve saved voice5
and7 belonging to owner9. A read-only production query confirmed both exist and
have valid provider identifiers; identifiers were not returned. The established
Scribe realtime -> Luna translation -> ElevenLabs multilingual-v2 path, native
Kilas voice settings and whole-utterance TTS remain unchanged. Ordinary VoiceOver
uses its own existing settings.

## Bounded latency work

Before this change RealtimeInput started admission on the first capture callback
but held PCM until its1s buffer filled. The first200ms capture frame now queues
immediately behind the SAME admission request. All later PCM retains1s batching
for serialHTTP throughput. There is at most one extra HTTP chunk per utterance;
no new STT connection, additional lease, repeated audio, new paid translation
request or automatic regeneration is introduced. Long350ms serialHTTP synthetic
tests still deliver every byte and exact final tail.

Existing overlap remains: provider-acknowledged complete clauses can translate
during speech, at most two clauses, with incomplete text retained for final
reconciliation. TTS uses the complete final utterance once. Playback waits for
the existing2000ms silence gate, capture flush, final commit and whole playable
output; it never plays a draft prefix. Existing End, bounded player recovery,
language-pair validation, credit checks, quota, revocation and tenant fences stay.

The last eight observed ElevenLabs completed logs (05:25–05:34 UTC) show backend
3689.4–9243.7ms from finalization, realtime-finalize160.2–509.5ms and one or two
overlapped clauses in seven of eight turns. These are historical server timings,
not a measurement of this release or Android first-audible output. Removing up
to800ms of local first-frame buffering does not guarantee an equivalent reduction
in the final wait. Two seconds means silence detection, not full response time.

## Access, safety and verification

The existing fixed-end authenticated sponsorship remains authoritative. No role,
subscription, quota, STT/provider cap, approval marker, key, project, billing mode
or provider voice is expanded or replaced. Gemini budget records are preserved
separately; its remaining allowance is not an ElevenLabs credit balance. No paid
automated QA, browser, new microphone capture or production history deletion.

Offline restoration regressions exercise real Flask owner/member admission for
both aliases, matching realtime mode, foreign-session End denial, unchanged old
native session rows, selected/default page navigation and rejected voice/pair/
consent/CSRF/funding. Input tests prove immediate first frame and exact final
bytes. Whole-output, incremental, transport, account-proof, billing, history and
original VoiceOver regressions remain part of browser-free CI. A SELECT-only
worker report records actual provider selection, owner/nonowner configured
readiness, realtime mode, public voice choices and existing STT cap values.

Local verification passed28 Python suites,274 JavaScript tests, four fresh-HTML
compatibility DOM tests and Ruff E9/F checks. No browser test was run.

Exact test, CI, commit/tree, Render LIVE, runtime readiness and read-only ledger
results are recorded in the cloud release-evidence artifact. No live audio
quality, intelligibility, Android playback, first-audible timing or demo-ready
claim is made. Direct cloud HTTP has previously been blocked by CONNECT403;
any repeated health attempt and its actual outcome are recorded separately.
