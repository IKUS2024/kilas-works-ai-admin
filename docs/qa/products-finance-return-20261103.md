# Products catalog return from Finance

Base: main 63df65bc787b90e913db96bbb30977fc16723936.

The selected-Finance session allowlist omitted `products.catalog`, so an ordinary owner who opened an existing Finance workspace received a 303 back to the Finance chooser. The change permits that single authenticated, read-only discovery endpoint. It does not clear the selected product or expand Finance, account, entitlement, CSRF or tenant access.

Validation:
- New existing-owner regression failed with the observed 303 before the fix; passes afterward.
- Catalog, sidebar product navigation and Finance onboarding: 12 tests pass.
- Paid AI lifecycle (run separately): 8 tests pass on both unchanged reviewed baseline f25411b and this fix. Combining its legacy fixtures with the navigation modules causes seven fixture-contamination failures; independent execution passes.
- Chromium at 390px and 1440px: existing Finance selection, chooser sidebar Products via keyboard, repeated Back/Forward and refresh, direct catalog URL, Creative Services return, intercepted official Shotcut popup with null opener, Home draft preservation, logout interruption: pass.
- Finance business/account/transaction snapshots unchanged; missing CSRF, foreign business access and unrelated selected-Finance redirects remain denied.
- `git diff --check`: pass.

Browser evidence: `/tmp/products-finance-return-qa/results.json` and `catalog-from-finance-{390,1440}.png`; CI uploads these alongside the existing catalog artifacts. No production mutation, installer download or paid provider call.
