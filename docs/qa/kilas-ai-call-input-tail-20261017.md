# AI Call captured-input tail repair

## Evidence

The 2026-10-17 08:35:44 UTC production close metadata reported 54.8 seconds
accepted and sent, four transcription events (196 characters), three completed
replies, zero interruptions and no search. No error log was returned for that
window. These counts establish dispatch/activity, not accurate recognition.
No private audio or transcript content was retrieved or persisted.

An input-loss race was reproduced in the production browser engine: reply
arrival called `discardPending()`, invalidating already queued microphone POSTs
and clearing the partial input buffer while an earlier POST awaited ACK. With
700ms of captured question audio queued/pending, the old implementation sent
only the initial four fixture bytes instead of the expected 22,404 bytes.
Server accepted/sent counts cannot reveal bytes discarded before acceptance.

## Focused correction

Reply arrival now flushes the captured partial frame into the existing ordered
upload chain. It does not cancel previously captured audio. The obsolete epoch
discard path is removed. Accepted input order, sequential indexes, bounded
backlog, End aborts and no-retry behavior remain intact.

User-speaks-first remains. No automatic greeting, forced guidance, diagnostic
page, prompt edit, provider/model change or sensitivity change is introduced.
The restored playback microphone policy is unchanged: newly captured samples
during Speaking are still represented by silence; this fix does not enable
overlapping speech recognition. Already captured user input is retained ahead
of that silence. Call module URLs are cache-busted. Search adapter, normalized
response contract, server, capture, resampling, conditioning and player sources
are unchanged from `808778c`. No unrelated product changed.

## Actual verification

- The new held-ACK regression failed before the fix: 4 versus 22,404 bytes.
  After the fix all expected captured/conditioned bytes arrived in order.
- All 42 focused frontend tests passed, including existing playback mute/drain,
  next-question, End, framing, bounded queues, PCM and search-source checks.
- Actual Chromium used synthetic getUserMedia, AudioWorklet, CallCapture,
  CallSession and CallPlayer with local injected transport. Holding the first
  ACK through reply onset preserved all 38,400 expected captured/conditioned
  bytes, retained the next question, and produced zero post-End uploads and no
  automatic-opening requests. Adjacent browser JSON contains the raw summary.
- No provider IO, paid test, new credential, private-audio inference, quota or
  service configuration change was performed. Production preflight found zero
  recent active Call operations.

This proves a specific input-loss repair. It does not establish that this race
caused every unrelated reply or verify the phone's actual microphone waveform,
ASR accuracy, conversational semantics, or successful sourced live search.
