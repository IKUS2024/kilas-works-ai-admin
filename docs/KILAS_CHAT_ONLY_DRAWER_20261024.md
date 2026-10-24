# Chat-only conversation drawer

Supersedes the initial Credits sidebar restyling request. The owner clarified that conversation navigation/history belongs only to AI Chat, not Credits & Usage, Translator or Voice Over. No superseded restyling was deployed.

The shared workspace include now routes audio tool pages and the usage/invoice/topup-invoice views to a simple back-to-Chat/brand/profile header. There is no sidebar markup, hamburger trigger, backdrop, conversation script or rail stylesheet on those pages. Scoped navigation CSS removes reserved rail space. AI Chat's PR158 drawer CSS/JS, conversation records, tool-specific audio history, APIs, balances and billing calculations are unchanged. The inclusion boundary also covers full HTML audio output/history/invoice views without modifying their route logic.

Validation in cloud Chromium: 48 real authenticated navigation flows (six routes, two locales, four mobile/tablet/desktop viewports) verify no drawer artifacts, back-to-Chat open/Escape and return, no horizontal overflow, no POSTs and no page errors. Ten Credits preview interaction/localization cases pass with disabled payment unchanged. Existing Chat mobile drawer/history/keyboard tests pass. Route tests across four locales prove no drawer assets and unchanged exact subscription/invoice/audio-balance/order/topup rows after GETs. Billing and owned-history regression suites pass. Mobile and desktop Credits screenshots inspected locally. No paid provider IO or production financial writes.

Authenticated production browser access is not established in this executor; production verification uses approved Render revision/startup evidence. Physical Android is not tested.
