# AI Call viewport and Android audio repair

Baseline:3acb79a7f529d760e5596681fc73c4d2c2a23c2b.
Scope:AI Chat Call only. Translator, VoiceOver, text chat, funding caps and
historical reservations remain unchanged. No new paid QA or credential changes.

## Evidence and changes

The global `.kilas-light dialog` selector has greater specificity than the old
`.ai-call-dialog` rule. It therefore replaced Call's max width/height and dark
surface with the regular inset white dialog theme. Call now uses its own ID
selector, resets radius/shadow/max sizes, and follows the visual viewport on
resize/keyboard/orientation events. Its native modal moves directly under body.
An explicit HTML `hidden` plus a closed-state CSS rule prevents an inactive
Call surface from appearing in chat, even before the module runs. Only the Call
button beside Send appears until tapped. End/background/pagehide conceal it and
retain immediate local cleanup and owned server cancellation.

The shared PCM player originally buffers only its first300ms of audio. Once
started, every packet is scheduled immediately. The output polling interval is
250ms, so a delayed delivery can drain that short cushion and leave silence
between otherwise consecutive buffers. A deterministic jitter profile reproduces
a70ms scheduling gap in the unchanged shared player. A Call-only adapter buffers
750ms before starting each answer or recovering an underrun; it schedules the
same PCM on the same audio clock and produces zero gaps for that profile. The
fixture's first start changes from240ms to660ms. This is a buffer/latency tradeoff,
not a real-device timing measurement. Prefill waits at most1250ms; a provider
turn-complete marker releases a short tail immediately. End cancels both timers
and scheduled audio. The original bounded watchdog and60s output limit remain.

Output stays signed little-endian PCM24k. Tests cover native44.1/48k output
contexts: buffer duration derives from24k input, and Web Audio handles device
resampling. Call requests the playback latency hint without forcing a device
sample rate. Shared Translator capture/player modules are not edited.

Call's unsent input batches previously survived while the assistant spoke and
could be appended to the next question. An input epoch now discards pending and
not-yet-dispatched old-turn PCM without leaving gaps in accepted chunk indexes.
Captured-byte limits are not refunded. Already dispatched requests remain owned
and retain their accounting. The existing turn-taking Call explicitly selects
Google's `NO_INTERRUPTION` activity handling so late input/echo does not cut off
the answer. Explicit provider reset events still discard canceled output.

The public API reference documents the default interruption behavior, selectable
activity handling, and that generated content may be buffered by clients:
https://ai.google.dev/api/live (checked2026-10-16).

Existing content-free production logs show one user Call with8200ms input and
2220ms output and two with0/0. Those logs do not establish audible continuity
or the reason for the0/0 calls. Future Call close logs add only an allowlisted
reason and interruption count, with no audio, transcript, user ID or credential.

## Verification limits

No browser/browser-based tests, paid provider requests or microphone captures
are used for this repair. Deterministic Node clocks test jitter, samples, input
epochs, End, limits and stale callbacks; jsdom checks actual Flask markup with
the actual conflicting theme/Call styles and synthetic viewport events.
These checks do not measure Android speaker output, OS resampling, perceived
latency or pixel layout on a real device.

Both supplied Library screenshots were resolved, but the authorized transfer
helper failed to download them. The image-read route returned no pixel blocks.
No screenshot pixels were inspected and no image-dependent claim is made.

The exact source/tree, offline CI and Render release evidence are recorded in
the external cloud release artifact after deployment. Runtime readiness is a
configuration/ledger check, not paid end-to-end audio verification.
