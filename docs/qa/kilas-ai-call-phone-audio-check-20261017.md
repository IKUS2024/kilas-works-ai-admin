# Provider-free phone audio diagnostic — prepared, not deployed

Branch `call-audio-check-20261017` is separate from production/main `511af5b`.
No change to normal Call capture, playback, provider VAD, greeting, interruption,
End, search, funding or other products is included. No paid provider session ran.

## Concrete finding

Production asks for mono input with `echoCancellation`, `noiseSuppression` and
`autoGainControl` true. Capture routes the microphone into a silent worklet;
there is no direct microphone-to-speaker monitor. Playback uses Web Audio.
The capture path does not read actual track settings/capabilities. A requested
boolean alone does not demonstrate acoustic performance on the user's phone.

The W3C Media Capture specification says boolean true leaves cancellation scope
to the user agent; `all` attempts cancellation of all system sound, while
`remote-only` targets incoming WebRTC tracks. This is a possible platform
limitation, not proof of the reported cause. Local Chromium 151 with a synthetic
device reports true for all three requested processors and supported AEC modes
`[true, false, "remote-only"]`; it does not advertise `all`. Blindly requiring
that mode would be incompatible with this tested browser.

Reference: [W3C audio constraints](https://www.w3.org/TR/mediacapture-streams/#dom-mediatrackconstraintset-echocancellation).

The earlier actual-browser queue tests retained speech through normal playback
completion, and cancellation stopped scheduled output. Nearby production logs
show interruptions and no complete turns. Those facts identify the interruption
path, but do not distinguish speaker echo, noise and actual user speech.

## Prepared diagnostic

Authenticated GET `/kilas-ai/call/audio-check` loads only a dedicated local page.
It requires existing AI access but never calls Call readiness, admission,
funding, provider connection, remote speech recognition or recording APIs.
Before the user explicitly presses Start it requests no microphone or audio
context. Its CSP prohibits all network connections (`connect-src 'none'`).

The test uses the existing CallCapture and CallPlayer with the production
playback latency hint. It measures approximately two seconds of room baseline,
six seconds of low-amplitude synthetic modulated tones and two seconds of tail.
Microphone PCM is consumed frame by frame for peak/clipping counters, never
retained as an audio recording. Only timestamped RMS values and synthetic
reference levels are kept temporarily for an approximate envelope correlation.
Both arrays are erased at finish. The visible/copyable summary contains only
allowlisted processing settings, latency, aggregate energy/peak counts and
correlation coefficient/lag. It excludes device names, IDs, account data, raw
samples, recordings and transcripts. Copy is explicit and local.

Stop, pagehide and backgrounding cancel output/capture. Late microphone grants
are stopped. No microphone access is remotely enabled. The correlation assumes
the user remains silent; it is not an AEC pass/fail, a speech detector, or a
measurement of the paid provider's VAD. Results must be interpreted alongside
device settings and the original symptom.

## Actual offline verification

- All 127 Python Call tests passed, including two new authenticated-route cases.
  Route access creates no admission, provider connection or usage reservation;
  it still works when the paid Call flag is off. Anonymous access redirects.
- All 58 Node frontend tests passed, including settings privacy and a synthetic
  delayed-echo envelope with known 400ms lag.
- Actual Chromium exercised the page, CSP, AudioWorklet, capture and player with
  a synthetic microphone. It processed 51 frames / 163,200 input samples, with
  no page errors, POSTs or WebSockets. There were seven same-origin GETs for the
  page and modules. Processing settings reported true/true/true. This is not a
  physical AEC test. Results: `kilas-ai-call-phone-audio-check-browser-20261017.json`.
- A separate cancellation case held the microphone-permission result until
  after Stop. The late tracks ended, all contexts closed, and no output source
  was created after cancellation.

## Exact device action, after diagnostic deployment is authorized

This URL is not available on current production/main yet. Once deployed:

1. End AI Call, then open `https://app.kilasworks.id/kilas-ai/call/audio-check`
   in the same Android Chrome and remain signed in.
2. Keep the phone's built-in speaker at the usual Call volume, tap **Mulai tes**,
   allow the microphone, and remain silent for the approximately ten-second test.
3. Tap **Salin ringkasan** and share the numeric summary. No audio upload or
   provider charge is involved. **Hentikan** stops the test immediately.

Do not claim that the original audio issue is fixed until physical evidence
identifies a correction and real-device behavior verifies it. This prepared
diagnostic is not a speculative production audio repair.
