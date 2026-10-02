# Kilas AI cost and quality intelligence — 2026-10-02

Branch: `fix/kilas-ai-cost-quality-routing-20261002`.
Base: remote main `8130cdadc1ea6560458d52d6b2abb28176ee872a`, containing deployed PR #110.
State: implemented and locally verified; one focused PR for review. **Do not merge or deploy as part of this task.** No Render environment, production connection, production data or infrastructure was changed.

## Model and reasoning policy

Ordinary Chat, regeneration, attachment discussion, ordinary Agent Q&A, lightweight text workers and final research synthesis use `gpt-6-luna`. Legacy FAST/SMART/EXPERT labels no longer select Sol for the streaming provider. Luna failure returns the existing graceful retry response; there is no automatic expensive fallback. The private Anthropic adapter is retained but is not advertised as a configured ordinary Chat fallback.

Server-owned deterministic tiers:

| Tier | Reasoning | Output cap |
| --- | --- | --- |
| QUICK | none | 600 tokens |
| NORMAL | low | 1,000 tokens |
| DEEP | medium | 1,500 tokens |

Greetings/simple translation/direct explanations use QUICK; ordinary advice/writing use NORMAL; analysis, strategy, debugging, SQL, long documents and material business comparisons use DEEP. These are safeguards, not response-length targets. User-supplied model/reasoning parameters do not select the model. Routine high/xhigh/max reasoning is not used.

Simple autonomous and conversational scheduling plans use Luna with medium reasoning. `gpt-6.1-sol` is selected only for explicit coding/repository/repair work, dependency or multistage sequencing, or a verified failed plan requiring substantive replanning. A simple user edit alone does not promote planning to Sol. The complex planner's existing configured model must match `gpt-6.1-sol`; Astra and old `gpt-6-sol` are not introduced into the new normal Chat/planner policy.

Recurring/continuous work can reinstall its persisted, validated bounded plan after the latest cycle succeeds. Reuse excludes CODE and sensitive external actions, requires all latest-cycle steps to have succeeded, and does not apply to failed/changed/empty plans. Existing install transactions create fresh idempotency keys and preserve fencing, approvals and cumulative max-step limits. Capability availability is still checked by the registered executor. No expensive model call occurs solely because a successful safe cycle wakes again.

## Paid Chat and fair use

Rp99k paid normal Chat has **no numeric monthly message wall**, including SMART-labelled analytical Chat and ordinary Agent Q&A. It does not reserve Chat top-up credit when the old 600/1,500/10,000 message allowances are exceeded. Free Chat and separately metered Search, images, PDF, background work and external tools retain their limits and existing billing data.

Internal cost tiers derive from recorded normal Chat cost within the paid period, including returned billable usage from interrupted calls. Pending reservations use a conservative forecast. Default cost/revenue thresholds: HEAVY 16%, VERY_HEAVY 24%, PROTECTION 30%, with configurable validated exchange rate and ratios. Defaults use existing `KILAS_AI_USD_IDR=17000`; no production env values were changed.

| Cost tier | Recent messages | Text budget | Concurrency | Output restriction |
| --- | --- | --- | --- | --- |
| NORMAL | 12 | 18,000 characters | 3 | normal tier cap |
| HEAVY | 10 | 14,000 characters | 2 | at most 1,200 tokens |
| VERY_HEAVY / PROTECTION | 8 | 11,000 characters | 1 | at most 1,000 tokens |

The complete current user question is retained even when longer than the tightened historical budget, within the existing input limit. Existing burst/hour limits, provider timeouts and idempotency remain. Failed attempts cannot be used to escape burst protection. Cost PROTECTION alone does not permanently block Chat: a temporary slowdown requires both at least 60 normal Chat attempts in the previous hour and 10 in the previous five minutes. Paid users are not sent to buy Chat messages for this throttle. Limits are derived per request; there is no permanent ban or new Redis resource.

