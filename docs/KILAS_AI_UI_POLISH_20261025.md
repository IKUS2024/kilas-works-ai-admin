# AI workspace visual polish — 2026-10-25

Scope: proportion/alignment refinements to the existing AI Chat, AI Call, Translator and Voice Over. Preserve the October 24 reference identity, prior keyboard/drawer fixes, all handlers, models and account behavior. No Finance or provider implementation changes.

Baseline: remote main and Client Hub both `743f1e08a533dafc8667f201fdeca805dedb4150`; deploy `dep-dbeg15rncjis73e4r23g` LIVE. No other active agent or Render rollout was observed. Work is isolated from the user's dirty main checkout in `.worktrees/ui-polish-20261025`.

Impeccable: read the workspace skill, PRODUCT.md, newest master entries, DESIGN.md, the scoped AI reference brief, polish and craft-floor guidance; context loaded once. Incumbent UI is the visual authority. No Figma, generated assets, new template or global design changes.

Changes: reduce oversized headings and control heights, tighten local gaps, align voice preview and script actions, retain readable full tab labels in a horizontally scrollable narrow strip. Only the scoped reference stylesheet changes application appearance; base.html changes only its cache version inside the existing non-Finance gate. Compact keyboard identity/pending-attachment rules and chat-only drawer boundary are preserved.

Before evidence: authenticated read-only production captures for Chat, Call setup, Translator and Voice Over; synthetic baseline artifacts from successful Linux CI run 40123379257 at the exact production SHA, downloaded under `.impeccable/review/ui-polish-before/`. The local Windows Flask harness cannot import the existing Linux-only `fcntl` acceptance module; no production module or security check was patched to bypass that limitation. Browser matrix and Python regressions therefore run in Linux CI.

Local Node lifecycle/PCM/playback/interpreter/viewport tests: 97 PASS. Python test syntax, Ruff E9/F and git diff whitespace checks passed. No physical Android or real paid audio/model test is claimed. This is the validated pre-release checkpoint; final main/deploy/live verification metadata is maintained in [release PR #160](https://github.com/IKUS2024/kilas-works-ai-admin/pull/160).

Expanded responsive matrix: 320, 390, 412, 768, 820, 1024 and 1440 px, plus 844×390 landscape. Retain existing empty/drawer/Call setup+connecting/Translator setup+active/Voice Over/keyboard tests; add model menu bounds, filled long transcript with pending attachments, and explicit absence of Chat sidebar on Translator/Voice Over. Existing mobile visualViewport/zoom tests remain unchanged.

Final application candidate `b78478688e6f5b9d7c46d77f778b167c927fa759`: [reference UI CI 40125305137](https://github.com/IKUS2024/kilas-works-ai-admin/actions/runs/40125305137) passed all three jobs: behavior/boundaries (133 Python, 97 Node), responsive states/navigation, and baseline comparison. The 80 screenshots/24 surface checks report no page overflow or page errors and zero paid calls. Existing mobile drawer/visualViewport/zoom scenarios and the 48 tool navigation flows also passed. Representative desktop/mobile captures of all four surfaces were compared with the exact incumbent baseline; the visual identity and dark Call state remain intact. Narrow navigation scrolls only within its strip.

The expanded landscape test must use the existing Chat options disclosure for model selection and Call launch; two initial harness timeouts were corrected to follow that real path, without force clicks or deleted assertions. A strip wrap setting was corrected in CSS. The original handlers remain unchanged.

One scoped Impeccable detector pass returned 188 advisory findings and no non-advisory findings. These include incumbent palette/type literals compared with the global DESIGN ramp; scoped reference colors remain unchanged, and the smaller display/control sizes are the explicit purpose of this refinement. No global token/sidecar/drift repairs were performed.

The full repository is not claimed green. Automatically triggered legacy Assist/phase workflows still encounter retired-flow 303 versus 200/404 expectations; Global UI's Home/workspace/Finance/localization failures were compared against the immutable earlier baseline with **zero added failures** in all three groups. No unrelated test or protected implementation was edited to turn these green. Read-only GitHub branch-rule inspection found no required status contexts or rules; release uses the normal PR merge endpoint, no bypass/force push.
