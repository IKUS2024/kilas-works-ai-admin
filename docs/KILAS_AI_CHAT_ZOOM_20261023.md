# AI Chat zoom repair — 2026-10-23

Baseline: main d7e8fcca55baa5d515bac8a0adb0b9b52a9b7482 (six Chat recovery fixes).

Confirmed reproduction: a 390 CSS-pixel layout pinched to 200% exposes a 195-pixel visual viewport. Old code set body height to 422 but retained body width 390 and flagged `home-keyboard-open` without a keyboard. The send button was at x=275..319, outside visible x=0..195. This is an application viewport mismatch in addition to ordinary browser magnification. The old 500px chat-shell minimum and clipped main region also made a short visual viewport permanently hide controls.

The Chat body now follows all four visual viewport dimensions. Keyboard detection compares height multiplied by pinch scale, so zoom alone is not a keyboard. Container queries reflow model selectors, task controls and the composer inside the actual visible Chat width. Small controls retain their touch targets, long content remains vertically scrollable, and focusing the composer keeps it reachable at the bottom. Viewport meta still permits user zoom. Scope is Chat only; no provider, quota, persisted data, credential, Finance, Translator or Voice Over implementation changes.

Validation:
- 24 Chromium scenarios, Home and persisted-conversation routes: 320/390/768/1440 CSS widths; native CDP visual viewport pinch 200/300% on mobile and desktop; 200% text sizing; synthetic keyboard geometry with zoom and pan. No horizontal document overflow, no false keyboard state, usable input width and reachable send button.
- 31 offline core Chat/model/recovery tests PASS, including all six recent regression cases.
- Existing synthetic-provider composer recovery browser checks PASS at 390/1440, including failure/retry, uncertain HTTP replay, multipart and cancel/new-message.
- Home suite: 18 tests, five pre-existing failures; same exact failure names on clean c542491 baseline. Combined run:49 tests,44 PASS,5 baseline failures. Details outside repository in zoom-baseline-comparison.json.
- No paid inference or production form submissions.

Limits: headless Chromium emulation is not a physical Android device. Keyboard geometry and browser text scaling are simulated; native desktop browser zoom is represented by CSS reflow widths, separately from actual CDP pinch. Production verification must additionally confirm exact deployed revision, served asset hashes and health after LIVE.
