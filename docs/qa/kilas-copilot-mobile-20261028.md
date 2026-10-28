# Copilot compact mobile correction

Baseline production/main: `666836562c7235b4823515a1026096d6b6b55037`.
The owner reported that capture works but the first screen is oversized and
text-heavy, and requested one microphone tap to begin. This scoped revision
preserves the existing speech, reply, translation, metering and ownership engines.

- Compact tool navigation and title; plain white Copilot canvas. The translation
  switch remains above the mic, with full-name target selection only when ON.
- Santai/Profesional and secondary guidance remain in a closed native Info
  disclosure. The repeated instructions, capacity notice and checkbox gate are
  removed. One concise processing disclosure remains visible before recording.
- A deliberate tap invokes browser microphone permission directly. Once granted,
  native capture begins without waiting for a network session request. That POST
  is deferred until the second tap has stopped capture. Audio still uploads only
  after stop, capped at 60 seconds; no interim transcript or automatic rearm.
- The existing server consent and CSRF guards remain. The explicit stop/process
  action submits the existing consent field after the processing disclosure;
  browser permissions are never bypassed by application code.
- Pending permission, repeated taps, cancellation during deferred session creation,
  denied permission, navigation cleanup, translation/history, old Chat preservation,
  and Voice Over unsaved-draft guards remain covered.

Browser QA uses disposable accounts and mocked providers at 360x740, 393x786,
768x1024 and 1440x900. In addition to deterministic capture mocks, a native
Chromium MediaStream/AudioContext/PCM/WAV case uses Chromium's synthetic hardware
source and verifies live/ended tracks and one-tap capture with no provider call
before stop. It is not a physical microphone or paid API acceptance test.

Input Library image `libfile_acc91c0311208191a9786291852f24d8` resolved, but
supported materialization failed twice (`library file transfer failed: download
failed`), including the bounded explicit local destination retry. The executor
therefore used the parent's actual pixel observations and inspected its own
reproducible browser screenshots. It does not claim to have viewed original
input pixels. Screenshot artifact and review/release outcomes are recorded in
the PR; publication requires parent visual review of this correction first.

No Finance business/UI files, historical chats, database schema, credentials,
subscriptions, budget settings, or other Render services are changed. Existing
general CI baseline failures remain documented in the October 27 triage report;
this is not authorization for unrelated historical test cleanup.
