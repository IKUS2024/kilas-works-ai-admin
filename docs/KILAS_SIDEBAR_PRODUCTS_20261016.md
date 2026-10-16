# Sidebar Products placement

Baseline:3e253e54463d7b5f06f74b106e0659d623718780.

The user explicitly requests Products as a separate sibling immediately below
My Library. Finance is the child of Products. Products is not inside My Library.
The shared sidebar now renders an initially open native disclosure in that
position, followed by the existing Chat/history section. English uses Products,
Indonesian Produk, Spanish Productos and Chinese 产品. The existing singular
product translation is untouched.

Finance is removed from the shared Chat/Translator/Voice Over peer selector.
Its existing POST form moves to Products with the same /products/start action,
product=finance value and CSRF field. Existing authenticated business selection,
tenant access, entitlement and Finance routes/data are not changed. The existing
sidebar draft/attachment navigation guard now protects this form in its new
location. Native disclosure toggling makes no requests and works independently
of the chat-history toggle.

Styles are limited to the conversation sidebar. The same disclosure is used on
desktop and mobile, with44px controls and the existing mobile drawer, focus and
Escape behavior. Chat history continues to scroll in its existing container.
No Finance workspace CSS or runtime code, audio/call modules, credentials,
budgets, data or subscriptions are changed.

Verification uses real Flask-rendered Home, agent and Library pages in four
locales; actual Finance POST/CSRF/owned-business tests; independent history
tests; and jsdom at390/1280px for sibling order, native collapse/expand,
draft-cancel/continue and mobile Escape/focus. Provider and network IO are
blocked in test fixtures. No browser/browser-based QA or paid QA is run.
The existing browser fixture's expected peer list is updated but not executed.
Real-device pixel layout is not certified by jsdom.

An extra legacy test_kilas_workspace.py run fails its historical UI-copy
expectations on the unmodified baseline too. That file is left unchanged;
focused tests exercise the actual Finance handoff and tenant checks directly.
The existing retirement test retains all Learning-denial checks while updating
its peer-selector expectation to the requested Finance placement.

Before/after production verification uses read-only counts and whole-row
fingerprints of30 Finance tables. Exact tested tree, CI/deployment IDs and
comparison results are retained in the external cloud release evidence.
