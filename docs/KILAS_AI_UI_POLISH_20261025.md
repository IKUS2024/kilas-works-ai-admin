# AI workspace visual polish — 2026-10-25

Scope: proportion/alignment refinements to the existing AI Chat, AI Call, Translator and Voice Over. Preserve the October 24 reference identity, prior keyboard/drawer fixes, all handlers, models and account behavior. No Finance or provider implementation changes.

Baseline: remote main and Client Hub both `743f1e08a533dafc8667f201fdeca805dedb4150`; deploy `dep-dbeg15rncjis73e4r23g` LIVE. No other active agent or Render rollout was observed. Work is isolated from the user's dirty main checkout in `.worktrees/ui-polish-20261025`.

Impeccable: read the workspace skill, PRODUCT.md, newest master entries, DESIGN.md, the scoped AI reference brief, polish and craft-floor guidance; context loaded once. Incumbent UI is the visual authority. No Figma, generated assets, new template or global design changes.

Changes: reduce oversized headings and control heights, tighten local gaps, align voice preview and script actions, retain readable full tab labels in a horizontally scrollable narrow strip. Only the scoped reference stylesheet changes application appearance; base.html changes only its cache version inside the existing non-Finance gate. Compact keyboard identity/pending-attachment rules and chat-only drawer boundary are preserved.

Before evidence: authenticated read-only production captures for Chat, Call setup, Translator and Voice Over; synthetic baseline artifacts from successful Linux CI run 40123379257 at the exact production SHA, downloaded under `.impeccable/review/ui-polish-before/`. The local Windows Flask harness cannot import the existing Linux-only `fcntl` acceptance module; no production module or security check was patched to bypass that limitation. Browser matrix and Python regressions therefore run in Linux CI.

Local Node lifecycle/PCM/playback/interpreter/viewport tests: 97 PASS. Python test syntax and git diff whitespace checks passed. Candidate CI, after screenshots, merge and final production verification are pending and must be recorded from observed evidence. No physical Android or real paid audio/model test is claimed.

Expanded responsive matrix: 320, 390, 412, 768, 820, 1024 and 1440 px, plus 844×390 landscape. Retain existing empty/drawer/Call setup+connecting/Translator setup+active/Voice Over/keyboard tests; add model menu bounds, filled long transcript with pending attachments, and explicit absence of Chat sidebar on Translator/Voice Over. Existing mobile visualViewport/zoom tests remain unchanged.
