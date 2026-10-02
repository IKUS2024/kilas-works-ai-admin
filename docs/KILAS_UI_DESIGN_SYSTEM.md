# Kilas Works customer UI — white workspace V1

2026-10-03. Mode: Operate. The approved brief replaces the customer dark theme;
the incumbent implementation remains the authority for capabilities and workflows.

## Direction

A quiet professional workbench: white canvas, warm neutral navigation, precise
typography, readable conversation documents, deliberate Kilas orange actions.
No decorative dashboard metrics, gradients, glass, sparkle graphics or new modes.
Impeccable direction seed f689966e was considered against the pinned brief.
Dark console, map notation and font-specimen directions were rejected because
they would introduce incompatible color or decorative UI. The selected direction
is grounded in the owner's white, calm productivity workspace brief.

## Direction contract

THESIS: A quiet professional workbench that foregrounds actual tasks instead of
generic dashboard cards or synthetic metrics.

OWN-WORLD: White canvas, warm neutral 240px navigation, charcoal text, Manrope,
deliberate orange actions, flat reading surfaces and compact files.

STORY: Home leads into one AI conversation, existing Finance, account settings,
actual Google Connections and external human services. Capabilities stay intact.

FIRST VIEWPORT: Desktop rail left, readable white main, one contextual heading and
primary action. AI history shares the rail; the composer stays below the conversation.
Mobile collapses navigation into the existing drawer convention.

FORM: Code-led implementation of the owner's pinned professional workspace,
grounded candidate 7; direction seed f689966e. No approved raster comp exists.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish
review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Tokens and components

The opt-in `kilas-light` class owns `static/kilas_premium.css`. Assist and admin
do not load the layer. No global dark stylesheet is rewritten.

| Role | Value / behavior |
| --- | --- |
| Canvas / surfaces | `--bg`, `--card`: #fff; `--bg-soft`, `--panel`: #f7f7f6 |
| Text / secondary | `--text`: #202329; `--muted`: #62666f |
| Lines / input borders | #e4e5e7 / #c7c9cd |
| Orange text / action fill | #bd4700 / #e96817 with #22150c text |
| Selected navigation | #fff0e5 with #bd4700 text |
| Success / error | #20704a / #b42330; light tinted backgrounds |
| Typeface | Self-hosted variable Manrope, system sans fallback; font-display swap |
| Type scale | 12 metadata, 13 labels, 14 navigation/actions, 15 body, 16 composer, 18/22 sections, 30 page title; 40 maximum Home heading |
| Weight / measure | 400–500 body, 600 controls, 700 headings, 800 brand; 65–75ch reading measure |
| Spacing | 4/8/12/16/20/24/32/40/48; related controls grouped, sections separated |
| Radius | 8 controls, 12 surfaces/files/dialogs, 14 composer; no all-pill layout |
| Elevation | Flat content; menus/dialogs 0 12px 32px #20232912; composer 0 4px 14px #20232908 |
| Buttons | 44px minimum target; orange primary, white bordered secondary; disabled remains clear |
| Inputs / dropdowns | Visible labels, neutral border, charcoal text, orange focus; browser semantics preserved |
| Dialogs | Native existing dialogs; viewport minus 32px max size, scrolling, Escape behavior retained |
| Navigation | 240px neutral desktop rail; mobile drawer with inert closed content, Escape, focus trap, restore, backdrop |
| Chat | Restrained warm neutral user surface, document-style assistant; no mode selector or Search checkbox |
| Files / images | Existing private downloads and persistent message anchors; compact filename/type/size cards, individual pending remove controls |
| Tables / code | Existing Markdown scroll containers; neutral headings and code surface, no page overflow |
| Empty / loading | Brand and one useful question; existing genuine progress states and skeleton logic remain |
| Focus / hover | Visible 2px orange outline offset 3px; subtle neutral hover; no artificial delay |
| Motion | Small navigation/color transitions only; prefers-reduced-motion disables transitions/animations |

Manrope source and SIL Open Font License are bundled from the
[official Google Fonts repository](https://github.com/google/fonts/tree/main/ofl/manrope).
No third-party font request is made by the application.

## Route map and scope

| Surface | Current routes / implementation |
| --- | --- |
| Authentication | /login, /register, /forgot-password, /reset-password/&lt;token&gt;; OAuth login/status redirects stay unchanged |
| Home | /products/start; existing product selection POSTs; Services externally https://kilasworks.id |
| Canonical AI | /kilas-ai → /kilas-ai/agent; chat, history, preferences, Connections |
| Legacy chat / shared | /kilas-ai?attachments=1, /kilas-ai/threads/&lt;id&gt;, /kilas-ai/shared/&lt;token&gt;; retained direct/history access |
| Background work | Existing /kilas-ai/agent/jobs/&lt;id&gt;, /kilas-ai/automation and its new/edit/results routes; secondary only |
| AI subscription | /kilas-ai/usage, /kilas-ai/invoices/&lt;id&gt;, /kilas-ai/topups/&lt;id&gt; prices/payment forms unchanged |
| Account / settings | /account, /account/bills; existing profile/email/password forms and dialogs |
| Finance entry | /products/finance, /finance, business Finance workspace selection/subscription/bill pages |
| Finance workspace | Existing dashboard, transactions, accounts, budget, operations, payees, invoices/settings/detail, reports, collections, statements, receipts, bank import, assistant routes |
| Legacy services/orders | Existing /products/services, /products/order and customer project/order routes retained; no new Services app page, no normal navigation to internal catalog |
| Protected legacy areas | Assist/Inbox/Customers/Jobs, operator/admin/support, WhatsApp/Meta: retained and not redesigned or added to normal navigation |

Connections uses the existing owner-scoped status read and Gmail connection POSTs.
Only Gmail send is presented. No OAuth permission, credential, tool advertisement
or approval execution change. The previous Connections redirect to preferences is
replaced with a presentation view on the same existing route.

Finance integration is deliberately color-only: white background, light borders,
neutral shell. Existing Finance template structure, form fields, navigation targets,
tables, money and ledger behavior are unchanged. Financial forms retain their sizing.

## Verification contract

Capture desktop and mobile together: 320, 360, 390, 768, 820, 1024, 1440 pixels.
Check real states, long filenames, tables, dialogs, history, contrast, focus, touch
targets and no page overflow. Existing capability browser suites remain authoritative
for streaming, Stop, attachments, Search, images, documents, durable jobs, approvals
and reminders. Controlled fixtures use disposable local data and mocked providers;
they are never presented as live customer activity.

Only Client Hub may be deployed. No Cron/AI Admin deploy, migration, secret or data
reset. Protected production acceptance must be reported blocked if no login exists.
