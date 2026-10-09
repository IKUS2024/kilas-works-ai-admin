# Professional conversation comparison — synthetic, offline

The ten cases in `kilas_ai_professional_pairs.json` are **curated evaluation pairs**, not fine-tuning, measured model answers or material loaded into production prompts. Five include prior turns; the rest test a complete first request. Good answers illustrate an acceptable result, not mandatory wording. Bad answers illustrate omission, context loss, unsupported certainty or invented evidence/actions. Every factual reference is supplied synthetic context or an elementary calculation; example-domain links must never be treated as real research.

Review a candidate against the latest user request, supplied facts and earlier constraints. Score each dimension 0–2, recording a short reason and the affected claim or omitted part. Use meaning, not lexical similarity to the good answer.

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Factuality | Wrong supplied fact/calculation or fabricated document contents | Material ambiguity, unit confusion or partly unsupported claim | Supplied facts and calculations correct; assumptions identified |
| All requested parts | Main requested output or multiple parts missing | One requested part materially incomplete | Every requested part covered at useful depth |
| Context and corrections | Wrong selected option, ignored correction/preference, or asks for known facts | Preserves some context but drops a material constraint | Latest correction wins; relevant option, constraints and language preference retained |
| Source and action honesty | Invented citation, search, file read, completion or unavailable current fact | Missing provenance/coverage caveat or overstates certainty | Actual evidence and scope attributed; missing/current data and action status explicit |
| Actionable completeness | Reassurance/generic advice substitutes for requested reasons, steps or result | Some useful detail but unclear next step or reviewable outcome | Specific reasons/steps/outcomes when requested; necessary missing input stated |
| Adaptive language and length | Wrong language, ignores explicit brevity, forced slang or robotic filler | Understandable but unnecessarily long/short or awkward tone | Natural requested language/formality; enough detail without padding or excessive questions |

A simple numerical answer can receive 2 for actionable completeness when only the result was requested. More words do not imply higher quality. For P003/P008, several terse generic sentences do not replace requested reasons, risks or daily outcomes. A current-data abstention is successful when it honestly explains the boundary and offers the next verifiable step; it need not invent a number to be useful. Avoid generic disclaimers on unrelated static questions.

Treat invented sources/actions, dangerous unsupported advice and ignored material corrections as hard failures; do not average them away. Report counts per dimension, omitted requested parts, incorrect supplied facts, false source/action claims and unnecessary abstentions separately. No observed pass rate or model-equivalence claim exists for this dataset.

`kilas_ai_conversation_eval.py --professional` performs only fixture-specific required-part mentions, exact known-bad patterns, URL provenance and explicit length/question-limit checks. It cannot establish semantic factuality, citation entailment, language quality or resistance to prompt injection. A correct paraphrase may be flagged, and a wrong answer that includes keywords may pass. Human review remains required. The script uses no provider APIs, credentials, customer data or semantic judge calls.

Example offline use: create a JSON object mapping `P001`…`P010` to candidate strings, then run:

```sh
python client-hub/tests/kilas_ai_conversation_eval.py --professional /tmp/synthetic-responses.json
```

For separately authorized live QA, start with these ten cases twice (20 conversations), preserve model/tool access and dates, and review randomized outputs without model labels. Each fixture ends with a single scored request; do not import the curated good answer as conversation history. Score real sources against independently checked facts; supplied example-domain sources remain simulation fixtures. Add the reliability audit's high-stakes cases before release. No customer histories or production submissions.

Budget plan: require an owner-approved dollar ceiling and verified rates for every configured model/tool before any call. Reserve conservative worst-case input/output/tool/repair cost before admission, use existing output/tool limits, count failed/unknown-usage requests against the reservation, and stop before the aggregate ceiling would be exceeded. No automatic extra sampling or semantic-judge calls. Provider budget alerts are not assumed to be hard limits. Measure tokens/cache/tool/repair counts and latency alongside human quality; no current prices or savings are asserted here.
