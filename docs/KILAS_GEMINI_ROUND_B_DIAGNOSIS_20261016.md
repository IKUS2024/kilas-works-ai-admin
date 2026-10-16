# Live Translate round B: offline diagnosis, 2026-10-16

## Proven observations

Both separately approved round-B calls used the same native code as main
6121854. ID→EN / EN→ID respectively reached first backend PCM in 3425.1 / 3133.5
ms, before input finished. These are server observations, not audible latency.
Each accepted exactly 30,000 ms of output, 1,440,000 PCM bytes, 240 client frames.
The calls settled in 33,594.4 / 33,208.2 ms. Both had zero generationComplete and
zero turnComplete events; both sent audioStreamEnd. Neither final source nor
translated transcript contained the expected final water/air word. Thus the
last tail was not verified. Backend End was 205.1 / 98.9 ms, after which output
access was blocked. None of these numbers proves Android playback quality.

The QA child explicitly sets `OUTPUT_BYTES = 30 * 48000`; normal native code
uses 90 seconds. `Relay.receive` formerly raised the same ValueError for valid
PCM exceeding this local cap and for malformed PCM. That explains the exact
30-second accepted-output boundary and the misleading gemini_response_invalid
classification. It does **not** prove what the rejected/unreceived audio contained
or why either transcript missed its final word. This release reports
`gemini_output_limit`, retains valid accepted bytes and existing settlement, and
records numeric sent/accepted/rejected packet counts. It does not raise QA caps,
lease duration, paid funding, or automatically retry.

## Input and pacing

Offline WAV inspection confirms both inputs: mono signed PCM16, 16,000 Hz,
240,000 samples / 480,000 PCM bytes / exactly 15,000 ms. SHA-256:

- ID: `3751b3b407c81b5f6398f1dcccc4ad21fbaffda3912e51f6aabe12f760714fc9`
- EN: `955455943bd45b9ca13b375030f75b49e9515d477ab26a65ed3e6731df3e0e8a`

10-ms RMS windows with an amplitude threshold of 100 put the last above-threshold
window at 14,350 ms (ID) / 14,060 ms (EN), leaving about 650 / 940 ms below
threshold. These are signal measurements, not speech/VAD labels. Peaks are
24557 / 32517; overall RMS is about 3164 / 3161. The fixtures are not 30 seconds
of source audio or empty recordings.

The QA feeder sent 30 batches of 16,000 bytes at average real-time pacing;
recorded input wall time was 15,000.1 ms. Relay splits each batch into five
3,200-byte/100-ms messages without pacing between those five messages. That is
150 provider messages, bursty at 500-ms boundaries. No per-send timestamps were
saved in round B, so exact network pacing/jitter cannot be reconstructed. New
numeric diagnostics count successful sends but do not fabricate old timings.
No pacing change was justified by the available evidence.

## Continuous translation and missing final evidence

[Google's dedicated translation guide](https://ai.google.dev/gemini-api/docs/live-api/live-translate?hl=en)
distinguishes continuous interpretation from turn-based agents and specifies
16-kHz input / 24-kHz output. Its linked
[official Python example](https://github.com/google-gemini/gemini-live-api-examples/blob/3bcae1162d1bc6955672153310e4f84eba6621ff/command-line/python/translate.py)
sends paced 100-ms chunks, then waits four seconds and cancels receiving; it
does not establish a guaranteed final EOF marker or prove every tail complete.
The [general API reference](https://ai.google.dev/api/live) defines audioStreamEnd
for automatic activity detection. It does not establish a final-tail guarantee
for this continuous model. Injecting clientContent.turnComplete could interrupt
generation; it is not an evidence-based repair.

The product's current success gate still requires a terminal post-EOS turnComplete;
this may not fit the model's continuous contract. Missing that marker is an
unconfirmed tail, not proof that Google returned malformed data. Keeping a
bounded visible failure is safer than declaring success from silence, usage,
generationComplete alone or socket close. The UI now states this unresolved
limit instead of promising that Finish delivers the last word.

Output PCM was RAM-only and explicitly cleared by cleanup End. Read-only
production SQL confirms jobs 176 and 177 have NULL result_content, source_content
and original_script. They record 30,000 ms of valid accepted PCM; their parent
turns failed. Saved transcripts, usage events and event counts remain in the
cloud evidence JSON, and synthetic source WAVs remain in Git. No saved output
WAV/PCM is available to listen to or analyze for repetition/silence. Repeated
speech, padded silence or a provider sample-rate discrepancy remain hypotheses.
350 output tokens per call correspond to about 14 seconds at the published
25-token/second rate, whereas accepted PCM spans 30 seconds; that discrepancy
needs an actual saved output sample, not another inferred explanation.
`all_generated_pcm_read` was a misleading historical metric: it only compares
accepted bytes against fetched bytes. A new `all_accepted_pcm_read` names that
fact accurately; neither proves the missing tail was received.

## Spending and release state

[Official pricing](https://ai.google.dev/gemini-api/docs/pricing?hl=en): input
USD3.50/million audio tokens and output USD21/million; approximately USD0.0053
per input minute plus USD0.0315 per output minute. Equal one-minute input/output
is about USD0.0368. Round B reported 350 input + 350 output tokens per call,
USD0.008575 each / USD0.01715 together by that tariff. This is a token estimate,
not the supplier invoice. The local ledger retains USD0.40 across all four
historical dispatches, with zero unsettled operations. Zero-cost durable QA
markers explain why ledger row counts exceed paid connections. No refund is
assumed and no extra inference was run for this diagnosis.

The owner subsequently approved **total Rp500,000 including previous usage**,
continuing owner-only use and no auto-top-up. Standing policy is prepared without
QA expiry and includes every gml-campaign's retained allowance under the existing
PG admission lock. A verified tax/fee-inclusive IDR-per-USD ceiling is required;
no rate or supplier balance is inferred. Existing connectors cannot verify the
supplier invoice/balance, outside-project usage or that conversion ceiling.
Therefore activation remains OFF. This is a specific funding-enforcement gap,
not a request to approve the same Rp500,000 again. No key/permission/subscription
or environment value was changed by this release. The verified owner can view
the locked landing page; POST admission remains closed.

## One future verification, not blind retries

After the funding gap and continuous-stream stop contract are resolved, prepare
one explicitly authorized synthetic run with private, bounded output-PCM capture
and a numeric monotonic event timeline. The capture/export must be in place
before dispatch; do not stream audio into logs or persist real microphone audio.
Use a known final word and at least two seconds of known trailing silence,
record input send times/bytes, EOS, every output byte count/MIME/rate, transcript
events, usage and close cause. Make the QA output cap distinguishable from
transport/format failure; choose a sufficient finite cap once, within the approved
reserve, rather than increase it through paid retries.

Download that one fixture artifact securely and analyze it repeatedly offline:
listen, inspect RMS/silence, repeated-window hashes, true duration/sample rate,
final-word audio and transcript alignment. Report any unverified final tail
explicitly. Then the owner may measure real-device first-audible delay, End and
headset/speaker behavior manually; browser automation remains prohibited. Do not
claim backend mocks or token metadata verify audible output.
