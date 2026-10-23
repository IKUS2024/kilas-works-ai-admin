# AI Chat zoom repair — 2026-10-23

Baseline: main d7e8fcca55baa5d515bac8a0adb0b9b52a9b7482 (six Chat recovery fixes).

Confirmed reproduction: a 390 CSS-pixel layout pinched to 200% exposes a 195-pixel visual viewport. Old code set body height to 422 but retained body width 390 and flagged `home-keyboard-open` without a keyboard. The send button was at x=275..319, outside visible x=0..195. This is an application viewport mismatch in addition to ordinary browser magnification. The old 500px chat-shell minimum and clipped main region also made a short visual viewport permanently hide controls.

The Chat body now follows all four visual viewport dimensions. Keyboard detection compares height multiplied by pinch scale, so zoom alone is not a keyboard. Container queries reflow model selectors, task controls and the composer inside the actual visible Chat width. Small controls retain their touch targets, long content remains vertically scrollable, and focusing the composer keeps it reachable at the bottom. Viewport meta still permits user zoom. Scope is Chat only; no provider, quota, persisted data, credential, Finance, Translator or Voice Over implementation changes.

Validation:
- 28 Chromium scenarios plus four zoomed Chat/image model dialog containment checks, Home and persisted-conversation routes: 320/390/768/1440 CSS widths; native CDP visual viewport pinch 200/300% on mobile and desktop; 200% text sizing; focused desktop 200% reflow and reset; synthetic keyboard geometry with zoom and pan. No horizontal document overflow, no false keyboard state, usable input width and reachable send button.
- 31 offline core Chat/model/recovery tests PASS, including all six recent regression cases.
- Existing synthetic-provider composer recovery browser checks PASS at 390/1440, including failure/retry, uncertain HTTP replay, multipart and cancel/new-message.
- Home suite: 18 tests, five pre-existing failures; same exact failure names on clean c542491 baseline. Combined run:49 tests,44 PASS,5 baseline failures. Details outside repository in zoom-baseline-comparison.json.
- No paid inference or production form submissions.

Limits: headless Chromium emulation is not a physical Android device. Keyboard geometry and browser text scaling are simulated; native desktop browser zoom is represented by CSS reflow widths, separately from actual CDP pinch. Production verification must additionally confirm exact deployed revision, served asset hashes and health after LIVE.
## Follow-up: usable hierarchy after owner screenshot

The a25b8b1 repair still crowded the viewport. Its test allowed scrolling the whole Chat to reach Send, which masked the owner's actual composition. The replacement prioritizes the transcript and bottom composer. At magnification or a short viewport, one native `Opsi chat` disclosure contains existing model pickers, feature navigation and Call. The same DOM controls and handlers return to their original positions at normal size. Welcome artwork is omitted only in compact mode. Text is not counter-scaled and zoom remains enabled. Send/attachment targets remain at least 44 CSS pixels; the composer uses one row when there is room and two at extreme narrow width.

Pending attachment previews and public errors are bounded so a failed upload cannot push Send offscreen. Call's existing busy-chat guard now finds its owning composer after relocation, and closing Call returns focus to the visible disclosure. No call is started in the guard test: microphone and POST count remain zero.

Evidence: a 390x704 CSS viewport rendered at 945x1706 pixels, actual CDP pinch 150/200/300 percent. On a25b8b1 at 200 percent, visible height352 and Send bottom463.6 (clipped); replacement Send bottom337 (visible), no whole-Chat scrollbar. At300 percent Send stays visible as well. Input font remains16px in both revisions. The 100-percent mobile screenshots are pixel-identical. Synthetic before/after screenshots and geometry were inspected in the task's zoom-evidence/comparison directory; the owner's private screenshot is not committed.

Regressions now require Send to be fully inside the visual viewport without scroll-into-view rescue. They cover57 viewport scenarios across Home, empty conversation and a conversation with synthetic retained history, including realistic shorter mobile dimensions, text enlargement, keyboard geometry, model menus, normal-layout restoration and Call busy/focus guards. All pass locally. Existing failure/retry, lost-response replay, multipart and cancel/new-message cases pass at mobile pinch200 percent and desktop normal; provider dispatches remain idempotent.31 core Chat/model/recovery tests and29 synthetic Call lifecycle tests pass. Physical Android is not claimed tested.
