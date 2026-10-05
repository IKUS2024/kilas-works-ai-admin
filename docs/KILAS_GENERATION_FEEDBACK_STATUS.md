# Kilas Audio / Video generation feedback

2026-10-05 focused UI patch. Scope: Translator/Voice Over and Video Plan generation feedback only. Impeccable narrow polish, incumbent white/orange identity retained.

- Visible non-blocking live status panel and disabled processing button during submission.
- Video reports saved only after successful server response; errors preserve existing retry flow.
- Audio follows existing redirect and incremental job polling. Queued/processing jobs display actual busy state; completed/failed status updates feedback. A session marker carries feedback across the existing redirect, with storage failures tolerated.
- No new polling, simulated percentage, retry, provider call, backend change, schema migration, balance/pricing change, or Finance change.
- Focused real browser tests use synthetic accounts and mocked providers; busy/button state, success, error, dismissal, responsive no-overflow and existing generation/download/history flows are covered. Audio widths 320/360/390/430/768/1024/1440; Video adds 820.
- Impeccable detector: zero anti-patterns; advisory 16px title and pale error tint are intentionally scoped to the status panel. Template stylesheet cannot be resolved by detector; CSS was scanned directly.

Release gates: focused checks and production UI verification pending. No paid production generation is required for this feedback-only patch.
