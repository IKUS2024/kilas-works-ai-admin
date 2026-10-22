# Voice Over restored-result actions — 2026-10-22

Baseline: `4e27fbb980ab2a30645931cdc28c124a08e5064c` on main and the live Client Hub. Creative Services and all earlier changes are preserved.

Direct entry restores the newest owned, completed Voice Over into `_latest_result.html`. Recent opens `_result.html`. The restored-card template omitted the alternate action despite showing the same saved audio and edit action. A focused regression reproduced that discrepancy before the fix.

Both templates now include `_voice_result_actions.html` for the existing edit and alternate controls, passing the actual displayed job. The latest card also shows the existing alternate-charge explanation. The Home handoff also restores the latest owned successful result: the route no longer suppresses it when `home_task` is present. The separate transferred editor draft is preserved exactly. There are no provider, voice, pricing, permission, schema, or regeneration-handler changes. Regeneration continues to use the stored spoken script, target language and voice, rather than the current unsaved draft; edit continues to restore the latest spoken language and existing voice selector.

Validation:
- New latest-result tests: 4 pass, including matching initial/Recent action URLs, both real POST handoff routes with empty and transferred drafts, exact last translated script/language, ownership and no-history/legacy/queued/processing/failed exclusions.
- New Chromium checks at 390 and 1440 CSS pixels: real Home button handoff with empty and transferred drafts, direct entry, tab changes, refresh, Recent selection, exact translated-language/voice editing, alternate request bound to the displayed result, and absent alternate controls for non-success/empty states. Requests use a disposable local database and synthetic providers; the new browser test intercepts the alternate POST without regenerating.
- Existing alternate, spoken-script edit, audio, history, experience and navigation regression results are recorded in the release report.
- New focused and browser regressions run in Kilas Audio QA. Browser evidence is under `/tmp/kilas-latest-result-review` in the cloud workspace.

No paid generation, real regeneration, purchases, external sends or physical-device tests were performed. The referenced Library screenshot could not be downloaded (HTTP 403), so it was not visually inspected. The cloud workspace has no existing authenticated production browser session. Live authenticated visual verification must not be inferred from local synthetic Chromium results.
