# Unified Kilas AI Home — 2026-10-10

Owner request: Home should offer one Kilas AI entry rather than competing AI,
Video, and Translator product cards. This scoped change keeps the existing
white Manrope/orange identity and Finance tile, navigation form, and content.

`/products/start` now presents “Mau ngapain hari ini?”, the existing streaming
chat composer, and four task choices: Chat AI, Naskah & ide video,
Terjemahkan audio/video, and Buat suara. Optional project organization and
recent conversations sit below the composer. Selected UI language is retained.

Chat uses the existing private thread endpoints and persisted history.
The other choices POST a CSRF-protected draft to `/kilas-ai/home-task`, which
renders the original tool form without submitting a generation job. Video
receives its idea, voiceover receives its script, and translation displays its
notes before the original media upload. Results remain in the respective tool
histories; the UI states that handoff explicitly. Original URLs, upload forms,
saved projects, and conversation links remain available.

Home exposes “Terjemahan langsung / Bantu jawab” only when the existing isolated
owner QA readiness gates allow it. Otherwise it shows “Belum tersedia untuk akun
ini”. Supported capture is selected desktop Chrome-tab audio, including eligible
web videos or calls; it is not a YouTube-only feature or arbitrary phone/app
capture. This release does not enable flags or change capture/provider logic.

Verification uses disposable synthetic owners and forbidden external provider
transport. Six Home HTTP tests cover CSRF, gates, limits, escaped drafts, locale,
and existing route preservation. Actual Chromium acceptance covers 1440, 390,
and 320 px, repeated drawer navigation/Escape, draft switch/cancel, attachment
guard/removal, handoff forms and CSRF/uploads, back/forward, translation notes,
voiceover script, chat/history/reload, Stop, locale, overflow and JS errors.
Additional regressions: 32 chat/localization tests, 3 Finance style-loading
tests, 10 Finance UI integrity tests, and 17 content project tests passed.
One existing content prototype browser test is skipped outside its opt-in
runner; the dedicated Home browser test was executed and passed.

Screenshots are actual local Flask renders with synthetic data, stored in
`/workspace/kilas-home-review/` with `verification.json`; they are not production
browser captures. Library upload was attempted through the official refreshed
helper and failed during tool discovery with a network error, before uploads
were prepared. Local screenshots remain available for owner review.

No auth/session, Finance implementation, billing, provider, runtime flag,
Trading, inference, or paid capture changes. Trading main commit
`557a0847c5c8d6d68f9f46846c76a4299cd59768` is the integration base.
