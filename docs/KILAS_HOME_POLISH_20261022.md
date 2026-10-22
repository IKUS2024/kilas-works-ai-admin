# Scoped Home polish and stale draft notice — 2026-10-22

Baseline: `0c35a5914b187039a39e2d14da073516aa04cde6`. User authorized Home UI polish, removal of the redundant central Voice Over starter, and a verified fix for the confusing draft notice. Finance and provider/model behavior remain protected.

## Proven cause

At baseline `static/kilas_voice_handoff.js:8–14`, a starter checks the real textarea's `value.trim()`. When nonempty it writes the draft-protection message, but neither the textarea input handler nor a successful later starter clears that message. The normal Chat input handler only resizes the textarea (`kilas_ai.js:33–34`). A code execution probe using the actual baseline module and synthetic UI objects reproduced:

1. Starter fills a prompt; another starter protects the existing draft and shows the warning.
2. Clearing the input fires its input event. The value is empty, but the old warning remains visible.
3. A successful starter can also leave the old warning visible.

The guard uses a native textarea, not hidden rich-editor markup. Ordinary whitespace is trimmed and does not trigger it; attachment state is not consulted by this warning. No draft contents were inspected or printed. The exact preceding interactions on the reported Android device were not observed; the reproduced stale-message defect explains an empty composer with its placeholder plus that old warning without inventing a hidden draft.

## Implemented

- Keep real-draft protection. Mark ownership of the starter's notice, clear only that notice when the composer becomes empty or a starter succeeds, and leave a later upload/model/transport error alone. The draft message is a neutral hint on Home. Repeated taps on the same untouched app-populated starter are a no-op. Disabled/read-only/busy composers cannot be changed by a starter. No auto-submit, auto-generation or attachment deletion.
- Three equally sized central starters: promotional script, product image, document summary. The actual Voice Over tab and Chat → Voice Over action remain intact.
- Home-only CSS groups hero, starters, task tabs and composer; balances logo/title sizes; aligns the model selectors; fits all three task tabs at narrow widths. Existing thread/VO/Translator/Finance shells are not restyled. Short keyboard viewports hide decorative welcome content while retaining the composer and task controls.
- Bump the changed script cache key. No backend, schema, credential, pricing or provider settings change.

## Evidence

Real Flask + Chromium with synthetic accounts, model catalogs and blocked external browser traffic. No provider call or chat submission.

Before/after captures at 320/390/412/820/1440px show the gap from starters to tool tabs reduced from 104/176/211/265/286px respectively to 24px at each width. All three starters have equal widths/heights, the composer fits the viewport, and no horizontal overflow occurs. Keyboard checks at narrow widths keep the composer visible.

The new Home browser checks pass: empty composer, untouched-starter repeated taps, genuine unsent drafts, clearing and retrying, placeholder state, pending attachment preservation, unrelated-error preservation, request-in-progress guard, model-dialog open/close, reload and return navigation. Existing asset/audio/model/VO draft regressions remain in the focused release gate, including native PostgreSQL Library isolation.

Local before/after evidence is in the task's `home-polish-qa/` directory. Exact remote commit, final Linux gate, Render deploy and authenticated live verification must be recorded in the final handoff; this document alone does not claim production completion.