Subscription wording now says **Kilas Pro / Rp99.000 / Unlimited AI Chat*** and explains fair use plus separately limited tools. No new model selector or quota counter is exposed. Existing checkout/payment verification and capacity credit data are unchanged.

## QA account

The exact existing user 9/email exemption is preserved, including its existing expiry **2026-11-01 00:00 UTC**. During that grant it bypasses base quotas, paid Chat cost degradation and the existing autonomous daily execution quota. It does not bypass identity matching, request validation, burst/hour limits, concurrency, idempotency, external/Gmail approval, maximum active jobs, step/attempt limits, capability availability or sandbox controls. Its calls remain metered; the email is not added to runtime logs.

## Conversation quality and context

Existing adaptive language, tone, typo/slang handling, continuity, correction priority and useful depth guidance is reused across Chat and Agent. Added explicit resistance to blind agreement, distinction between facts/estimates/opinion, and avoidance of internal model/router terminology. Runtime instruction stays compact and stable. The offline 60-case corpus covers casual/formal Indonesian, English/mixed language, typos, follow-ups, corrections, advice, analytical/coding work, writing, research, uncertainty, capability limits and Agent progress/results. It is never injected into API context.

Ordinary Chat uses bounded recent turns plus an extractive historical note. The note preserves original user wording, selected decisions/constraints and corrections; it invents no facts and skips secret-like messages. It is cached in existing owner-scoped message metadata; earlier notes can be carried forward. Agent Q&A uses the same bounded approach without a new schema. No summary model call, raw prompt logging or migration is added.

The summary is bounded/lossy: it is not a guarantee of unlimited perfect conversation memory. Recent messages and the latest correction remain authoritative. Original full history stays in the existing persistence layer. Agent assistant responses may now retain up to 12,000 characters to support the reasoning/output budget; user input limits remain unchanged.

Activity appears immediately and updates from actual backend work: Menyiapkan jawaban, Menganalisis, source search or task preparation. Streaming is unchanged. **No artificial multi-second sleep or delayed token playback.** PR #110 safe Markdown, task cards, result hierarchy, citations, titles and shared shell remain intact.

Provider/model/input/output/cost remain recorded in existing usage rows. Cached input counts are parsed and used for configured cached-token pricing, and retained in normal Chat response metadata. Normal Chat reasoning tier is stored in existing message metadata; Agent classification is recoverable from existing operation keys. The legacy usage table has no dedicated cached-token/reasoning columns, so Agent Q&A does not gain separate durable columns without a migration. Mixed Search/final synthesis costs are estimated per returned model component rather than pricing all tokens as the final Luna model. Missing model rates remain unknown and use the existing guard forecasts; they are not claimed as verified invoice charges.

## Offline simulation

Run `python client-hub/scripts/kilas_ai_cost_simulation.py`. No real API calls.
Illustrative assumptions: 2,400 input tokens, including 1,200 cached tokens, and 650 output tokens per turn. Existing configured Luna estimates are used; cached tokens are conservatively priced as normal input unless a separate cached rate is configured. This is an unthrottled baseline, not actual user behavior or a claim of current official provider pricing.

| Scenario | Turns/month | Provider estimate USD | Share of Rp99k revenue | Derived tier |
| --- | --- | --- | --- | --- |
| LIGHT | 100 | 0.0565 | 0.97% | NORMAL |
| NORMAL | 500 | 0.2825 | 4.85% | NORMAL |
| HEAVY | 2,000 | 1.1300 | 19.40% | HEAVY |
| EXTREME | 10,000 | 5.6500 | 97.02% | PROTECTION |

The extreme scenario is a real margin risk if sustained at a human-like frequency. Tightened context/output and automated-use throttles reduce exposure, but the ratios are **not guaranteed absolute spending caps**. Owner should review this tradeoff before release. The paid promise does not silently become a numeric message limit to conceal that risk.

## Verification and limits

