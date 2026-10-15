# Live Translator: translation during speech

2026-10-15. The owner authorized implementation and direct main/live deployment,
cancelled paid QA, accepted normal configured API charges and requested enduring
availability. The previous proposed US$0.10 QA allowance, pilot dollar limits and
pilot expiration are **not runtime restrictions**. No new subscription, key,
purchase, permission or account billing configuration is introduced.

The old realtime relay streamed STT while speaking but waited until final input
before its first translation. It now allows at most two additional manual STT
commits on the same connection, after at least three seconds of segment audio
and either an internal quiet boundary (600 ms, existing .015 RMS threshold) or
an unchanged sentence candidate (400 ms). The normal two-second silence endpoint,
voice detection, minimum capture, 20-second safety commits, total input/queue
limits and complete final PCM flush remain intact. A short utterance remains
valid and may follow the existing single-final path.

Only a matching provider committed-transcript ACK can launch translation. An
interim candidate never launches a paid text call itself. Complete clauses up
to 1200 characters are translated once with bounded immediately previous
source/translation context. There are at most two clause requests per utterance,
one in flight, with deterministic per-clause keys and the existing account
usage reservation, proof, funding and cancellation checks. The full prefix is
not translated repeatedly. Capture/upload can continue during clause work.
An incomplete ACK can be combined with the next committed ACK before its first
translation; no already translated prefix is repeated. Large clauses remain
intact for final processing. Queued optional
work is discarded when final input arrives; its source stays in the final text.

At the end, the authoritative complete source, including the last words, is
checked against cached clause source. One strict final JSON reconciliation may
retain consecutive complete clauses and replace everything after them. It may
replace every clause when later context changes meaning, numbers, pronouns or
negation. It cannot keep a changed source/direction or silently omit an entire
untranslated tail. A single draft matching the complete final source exactly
can be reused without another text call. All other cases use at most one final
call, with original model/low reasoning/full output budget. No failed/uncertain
paid call triggers an automatic retry or alternate generation.

Draft waiting after final input is bounded to 12 seconds; each running clause
has a 30-second event-fence deadline. Existing network read deadlines remain
finite. End aborts the owned relay/work, clears RAM drafts and fences late
results. A response can settle dispatched cost after cancellation but cannot
publish audio. Translator-only settlement conservatively retains the existing
reserved estimated text cost when a dispatched stream supplies no trustworthy
usage, instead of recording a free unknown call or manufacturing token counts.
Shared Chat/Finance billing code and existing account budgets are unchanged.

One complete validated final text is sent to one whole-utterance TTS request:
same saved voice, `eleven_multilingual_v2`, stability 0.4, similarity 0.75,
style 0, speaker boost false, speed 1.0 and automatic normalization. The complete
MP3 is measured and accounted before session publication/playback. No audio
prefix is spoken over the user and no clause MP3s are concatenated. Mic capture
resumes after complete playback. Existing bounded playback recovery remains.

New source/drafts and translated/audio outputs stay in bounded owned RAM only;
no transcript/draft/audio database or file persistence is added. Existing
session-output TTL/End/next-turn handling, owner/language checks, soft-hidden
archives and accounting metadata remain. No migration or history deletion is
required. JSON prompt bytes are bounded to 60000; existing 4000-character source
and output limits and full model output-token ceilings stay in force. These are
technical input/work bounds, not the cancelled proposed dollar caps. Normal
runtime cost can increase by up to two extra text calls; actual token/account
charges depend on the utterance and existing account configuration.

`KILAS_LIVE_INCREMENTAL_ENABLED` defaults to true inside the already gated
realtime Translator path. Setting it false restores new turns to the existing
serial path without a paid retry or session/data reset. There is no pilot
expiration. Startup logs only fixed configuration; new turn diagnostics report
numeric early commits, clause count, provider/wait times and exact reuse, never
source/draft text, audio, owner IDs or credentials. Incremental provider duration
can overlap speech and is not an extra serial interval to add to backend time.

Verification uses disposable SQLite, synthetic PCM/socket/provider streams and
real local MP3 measurement with all external networking blocked. Eighteen new
tests cover before-end clause work, serial/deduplicated/disjoint requests,
continued complete PCM input, final tail/revision/language validation, exact
reuse, End/late callbacks, bounded wait, skipping queued work, existing quota
denial, conservative unknown-cost settlement and RAM-only complete output.
Existing core, realtime, whole-output, segments, transport, SSE, flow and
session-output Python suites plus 191 Node Translator tests also pass.

No paid provider QA, new microphone capture or real Android playback evaluation
was run. The prior recording's parent-supplied energy/frame timing was about
2.12 s endpoint + 8.00 s processing + 0.73 s text-to-output = 10.85 s; this is
not a post-release measurement. Continuous speech without a suitable boundary
may gain little. A final reconciliation still has model startup latency; smooth
prosody, complete semantic fidelity and actual first-audible improvement require
real use and are not established by synthetic tests or energy inspection.
