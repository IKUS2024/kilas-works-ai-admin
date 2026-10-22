# Home example-card removal - 2026-10-22

User explicitly requested removal of only the three example cards: Promotional script, Product image and Summarize a document. Baseline3a8fecc250a9234772d2889f1d85f46c220c666c.

Remove the shared starter partial from the normal and agent Home welcomes. Keep logo/greeting, model selectors, bottom composer and AI Chat/Translator/Voice Over tabs. A Home-only last-child margin keeps the remaining logo/greeting centered after the cards are absent; cache key updated. No shared handoff JavaScript, provider, model, backend, Finance, account or other product feature is changed. The unused starter partial/styles remain to avoid unrelated cleanup.

Acceptance updates require zero starter nodes, retained logo/greeting and tabs, normal typed drafts/attachments, composer at viewport bottom, populated transcript scrolling, short/tall and focused keyboard resize, two Android-like visualViewport-only focus/blur cycles and navigation. Existing mocked Chat-to-VO and Library/VO/credits/Creative regressions remain. No paid calls. Actual Android/iOS hardware is not controlled. Exact commit, CI, deployment and production checks are recorded separately after verification.
