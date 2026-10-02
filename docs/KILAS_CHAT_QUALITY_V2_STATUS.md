# Kilas Chat Quality V2

Built from production/main `a0851ed7c6c1aec337b9fbd394442692f553e917` (PR #113) on `feature/kilas-chat-quality-v2-20261002`. Proposed only: no merge or deployment. No Work V2, connector, scheduler, worker, migration, Finance, billing, quota or navigation implementation was edited.

## Reasoning and model policy

| Chat class | Before | After | Completion token ceiling |
| --- | --- | --- | --- |
| QUICK, including “halo” and translation | Luna / none | Luna / low | 600 |
| NORMAL | Luna / low | Luna / low | 1,000 |
| DEEP / analytical | Luna / medium | Luna / medium | 1,500 |
| Guard-triggered repair | Not available | Luna / medium | Up to 1,500, tightened by fair use |

HEAVY caps completion at 1,200; VERY_HEAVY and PROTECTION at 1,000, unchanged. No normal model Chat path has `none`, high or an expensive fallback. Existing environment validation rejects a non-Luna Chat model. A provider outage returns the existing calm retry message and never upgrades to Sol. Search retains its existing configured Web model and actual tool path; its former `none` setting becomes low for a quick search or medium for research. The existing research synthesis remains medium. Image generation uses the existing image tool, not the text Chat model.

Reasoning classification now understands informal Indonesian recommendations (`menurut lu/lo`, `mending`), comparisons (`bandingin`), strategy, planning, multi-constraint requests, business cost decisions and diagnostic language (`kemungkinan salahnya`, SQL/debugging). Obvious short references inherit the recent analytical user context. Extracted attachment evidence does not masquerade as a new user intent. No hidden classifier call or cosmetic delay is added. Processing labels reflect the real tier or actual tool/attachment operation.

## Compact quality standard

The Chat system prompt is **2,997 characters**, approximately 750–1,100 tokens depending on tokenizer/language. There is one named `CHAT_QUALITY_STANDARD`, composed into the compact Chat prompt; the shared Search/Automation style is retained.

It covers direct answers, natural Indonesian and multilingual tone, useful depth, practical business decisions, disciplined diagnosis, uncertainty, current-information honesty, capability/action honesty, transformations, arithmetic, Markdown and code formatting. A private final check reviews actual intent, corrections, unsupported claims, depth and necessary clarification. It does not request or expose chain of thought.

The 210 evaluation conversations are fixtures, never injected into API prompts. No summarizer call is made per turn.

## Context and corrections

Existing fair-use context budgets remain: NORMAL 12 recent messages / 18,000 characters; HEAVY 10 / 14,000; VERY_HEAVY and PROTECTION 8 / 11,000. The complete current user question and existing bounded multimodal attachment handling remain authoritative.

Older context is extractive, cached by the existing store, capped at 3,000 characters. Whole quotes are selected by correction priority, active constraint/decision priority and recency, then presented chronologically. Informal markers include `maksud gw`, `yang tadi salah`, `ganti jadi`, `eh bukan`, `sebenarnya` and changes of mind. Secret-like material is excluded. Duplicate wording retains its **latest occurrence**, so reverting to an earlier decision is not accidentally moved before a correction.

The model contract explicitly prioritizes latest corrections over conflicting older wording. Tests prove preservation, ordering and prompt instructions; they do not prove that every live model answer semantically obeys them. Bounded extractive context may eventually lose old facts and does not infer a structured truth database from arbitrary language.

## Structural guard and repair

`chat_quality.py` guards ordinary Chat send and regenerate only. It catches empty replies, obvious private implementation leakage, raw markup substituting for an artifact, placeholders, identical repeated paragraphs, excessive URL dumps, unsupported completed-action/Web claims and completion-limit truncation. DEEP requests flag only clearly unusable tiny answers, with exemptions for explicit brevity and short follow-ups. Code fences survive explicit code requests. Quoted transformation tasks are exempt from fake-action/Web claim matching.

This is a conservative structural check, **not** a semantic truth evaluator. Natural-language patterns are necessarily incomplete; normal factual accuracy still depends on the model, evidence and routing.

Good ordinary prose streams immediately and uses one API call. Visual/file-risk prose is buffered until validation. A broken streamed answer emits a reset event, which clears its transient text before repair or the existing error state. This is the only Chat UI change; no redesign or fake delay.

Only a guard-detected broken completed answer with reported usage can request one repair. The original attempt is finalized and charged as failed before an independent retry reservation. The repair uses the existing atomic quota, burst, concurrency, sustainability and top-up checks, with a separate `:quality-retry` operation key. Its actual usage is settled separately even if it fails or is interrupted. The route does not finalize the first attempt twice. Retried context/output is tightened to the latest fair-use level.

Provider transport failures do not trigger a quality repair. Missing initial usage denies repair rather than enabling a zero-cost extra call. A second invalid output is cleared and returns the calm error: there is no third call. Retry stays Luna / medium; no Sol fallback is introduced. Usage metadata on the assistant represents the initial attempt; the authoritative usage ledger contains each attempt separately.

## Routing and compatibility

PR #113 image/PDF/Work boundaries and last-resort visual guard are retained. Small Chat corrections prevent general capability questions from authorizing image/PDF execution, distinguish text rewriting from image edits, and distinguish `cari kemungkinan salahnya` from an internet search. Existing price/capability discussion remains Chat. Explicit current-fact requests keep Web priority even when phrased as discussion (`jelaskan berita terbaru`, `menurut lu harga ... sekarang`). Explicit code stays code; actual creation still routes through real tools.

PR #111 retail mapping (PLUS / Rp99,000), thresholds, sustainability ceiling, paid Chat marketing, QA identity/expiry, burst/concurrency, tool limits and security are unchanged. Existing failed billable calls still count toward the cost ceiling. The QA exemption is neither extended nor broadened.

## Evaluation and test evidence

- **210 fixtures**, all with multi-turn prior context; 150 new fixtures additionally carry explicit ordered turns and reasoning/tool traits. Thirty new scenario families have five concrete instances each, alongside 60 existing cases. These are regression/evaluation inputs, not model training or evidence of universal quality.
- New focused suite: **18 tests**, including analytical examples, attachment-intent separation, guard exemptions, streaming, one metered repair, no third call, provider failure, fair-use/burst denial, correction ordering, decision reversal, bounded context, corpus traits and both send/regenerate integration.
- **283 passing deterministic tests across 22 suites**: quality (18), cost/fair use (35), Chat (8), routing (3), natural style (7), foundation (5), tools (13), PDF (4), attachments (6), usage (5), billing (2), top-ups (5), single plan (4), Agent (9), Automation (17), connectors (32), autonomous agent (47), intent boundaries (10), Agent results (18), Work documents (22), Finance baseline (4), Assist connections (9).
- Chromium Chat browser suite passed at **320 / 360 / 390 / 820 / 1440 px**, covering normal replies, streamed text, actual analysis/document labels, Search, image, PDF, uploaded content, repair/reset, exhausted repair error, overflow and mobile focus. Tools/providers are mocked; this proves browser integration, not production provider quality.
- Existing composer browser coverage passed at the same five widths for pointer/touch behavior, response completion, viewport stability, Shift+Enter and Stop. The unchanged Work composer was tested only as regression evidence.
- The existing autonomous browser suite also passed at 1440 / 820 / 390 / 320 px for panel/detail, lifecycle controls, unread state and overflow; no Work implementation was edited.
- Four existing code-sandbox execution tests fail in this container because bubblewrap namespaces/network namespaces are restricted (`/proc/.../ns/ns` or NETLINK_ROUTE permission errors). The same four tests fail on unmodified production/main. No sandbox/security implementation was changed to work around the environment.
- A dedicated PR workflow runs Chat regressions and browser coverage. The live evaluation script is never referenced in CI/deploy.

## Manual model acceptance and cost impact

`client-hub/scripts/kilas_chat_live_quality_eval.py` is manual only, requires `KILAS_CHAT_LIVE_EVAL=I_ACCEPT_LUNA_API_COST` plus explicitly configured credentials, rejects CI/Render, uses Luna only, limits the run to 20 representative cases and prints structural flags/usage without secrets or full replies. It was **not run**. Its results are explicitly labelled manual acceptance, not deterministic proof of correctness.

Typical replies remain one call. QUICK reasoning moves none → low at the same 600 completion-token ceiling; NORMAL/DEEP ceilings remain unchanged. Broader analytical classification can move a formerly NORMAL answer from a 1,000 to 1,500 completion ceiling. Reasoning tokens consume the same provider completion budget, so useful visible output and latency depend on actual provider behavior.

Illustrative economics using the repository's configured default Luna rate of $0.50 per million output tokens (not a verified live pricing quote): an additional 100 billed output/reasoning tokens costs $0.00005, about Rp0.85 at the existing Rp17,000/USD setting. The 500-token analytical ceiling difference is at most $0.00025 / Rp4.25 in additional output cost per such call, before context/input changes. Exact average uplift and repair rate need manual/provider telemetry; no invented percentage is claimed. A repair can add one bounded Luna call, including its input cost. The fixed sustainability protections still apply.

## Work V2 coexistence and merge readiness

None of the explicitly forbidden Work V2 templates, CSS, routes, autonomous store/runner, workers, scheduler, connectors or migrations were edited. Main remains the PR #113 baseline at the time of implementation. Shared Chat policy/provider/Search modules necessarily affect callers using those modules, so existing Agent/Automation/autonomous regression suites were run.

A read-only attempt to inspect PR #114 for overlapping files was rejected by automatic approval review because the user instructed not to touch that PR. No workaround was attempted. Therefore exact conflicts against the evolving Work V2 branch are **unverified**. This PR is isolated and tested against current main, but it cannot be declared safe to merge after Work V2 until its final base/diff and CI are rechecked. It remains unmerged and undeployed.

## Owner acceptance questions

1. “halo” uses real reasoning: **yes, Luna low**.
2. Business/strategy/debugging use deeper reasoning: **yes, Luna medium**.
3. Normal Chat can use reasoning none: **no**.
4. Normal Chat silently upgrades to Sol: **no**.
5. Every bad answer causes another call: **no; only a completed structurally broken output can request one guarded repair**.
6. Repair can use Sol: **no; Luna medium only**.
7. 200+ examples are injected per request: **no**.
8. Latest user correction overrides older context: **yes, by priority/order and the runtime contract; live semantic acceptance remains to be checked**.
9. PR #111 fair-use protections preserved: **yes**.
10. Work V2 implementation modified: **no**.
