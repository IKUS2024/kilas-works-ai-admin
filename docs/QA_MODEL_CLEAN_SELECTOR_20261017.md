# Clean model selectors and provider colors — 2026-10-17

Removed the persistent size/USD line below the centered model controls, all Chat dropdown explanatory footer prose, and all image dropdown pricing/token/description footer prose. Normal dropdown choices retain provider icon, model name and selection checkmark; actionable unavailable/error notices remain. Model selection, authenticated account preferences and per-conversation behavior are unchanged.

The same image pricing/settings/rates remain available in a collapsed “Estimasi biaya gambar” preview beside the composer, outside the selector/header. Expanding it discloses the configured output estimate plus variable input/reference/thinking charges. This adds no approval gate, inference, new routing, billing change or fixed total-cost promise.

Local Claude and Gemini assets use their documented Simple Icons colors (#D97757 and #8E75B2). The icon source metadata cites the official provider sites. OpenAI remains monochrome as required by its brand guide; a neutral white backing preserves contrast. All provider marks share 17px geometry and 3px clear padding, accessible provider labels and local cache-busted URLs. See static/provider-icons/README.md for provenance.

Validation: JavaScript syntax and diff checks passed. 18 real Chromium cases passed over Home, modern Chat and legacy Chat at 320/768/1440 pixels under light/dark browser preferences. Verified no USD/pricing/explanatory prose in normal selectors/header, no visible USD on the collapsed page, provider labels/icons/checkmarks, centered controls, no horizontal overflow, and expanded composer estimate showing the selected Gemini Pro image’s unchanged $0.1344 configured output estimate, 1024×1024 settings and input/thinking rates. The existing application light theme was preserved; dark browser preference checks verify stable icon backing and loading, not a new application dark theme. Screenshots were visually reviewed. No paid inference or provider request was dispatched by the executor.

Separate read-only synthetic browser smoke reconciliation:

| Thread | Requested/returned exact model | Input / output | Recorded USD | Conservative supplier USD | Repair / top-up debit rows |
| --- | --- | --- | ---: | ---: | --- |
| 137 | claude-sonnet-5-5 | 2049 / 524 | 0.009338 | 0.0102718 | 0 / 0 |
| 138 | gemini-3.8-flash | 1225 / 1471 | 0.006435 | 0.011583 | 0 / 0 |

Both requests COMPLETE, finish stop, BASE quota, no cache/write tokens. Browser operator reports the expected JSON extraction/arithmetic and correct Python divmod code. Cumulative recorded test cost is $0.026402; conservative allowance $0.043052905, rounded reserve $0.0431. Release Sonnet $0.48 and Flash $0.94 reservations. Existing Opus $1.89 bound plus $0.0431 equals $1.9331, within the existing $2 authorization. Proposed $6 budget remains pending; no reliance on it. No further inference dispatched here.
