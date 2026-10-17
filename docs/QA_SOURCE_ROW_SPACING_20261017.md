# Source row spacing

Follow-up to `6a2ca6ac1c510467d044f5de129a50eff57499a7`. Production visual acceptance found the Sources label adjacent to its first source title without a visible separator. Both the saved-message template and streaming renderer append a strong label and anchors with no intervening whitespace, and the active Chat style layer supplied no row gap.

Added two scoped typography rules: source rows use wrapping flex layout with an 8px normal-size horizontal gap and 4px row gap; source links can wrap within the available width. The typography stylesheet URL is cache-busted. Source content, href, target, rel, order, click behavior and all generation/transport logic are unchanged. The existing Finance exclusion remains.

Focused actual Chromium checks pass at 320/360/768/1440px for a saved-message fixture and a dynamically appended row matching streaming markup. Measured first-link gap is 8px, wrapped-row gap is at least 4px, and long unbroken titles do not overflow the row/document. All three links retain exact text, URL, `_blank`, and `noopener noreferrer nofollow`. Saved markup checks, the Finance style-exclusion test, and diff checks pass. Two synthetic row crops were reviewed once.

Evidence: `/tmp/kilas-source-spacing-browser/verification.json`, `/tmp/kilas-source-spacing-browser.log`, `/tmp/kilas-source-spacing-scope.log`. No private production conversation was accessed or copied, no link was opened, and no microphone, paid API, provider generation, schema or data change was used. Authenticated production visual acceptance remains required after deployment.
