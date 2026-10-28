# Copilot owner-reference composition

Baseline/main: `726fef8ed6470bbec3f483480036e6e44c31e2e1`. The previous
deployment was already in progress when the latest owner reference arrived;
this follow-up starts from that main, without an automatic rollback.

The composition follows the parent's actual pixel inspection of
`libfile_28f0eb443db481919205e9a1fd891dab` (`1000349517.jpg`): centered existing
wordmark, hamburger and avatar, gray inactive tool pills, centered Conversation
Copilot title, capability badge, translation card, large orange microphone with
static peach halo on white, visible style segment, two-device hint, wide orange
Dengarkan action and a small text-only AI footer. Provider processing information
stays inside optional Info. Viewer controls, concept labels, numbered headings,
Powered by branding, consent checkbox and extra recent-session sections are absent.

The automatic-language badge describes the existing automatic speech-language
behavior. It never displays an invented detected language. Idle halo is static;
the waveform remains hidden until actual capture. Translation target and history
follow the existing toggle. Previous replies remain labelled AI suggestions.

Microphone and bottom action call the same guarded `captureAction` function and
share disabled/pressed/accessible-label state. One browser permission request
starts one capture; either control can stop/process it. Cross-control rapid taps
cannot create a second capture or provider submission. The existing stop-only
upload, 60-second cap, cancellation, foreground cleanup and quota gates remain.
Backend/providers/metering, Finance, Translator/Voice Over engines, existing
sidebar/Profile functions and hidden reversible AI Chat are unchanged.

Browser QA uses disposable accounts and mocked providers at 360/393/768/1440.
It exercises start on mic/stop on CTA, start on CTA/stop on mic, rapid taps across
both, denied/pending permissions, cancellation and blocked provider state,
translation/history, centered header and visible style/AI footer, optional Info,
native Chromium MediaStream/AudioContext/PCM/WAV with synthetic hardware, and
the single-sync-worker disconnect fence. Physical mic/phone, paid API and Safari
acceptance remain NOT RUN.

Both supported Library materializations failed (`library file transfer failed:
download failed`), including the explicit consumer-local retry. No original
pixel inspection is claimed by the executor; parent's actual pixel findings and
the executor's rendered screenshots are the evidence. The PR records CI artifact
and parent visual review before any follow-up production deployment. No new
credentials, costs, schema, subscriptions or production data changes are made.
