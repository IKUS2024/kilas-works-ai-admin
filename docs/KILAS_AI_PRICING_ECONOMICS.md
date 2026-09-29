# Kilas AI pricing economics

Verified 2026-09-29. This model applies only to Kilas AI. USD/IDR 17,000 is a planning assumption, not a live exchange-rate quote. Production usage so far is mainly short QA calls, so the scenarios below are assumptions rather than observed demand.

## Models and verified rates

The server routes ordinary Chat to `gpt-6-luna` with economical reasoning and clear complex work to `gpt-6-sol` with medium reasoning. Sol retains one same-class `claude-sonnet-5` fallback; Luna has no costly fallback. Search makes one real Web Search call on Luna by default, or Sol for complex searches. Image generation and edit keep `gpt-image-2` at low quality. The existing PDF renderer remains local after Luna/Sol prepares its text.

Published standard token rates are $0.10 input / $0.50 output per million tokens for Luna, $2 / $10 for Sol and Sonnet 5, and $10 per 1,000 Web Search calls plus model tokens. Low-quality square `gpt-image-2` output is listed at $0.006; input, editing, and size may increase the actual image charge, so the planning reserve remains $0.04 per image. Sources: [OpenAI API pricing](https://developers.openai.com/api/docs/pricing), [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation), and [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing). The $0.001 local PDF rendering/storage figure is an internal planning allowance, not a provider quote. Runtime estimates use known token rates plus one Search/PDF overhead per action; unknown model costs remain unestimated, rather than assigned an invented rate.

## Launch plans and accounting

| Plan | Price / period | Chat | Free daily Chat | Search | Image generate/edit | Generated PDF |
|---|---:|---:|---:|---:|---:|---:|
| Free | Rp0 | 100 / calendar month | 10 | 3 | 2 | 10 |
| Plus | Rp69,000 / 30 days | 600 | — | 15 | 20 | 75 |
| Pro | Rp149,000 / 30 days | 1,500 | — | 40 | 50 | 180 |
| Max | Rp299,000 / 30 days | 3,000 | — | 80 | 100 | 350 |

One Chat or uploaded-file analysis consumes one Chat; Search consumes one Search; generated/edited image consumes one Image; generated PDF consumes one PDF. Search/PDF no longer also consume Chat. Historical paired ledger rows are retained but their companion Chat rows are excluded from new visible Chat totals. Invalid requests reserve nothing. All paid plans use the same automatic model routing.

Phase A raises the internal image generate/edit fair-use limits to Free/Plus/Pro/Max 2/20/50/100 and generated-PDF limits to 10/75/180/350. These numbers are configuration-driven through `KILAS_AI_FAIR_USE_JSON` and are not advertised on customer plan cards. Verified Kuota Kilas top-ups (Mini Rp19,000, Extra Rp39,000, Power Rp79,000) add an account-owned cost allowance at 30% of purchase revenue using the planning FX. They expire after 90 days, survive subscription renewal, and are consumed earliest-expiry first only after an applicable base allowance or premium guard is reached. Manual transfer proof alone grants no credit.

## Scenario estimates

Assumptions per Chat: Luna 2,500 input + 500 output tokens ($0.0005); Sol 6,000 input + 1,200 output ($0.024). Search averages $0.0105 including tokens, Image $0.04, and PDF $0.0015 including Luna text plus local rendering. A 10% retry/provider buffer is included in totals. These are sensitivity estimates, not bills; larger context, output, search tokens, edit inputs, and infrastructure can cost more.

“Normal” uses 20% Chat, 25% Search, 20% Images/PDF, with 2% Sol Chat. “Heavy” uses 70% of all quotas with 5% Sol Chat. “Full” uses every quota with 5% Sol Chat. Fractional tool counts are expected-value arithmetic.

| Plan | Revenue at Rp17k/USD | Normal cost / revenue | Heavy cost / revenue | Full cost / revenue |
|---|---:|---:|---:|---:|
| Plus | $4.06 | $0.36 / 9.0% | $1.60 / 39.4% | $2.28 / 56.2% |
| Pro | $8.76 | $0.91 / 10.4% | $4.01 / 45.7% | $5.72 / 65.3% |
| Max | $17.59 | $1.82 / 10.4% | $8.00 / 45.5% | $11.43 / 65.0% |

At 100% Free quota with Luna Chat, the same assumptions yield about $0.137 including buffer. Heavy and full paid scenarios exceed the 35% premium/tool hard guard, so they represent unconstrained demand rather than permitted base-plan spend. Ordinary economical Chat remains available within its published Chat allowance when the premium/tool guard trips. Internal warning starts around 25% of plan revenue. Payment fees, Render, PostgreSQL, storage, support, and tax are outside these provider/tool ratios.

The cost guard uses recorded estimated provider/tool spend per user and paid cycle, with a forecast before costly operations. Existing burst/hour limits remain. Phase A adds migration 0073 for account-owned top-up orders, credits, debits, and a BASE/TOPUP usage marker; existing payment records and historical usage remain intact.
