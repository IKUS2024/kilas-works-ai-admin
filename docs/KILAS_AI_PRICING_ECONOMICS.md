# Kilas AI pricing economics

Verified 2026-09-29. This model applies only to Kilas AI. USD/IDR **17,000** is a conservative planning assumption, not a quoted live exchange rate. Prices are Indonesian rupiah per 30-day paid period. Existing production usage consists mainly of small QA calls, so it is a sanity check, not a demand forecast.

## Provider choices and source prices

| Use | Primary | Fallback | Reasoning | Official standard rate |
|---|---|---|---|---|
| Fast | `gpt-6-luna` | None: Claude Haiku costs roughly 10× more | none | $0.10 input / $0.50 output per million tokens |
| Smart | `gpt-6-sol` | `claude-sonnet-5` | medium | Both $2 input / $10 output per million tokens |
| Expert | `gpt-6-sol` | `claude-sonnet-5` | high | Both $2 input / $10 output per million tokens |
| Web | `gpt-6-luna` with one required web-search call | None | none | $10 / 1,000 tool calls plus model tokens |
| Image generation/edit | `gpt-image-2`, 1024×1024, low | None | n/a | $0.006 output image for low square, plus input tokens |

Model IDs and rates: [OpenAI models](https://developers.openai.com/api/docs/models), [OpenAI API pricing](https://developers.openai.com/api/docs/pricing), [OpenAI image pricing](https://developers.openai.com/api/docs/guides/image-generation), [Claude model catalog](https://platform.claude.com/docs/en/models/overview), and [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing). The account's actual access to new model IDs must be confirmed by live requests before declaring release complete. GPT-4.1 and GPT-4.1-mini are rejected by the new Kilas AI router, even if stale environment variables still name them.

## Final prices and customer quotas

| Plan | Price | Fast | Smart | Expert | Web | Images (generate + edit) | Generated PDFs |
|---|---:|---:|---:|---:|---:|---:|---:|
| Free | Rp0 | 5/day, 100/month | 3/month | 0 | 1/month | 1/month | 2/month |
| Plus | Rp69,000 | 400 | 17 | 3 | 6 | 5 | 20 |
| Pro | Rp149,000 | 900 | 37 | 7 | 12 | 10 | 50 |
| Max | Rp299,000 | 1,800 | 73 | 15 | 25 | 20 | 100 |

Paid quotas apply to each 30-day subscription cycle. A PDF also consumes one chat call at the user's selected mode; no expensive mode switch is forced. Web similarly consumes one chat call and one web allowance. Image generation and edit share one allowance. The existing burst/hour rate limits remain. The UI displays these exact limits, with no unlimited claim.

## Scenario model and safety margin

The expensive-use estimate assumes **10,000 input tokens per text call**, the configured maximum visible-plus-reasoning output budget of 800 Fast / 1,600 Smart / 2,400 Expert tokens, $0.012 per Web operation (one $0.01 call plus Luna tokens), **$0.04 per image** including image-edit input, and $0.001 per generated PDF for local rendering/storage. These are intentionally above ordinary short-message cost; unusual longer or more expensive calls are covered by the paid-period cost guard. It also double-counts some Web text because Web calls consume a chat quota.

| Plan | Revenue at Rp17k/USD | 100% expensive-use estimate | % of revenue | 85% heavy-use estimate | Estimated gross margin at full quota, before infrastructure |
|---|---:|---:|---:|---:|---:|
| Plus | $4.06 | $1.596 | 39.3% | $1.357 | 60.7% |
| Pro | $8.76 | $3.494 | 39.9% | $2.970 | 60.1% |
| Max | $17.59 | $7.008 | 39.8% | $5.957 | 60.2% |

At 18% Fast/Smart quota use, 10% Expert, 25% Web/PDF and 20% image use with normal shorter requests, provider cost is about **2.6%** of revenue. This is a scenario, not a promised average. The 85% expensive-use scenario is about **33–34%** of revenue. Adding a 10% retry/provider-cost buffer and a 3% payment-fee buffer to the full-quota estimates leaves roughly **53%** before Render, PostgreSQL, storage, bandwidth, support and tax. We retained the existing prices and reduced expensive quotas first.

The internal guard records known provider/model tokens, a $0.01 Web call, a conservative $0.04 image estimate, and $0.001 PDF overhead. It warns internally around 25% of paid revenue and blocks further premium/tool reservations above the configurable `KILAS_AI_COST_HARD_RATIO` (default 45%); ordinary paid Fast chat remains available within its stated quota. Free has a configurable $0.15 monthly safety cap. `KILAS_AI_USD_IDR`, `KILAS_AI_COST_HARD_RATIO`, and `KILAS_AI_FREE_COST_CAP_USD` are server-only settings. Customers see normal package-limit wording, never Kilas provider costs. If a new model has no verified cost estimate, it must not silently become an eligible fallback.

## Implementation notes

Text context remains bounded and generated PDF source content is reintroduced only when the user edits that document; it is not resent on every unrelated turn. The PDF renderer uses existing ReportLab infrastructure and persistent account-owned attachment storage. Invalid requests are rejected before quota reservation. A provider/network failure retains the existing failed-reservation semantics. Payment verification and plan activation are unchanged.
