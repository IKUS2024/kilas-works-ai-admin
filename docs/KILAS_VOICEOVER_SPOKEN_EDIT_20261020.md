# Voice Over: edit the script used for the selected audio

Prepared on latest main `a0f2e13f13aa174fb838ce03971ded79b27953f5` for the requested translated-script correction. This checkpoint records implementation and synthetic verification; deployment is handled separately.

## Behavior

Both result and Recent Edit script actions now fetch the selected job's persisted `spoken_script`. An Indonesian original translated into English opens the English words sent to speech synthesis. Any supported final language works the same way. Opening an older Japanese job after a newer Spanish job restores Japanese for that selected job.

The editor restores the output language and the exact available branded or owner-saved voice. Translation is switched off and its draft/result state cleared, so editing an already translated script and clicking Generate sends those edited words directly. A missing voice clears the selection and requires an explicit replacement. Accepted edits rotate the generation operation key; double clicks still submit once.

`original_script` remains untouched, including its original whitespace. Its existing reconstruction helper keeps its original-source semantics. Alternate takes use their own persisted spoken snapshot. Legacy jobs without spoken metadata do not offer an exact Edit action and explicitly say that the spoken script was not saved; no translation is inferred or invented.

Pending translation output cannot overwrite an accepted edit. Changes to a draft, translation settings or selected voice while Edit is loading cancel that replacement. Tenant ownership, terminal-state checks, private no-store responses and Live/session exclusions remain enforced.

## Verification

All provider calls were mocked or blocked. No paid inference, production data writes, new migrations, Finance edits or credential changes were used.

- Existing Audio/history/video-script/personal-voice/alternate backend regression: **105 passed** (independent parent verification).
- Focused `test_kilas_voice_edit`: **4 passed**, including exact translated/plain text, older selected Japanese versus newer Spanish, direct regeneration, alternate metadata, original archive preservation, personal/missing voice, terminal/legacy/session and tenant checks.
- Existing Translator regression: **21 passed** (independent parent verification).
- Actual Flask + Chromium `test_kilas_voice_edit_browser.py`: **passed** at 390 px (English) and 1440 px (Spanish), plus plain and saved-personal-voice regeneration. Covers result/Recent/reload/alternate edit, no double translation, stale translation discard, draft/settings races, one request on double click, legacy absence and deleted voice requiring selection. The operation-key check also runs without `crypto.randomUUID`.
- Existing history browser: **5 cases passed** (0/4/5/9 records at 390 px and 9 at 1440 px), preserving form, playback, scroll and retry behavior without extra POSTs (independent parent verification; `/tmp/kilas-voiceover-spoken-edit-history-browser.log`).
- Local synthetic evidence: `/tmp/kilas-voice-spoken-edit-review/verification.json`, `spoken-edit-390.png`, `spoken-edit-1440.png`; browser log `/tmp/kilas-voice-spoken-edit-browser.log`.

The source base's Chat attachments, initial navigation styling, model selector localization, Call recovery and Finance changes remain preserved. This patch is limited to Voice Over editor behavior, its localized messages, focused fixtures/tests and this checkpoint.
