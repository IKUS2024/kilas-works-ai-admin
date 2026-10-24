# Mobile drawer and keyboard correction - 2026-10-24

This records the narrow correction in [PR 158](https://github.com/IKUS2024/kilas-works-ai-admin/pull/158), runtime candidate `8c5968552c92d6041db55ff8dddac0c44665b266`. The owner rejected PR 157's mobile result with three Android screenshots. The correction restores usable saved-chat history and reachable drawer footer controls, keeps the Kilas identity visible when the keyboard reduces the viewport, and prevents pending attachments from covering the transcript.

## Evidence and cause

The three originals are preserved in the task's `mobile-bug-references/` folder: `1000345677.jpg`, `1000345675.jpg` and `1000345679.jpg`. The builder and independent reviewer inspected all three. Their archive is `E:\edit kilas\chat-layout-bug-screenshots.zip` (272,362 bytes), SHA-256 `ee0fabb7b079ee6aaf32ca266e307fc89892af7312c0648494f25098f035144f`.

The disposable reproduction of main `14fe` confirmed the drawer failure at 360 by 650 pixels: history collapsed to 8 pixels; its bottom was 615.8 pixels while Profile started at 535 pixels; the first saved-chat row began at 669.8 pixels, beyond the viewport. The Finance navigation row occupied 66 pixels. PR 157's enlarged menu rows consumed the space intended for history and allowed content to overlap the footer.

Voice Over had an additional loading defect: the audio blueprint rendered the chat drawer with `chat_sidebar_enabled=False`, so the base sidebar stylesheet was omitted. The compact chat rules also hid the central logo, welcome and Works wordmark segment. Finally, absolutely positioned pending attachment previews could overlay conversation content in the reduced viewport.

## Implemented behavior

The shared template now includes the sidebar stylesheet when sidebar history is defined, as well as when the sidebar is enabled. The reference stylesheet version is updated so the correction is requested as a fresh asset. Layout changes remain scoped to the existing AI reference header and drawer.

- Drawer rows use tighter spacing while keeping real links and controls. Saved-chat history has a 64-pixel minimum scroll area within history content with a 108-pixel minimum. The drawer follows the existing visible-viewport height and top offset, and its outer container can scroll to the footer. At 320 by 568 pixels, reaching Profile by scrolling is an accepted adaptation; the footer is not required to remain pinned while history is visible.
- Compact chat retains the full KilasWorks wordmark. An empty chat keeps the existing logo at 40 pixels and its welcome heading at 20 pixels. The compact header remains 44 pixels high; the wordmark reduces to 20 pixels at widths of 360 pixels and below.
- Pending attachment previews participate in the composer's layout instead of floating over the transcript. Their compact preview area is capped at the smaller of 64 pixels and 18 dynamic viewport-height units.

The existing identity asset, Manrope, palette and token system are preserved. No new colors or assets were introduced. Actual routes, history, attachment removal, composer actions, drawer focus/close behavior, locale preferences, account boundaries and security gates remain authoritative. Finance implementation and design tokens are outside this correction; its existing drawer destination remains available.

## Verification

The [final geometry report](../../evidence/mobile-correction-final/verification.json) accompanies 16 captures: Chat and Voice Over drawers at widths 320, 360, 393, 820 and 1440 pixels, plus compact empty-chat and transcript/attachment states at 320, 360 and 393 pixels. At 360 pixels, history is 115 pixels high, ends at 521 pixels and precedes Profile at 573 pixels. At 320 pixels, history retains its 64-pixel minimum. The Finance navigation row measures 48 pixels on both routes.

The [footer evidence](../../evidence/mobile-correction-footer/verification.json) and adjacent captures confirm the short-screen scroll adaptation, including [Chat's reachable Profile footer](../../evidence/mobile-correction-footer/chat-drawer-footer-320.png), the Voice Over footer and a compact keyboard drawer. Representative final footer and transcript captures were also inspected during documentation.

Local focused browser cases pass. Existing Home checks pass at five viewport widths, including keyboard and transcript behavior; all five viewport Node tests pass. Fresh independent review returned **SHIP**, with five review sections and no material findings. The detector's 176 advisory color findings are inherited; this correction adds no color values.

CI checkpoint: the [Linux behavior-and-boundaries job](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/40120043633/job/120949410851) succeeded for Audio, Call, Interpreter, protected Finance and Node checks. The original 40 responsive captures passed. The new focused CI browser suite and baseline comparison were still running when this record was written. This document does not certify a deployment or live revision.

## Limits and retained context

Browser verification uses Chromium and simulated visual-viewport changes. It does not establish physical Android keyboard/browser behavior, real microphone acceptance or paid-provider audio success. The reports explicitly record zero paid calls and no physical Android test. Production acceptance remains separate from these local and CI results.

The [six-reference contract](KILAS_SIX_REFERENCE_IMPLEMENTATION.md) and [scoped AI design](KILAS_AI_REFERENCE_DESIGN.md) remain the visual authority. This document supplements their mobile behavior. `PRODUCT.md` retains historical audit-only wording, and the global `DESIGN.md` retains older rail/composer descriptions alongside its scoped-reference pointer. That existing drift is recorded without repair. This documentation pass changes only this file; it does not regenerate global design tokens, the sidecar or other briefs.
