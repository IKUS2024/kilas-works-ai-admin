# Subscription presentation revision

Based on main `09ebf5a6a5050323f6f0f87e506654414de5a94c`. Release remains held for combined coordination.

- The inert Bank Mega preview shows the user-supplied account name and number exactly. Copy, upload and submission remain unavailable; the preview explicitly says not to transfer funds.
- Current plan uses the route's existing `subscription=usage.effective_plan(user_id)` context. That read model returns the stored plan only for ACTIVE subscriptions within their period, otherwise FREE. No route, service, database, entitlement or configuration changes. Active PLUS/PRO/MAX retain their own names in a separate current-plan summary; proposed quotas remain separate from active allowances.
- All page/payment text is translated for en/id/es/zh in the isolated `_subscription_copy.html` template using the existing `ui_language()` cookie selection. The shared profile menu uses the existing Subscription locale key. No shared locale catalog or translation engine edits.
- Terminal periods are removed from short labels/headings; prose, numeric values, currency and account identifiers are preserved. Number grouping follows the selected language. Existing legacy billing remains linked.

Validation: 20 Chromium viewport/language cases at 320/360/393/834/1440px passed, including repeated payment open/close, Escape, browser history/reload, selected language, exact account details, disabled controls, no horizontal overflow, no console errors and no write requests. Seven application route/billing tests passed, including active PLUS/PRO/MAX, missing/expired/cancelled/future entitlements and unchanged stored records. Screenshots/report are local at `/tmp/subscription-revision-review`; mobile and desktop screenshots were visually inspected. Broader production visual verification is reserved for the coordinated release.
