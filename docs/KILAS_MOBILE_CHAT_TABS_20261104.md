# Mobile chat tab reflow correction

The Android keyboard report was reproduced locally at 390px width with a short
visual viewport. Compact mode moved the managed `Kilas AI` heading into the task
row as a fixed 240px item. Theme rules still gave each task a shrinking percentage
width, leaving approximately 31px per task while its label remained much wider.

The task row now uses intrinsic, non-shrinking label widths and its own horizontal
scroll area. Ordinary managed keyboard layouts keep `Kilas AI` above the row;
interactive model selectors remain accessible in the scroller. Only extreme
magnification with less than 280px viewport height moves the managed heading into
that row, at its text width. Composer behavior and chat transport are unchanged.
CSS/JS cache versions are updated. The Chat options row remains absent.

Validation on the final patch:

- `test_kilas_mobile_tab_geometry_browser.py`: 44 geometry cases across managed
  and interactive-model modes, 320/390/1440px widths, normal and long labels,
  short visual viewport, offsets, keyboard close/reopen, layout viewport resizing
  and magnification. Assertions check label containment, non-overlapping task
  boxes, 44px targets, focus/scroll access, no document horizontal overflow and
  visible Send during keyboard cases. No network writes or page errors.
- `test_kilas_chat_zoom_browser.py`: 57 existing chat/agent zoom and reflow cases.
- `test_kilas_chat_options_removed_browser.py`: desktop/mobile tasks and composer,
  keyboard reflow and absence of Chat options.
- `node --check client-hub/static/kilas_home.js` and `git diff --check`.

Local screenshot evidence (synthetic account, no payment details):

- `/tmp/kilas-mobile-tabs/managed-True-390-keyboard.png`
- `/tmp/kilas-mobile-tabs/managed-True-320-keyboard.png`
- `/tmp/kilas-mobile-tabs/managed-True-390-long.png`
- `/tmp/kilas-mobile-tabs/managed-True-390-normal.png`
- `/tmp/kilas-mobile-tabs/report.json`

These are Chromium emulation checks, not physical Android keyboard verification
or production validation. The original screenshot's Library materialization URL
failed in this executor with `Tunnel connection failed: 403 Forbidden`; it was
not retried. Diagnosis used the parent's actual-image observations and the
independently reproduced browser geometry. Screenshots stay local/internal.

Publication is a distinct chat-only commit on top of the landscape thumbnail
integration. The checkout task will preserve it and deploy the combined release;
this task does not trigger a separate deployment or change payment/auth routes.

## Follow-up: ordinary tab widths

The combined-release reference job exposed an ordinary-layout regression in the
new broad flex rule. `flex: 1 0 auto` distributed equal extra space on top of
different intrinsic label widths. At 320px the three tabs measured 77.625,
94.21875 and 96.15625px. The retained cross-surface contract requires equal 52px
high tabs for stock labels when the keyboard is closed.

Normal tabs now use `flex: 1 0 0px` with the same `min-width: max-content` guard.
This restores equal widths where labels fit while retaining horizontal scrolling
for genuine long-label overflow. The separate non-shrinking compact rules remain
unchanged. The reference assertion is retained, with width diagnostics added;
the 44-case test also now asserts equal non-scrolling stock tabs in normal mode.
CSS cache versions are bumped independently of the unchanged JavaScript.

Follow-up checks use the same patch: `kilas_task_tabs_browser.py` (18 bilingual
width configurations and cross-surface navigation), the full reference UI browser,
44 tab geometry cases, 57 zoom/reflow cases and the three-width Chat options
regression. The full reference UI passes 24 surface/width checks with 80 captures
and zero paid calls. Stock 320px managed tabs now measure approximately
89.33/89.34/89.33px. Reports and screenshots remain under `/tmp/kilas-task-tabs`,
`/tmp/kilas-equal-reference-ui` and `/tmp/kilas-equal-tab-geometry`.
