# Copilot listening workspace visual refinement

Baseline: live/main `49d3810e131f039b7268d51383dff7eaa60d3c17`.
The owner found the compact version too bare. This scoped visual pass gives the
existing capture area a softly tinted peach surface, restrained depth and static
microphone rings, with aligned controls and balanced mobile/desktop proportions.
Copy and controls remain unchanged. The waveform appears only during actual
capture; decorative idle rings do not animate or imply an active microphone.

Capture JavaScript, all backend/provider/metering code, sidebar/Profile, hidden
legacy Chat, Finance and Translator/Voice Over engines remain unchanged. No new
feature, credential, schema, budget or production-data operation is introduced.
Existing browser QA covers native MediaStream/AudioContext using Chromium's
synthetic hardware, one-tap start/tap-stop, permission/cancel/history/translation,
shared tools and session preservation at 360/393/768/1440 widths. Added assertions
keep the initial waveform hidden and microphone aria state OFF. Physical phone,
microphone, paid API and Safari tests remain NOT RUN.

The read-only release smoke now compares both CSS and JavaScript bytes. A CSS
revision cannot pass by observing an unchanged JavaScript asset before deploy.
No publication is performed before parent review of the actual CI screenshots.

Original image `libfile_2d391239be1c8191b1eed9cf3363257d` resolved but both
supported materialization attempts failed (`library file transfer failed:
download failed`), including an explicit consumer-local retry. The executor
uses the parent's actual pixel findings and its own rendered screenshots; no
original-pixel inspection is claimed. Scoped Impeccable layout detector returns
no findings for CSS; Jinja-link analysis remains limited, so actual browser
inspection is the visual evidence. PR records final artifact and review status.
