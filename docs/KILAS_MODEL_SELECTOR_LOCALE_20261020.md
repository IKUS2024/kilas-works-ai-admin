# Model selector localization — 2026-10-20

Based on main 078d5d1e37160ea649514d2acfa2b38aab8d4d68. Scope is Chat/image
selector copy on Home, thread Chat and agent conversations.

Verified cause: `Pilih model` and `Model gambar` were absent from both server and
client translation catalogs. After hydration, kilas_chat_models.js additionally
wrote hardcoded Indonesian aria-label prefixes, overriding the template label.
Several selector availability/error messages were also absent from client i18n.

Added explicit English, Spanish and Chinese catalog entries; Indonesian retains
source copy. JavaScript now translates the same selector headings used by the
server template. English uses “Choose model” and “Image model”. Model/provider
brand names and selected IDs remain intact. Malformed/network selection failures
use localized recovery text rather than exposing a raw browser error. Existing
localized server validation messages are preserved. Refreshed the selector script
cache version. No CSS/layout, inference, model/pricing, quota or billing changes.

Validation (no paid inference or external provider IO):
- test_kilas_model_initial_render: 14 PASS, including locale/SSR/accessibility and
  localized selector API error tests with brand names retained.
- test_kilas_chat_models: 20 PASS; selection, tenant/CSRF, routing and history.
- test_ui_i18n: 14 PASS; test_ui_i18n.mjs: 4 PASS.
- kilas_model_selector_locale_browser.py: 12 PASS combinations (id/en/es/zh ×
  Home/thread/conversation). Uses real language form, templates and JavaScript;
  checks SSR plus hydrated labels, aria/title/close text, menu status, malformed
  selection response, failed catalog and selected-name preservation. Zero page
  errors. Screenshot and verification JSON under
  /tmp/kilas-model-selector-locale-browser/.

Existing AI Call 078d5d1e and Finance 0f33bb4e are ancestors and untouched.
Production browser confirmation is assigned to parent; execution proxy previously
blocked direct production HTTP. Release proof records exact commit/deploy/LIVE.
