# Compact Subscription preview

Based on `d50e17ef4ab4398a51c55955f24aaa7be7193b09`.

Removed the tagline, service-terms sentence, plan introductions, feature descriptions, repetitive proposal/tagline badges and billing explanation. One short translated notice states that proposed quotas are not active; the payment warning is shortened to Preview only / Do not transfer. Existing current-plan context, feature names, numeric counts, prices, Bank Mega details, disabled payment controls and legacy billing link remain. Counts explicitly use translated uses/day and uses/month, with singular grammar; no durations or entitlements are invented. Retired scoped copy/styles were removed.

Validation: seven route/billing tests passed, including real effective-plan defaults and stored-record preservation. Twenty Chromium cases across en/id/es/zh and 320/360/393/834/1440px passed: compact cards, absent descriptions/badges, translated counts, selected language, exact bank details, inert payment, repeated open/close, Escape, Back/Forward, reload, legacy link, no overflow/console errors/write requests. Mobile393 and desktop1440 screenshots were visually inspected in all four languages. Local screenshots/report: `/tmp/subscription-compact-review`. `git diff --check` passed.

Presentation-only: no backend, entitlement, payment, Finance, configuration or data changes. Client Hub only is the eventual release target; standalone Creative is unchanged. Merge/deployment held pending parent review and final-head CI classification.
