---
version: 1
slug: "client-hub-templates-kilas-ai-agent-html"
primary_target: "client-hub/templates/kilas_ai/agent.html"
related_targets: ["client-hub/templates/kilas_ai/home.html","client-hub/static/kilas_ai_drawer.css"]
---

# Kilas AI drawer
Mode: Operate. Scope: existing AI Chat and Agent drawer only; preserve the established white Manrope/orange workspace. No alternate visual world, no backend changes.

## Direction contract
THESIS: A compact conversation library within the existing workspace; navigation, new chat, history and utilities have distinct levels.
OWN-WORLD: Existing white canvas, charcoal, muted gray, orange text with pale orange selection; consistent 44px rows, 8px control radius, thin neutral divider.
STORY: Navigate products, start or reopen a conversation, then reach account utilities without scrolling through all history.
FIRST VIEWPORT: Compact wordmark and close target; aligned stroke-icon product rows; outlined new-chat row; muted Recent chats heading and independent scrolling list; lower AI settings, language select/Apply and sign out.
FORM: Existing responsive navigation rail extended with a conversation library. Code-led within pinned existing identity; no random visual direction or replacement brand is appropriate.
FINISH: Independent finish verdict **ship** after selected-language clipping was fixed and all 15 local synthetic captures passed review. Documentation handoff preserves the incumbent `DESIGN.md`, `PRODUCT.md` and `.impeccable/design.json`; no new world, global token ramp or shipping raster asset was introduced. Commit/CI/deployment and authenticated production QA remain pending.

Interactions: history rows do not flex-shrink; one-line ellipsis retains the full accessible title. History scroll does not displace lower utilities. Short-height viewports retain an outer fallback scroll. Existing new-chat, language POST, navigation, logout and conversation data handlers are unchanged. Drawer focus trap includes the native language select.

## Built component and review evidence

The completed extension matches the incumbent Quiet Professional Workbench: white canvas, Manrope, charcoal/gray text, restrained orange selection, thin borders and flat navigation. Observed local geometry: desktop rail 270px; mobile width `min(88vw,320px)` at 760px and below; controls/history rows 44px with 8px corners; navigation/history 14px, headings 12px and utilities 12–13px. Product selection uses pale orange; current conversation uses quiet neutral selection. The history list scrolls independently, with an outer fallback below 720px viewport height. These are drawer expressions, not replacements for global navigation tokens or layout rules.

`client-hub/tests/test_kilas_drawer_browser.py` PASS: all 12 `id`/`en` combinations at 320,360,390,430,768,1024, plus empty/one/20 chats, long title, legacy thread, saved-chat open/reload, New chat and language POST, logout, focus/close/Escape/backdrop, independent scroll and no page/drawer overflow. Selected-language text fitting has an explicit regression guard. The 15 reviewed screenshots are `.impeccable/review/drawer-{id,en}-{width}.png`, `drawer-count-{0,1}-360.png` and `drawer-legacy-360.png`; synthetic local QA provenance only, not production evidence.

The sole material finish finding, clipped selected-language text, is resolved in the scoped language layout. Detector suggestions about incumbent compact type and unresolved Jinja stylesheet paths are advisory, distinct from verified findings. Documenter checked the drawer CSS, Agent/Chat templates and navigation/utility/icon partials against the incumbent design/context files. Pre-existing `design-sidecar-stale` (root design newer than sidecar) and `config-build-path-unset` are recorded without repair or canonization. Existing Deliberate Orange, Actual Work and Content Before Chrome rules remain applicable; no global design/context files were rewritten.