**241 tests passed across 15 focused suites**: cost/quality 24; Chat 8; usage 5; tools/Search 12; natural style 7; attachments 6; PDF 4; Agent 9; Automation 17; connectors/Gmail approval 32; Agent chat experience 43; autonomous engine 47; PR #110 results 18; single subscription console 4; top-ups 5.

**Seven Chromium browser scripts passed**: PR #110 response/results, Agent chat, Agent, autonomous details, shared shell, normal Chat/subscription/attachments, Automation. PR #110 checks include 320/360/390/820/1440 px, safe stored/streamed Markdown, compact result-first cards and no horizontal overflow. The browser heading assertion was updated for the requested Kilas Pro wording. Existing security assertions are retained.

Old Sol-default/fallback test expectations were updated to the intentional Luna policy. One intermediate browser test edit had incorrect indentation and was fixed before the successful rerun. No unresolved focused test failure remains. No unrelated baseline suite failure was encountered in the tests run; the whole repository suite was not run. PostgreSQL and Linux sandbox checks remain CI gates, not local Windows passes.

The corpus validates the behavioral contract offline; it does not prove live model prose sounds natural on every case. No production model/search request or authenticated production test was performed. The simulation is illustrative. Existing free/tool quota and provider outages can still prevent those separate features. No whole-app redesign or full Impeccable audit was performed.

Diff review: no Finance, Assist, WhatsApp/Meta, Google scopes, Gmail approvals, payment provider code, sandbox changes, schema/migration changes, production data reset or infrastructure changes. `git diff --check` passes. CI includes the new cost/quality tests plus the directly relevant quota/attachment/style/top-up regressions.

Technically ready for PR/CI review. **Do not claim fully safe to deploy until CI (including native PostgreSQL/sandbox) passes and the owner reviews the documented extreme-use margin risk.** A future authorized release should update Client Hub and the existing Cron runner together; no AI Admin deployment, migration or new resource is needed.

## Exact changed files

- `.github/workflows/kilas-autonomous-agent-qa.yml`
- `client-hub/kilas_ai/agent_chat.py`
- `client-hub/kilas_ai/agent_planner.py`
- `client-hub/kilas_ai/agent_response_style.py`
- `client-hub/kilas_ai/agent_store.py`
- `client-hub/kilas_ai/agent_workers/content_worker.py`
- `client-hub/kilas_ai/autonomous_planner.py`
- `client-hub/kilas_ai/autonomous_runner.py`
- `client-hub/kilas_ai/conversation_context.py`
- `client-hub/kilas_ai/conversation_standard.py`
- `client-hub/kilas_ai/fair_use.py`
- `client-hub/kilas_ai/model_policy.py`
- `client-hub/kilas_ai/providers.py`
- `client-hub/kilas_ai/response_style.py`
- `client-hub/kilas_ai/routes.py`
- `client-hub/kilas_ai/store.py`
- `client-hub/kilas_ai/tools.py`
- `client-hub/kilas_ai/usage.py`
- `client-hub/scripts/kilas_ai_cost_simulation.py`
- `client-hub/static/kilas_ai.js`
- `client-hub/static/kilas_ai_agent_chat.js`
- `client-hub/templates/kilas_ai/agent.html`
- `client-hub/templates/kilas_ai/home.html`
- `client-hub/templates/kilas_ai/usage.html`
- `client-hub/tests/fixtures/kilas_conversation_standard.json`
- `client-hub/tests/test_kilas_ai_agent.py`
- `client-hub/tests/test_kilas_ai_automation.py`
- `client-hub/tests/test_kilas_ai_browser.py`
- `client-hub/tests/test_kilas_ai_chat.py`
- `client-hub/tests/test_kilas_ai_cost_quality.py`
- `client-hub/tests/test_kilas_ai_tools.py`
- `client-hub/tests/test_kilas_ai_usage.py`
- `docs/KILAS_AI_COST_QUALITY_ROUTING_STATUS.md`
