Translator direction selection — 4 November 2026

Baseline: main d83d24531df5d37a86ac1d735b2905d1e9f0ff07 (PR200).

The language cards previously started microphone capture and changing cards could cancel an unfinished turn. Cards now only select the speaking direction. Selection changes neither audio context nor capture, readiness, admission or provider work. Their pressed state indicates selection; the current direction and the K button's accessible name reflect it. Only K starts listening and K again finishes the turn. Both cards are disabled throughout connecting, recording, processing and playback, preserving pending output. Language setup controls are also locked until End. Backgrounding still stops capture immediately and now explicitly reports that the session ended with K restart guidance.

Preserved: both directions, all 99 configured languages, native K touch/keyboard controls, consent, ordered PCM/Finish, duplicate Finish prevention, microphone exception normalization and error retry. No backend, Finance, provider configuration, billing or schema changes.

Validation: backend 18 tests; interpreter/capture/player/PCM/API 87 Node tests; authenticated Flask/synthetic-wire tap flow at four widths; K image touch/pointer/keyboard at four widths; hardened four-locale/four-width matrix; legacy browser five viewports. Selection tests count zero readiness requests, zero AudioContexts and zero microphone requests before K. They cover selection by mobile tap/Space/Enter, ignored card activation during connecting/listening/processing, immediate track stop, one activityEnd, output drain, denied/missing microphone, pending-permission cancellation, provider error/retry, background stop, End and arbitrary Japanese/French settings. Mobile/desktop rendered screenshots were visually inspected; selected direction is clear and layout retained.

All microphone samples and provider replies are synthetic. Physical microphone and real Gemini acceptance require independent device evidence and are not claimed. Parent inspected the user's latest screenshot; this executor inspected its generated test screenshots, not that Library file.
