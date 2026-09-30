# Kilas AI internal conversation QA

`kilas_ai_conversation_curriculum.tsv` contains 100 authored three-turn situations: the first user request, a prior assistant response, and a follow-up. Each row records the desired behavior and one failure pattern. It is evaluation data, not a prompt injected into every production request. `kilas_ai_golden_conversations.tsv` selects 40 important cases for recurring review; the good/bad examples are in `kilas_ai_behavior_examples.md`.

The deterministic `test_kilas_ai_natural_style.py` validates the fixture, the shared policy, and its actual use by Chat, Search, Research, and Automation. It does not call a live model. To inspect a sampled model run separately, save a JSON object mapping Golden IDs to candidate replies, then run `python tests/kilas_ai_conversation_eval.py responses.json` from `client-hub`. The offline checker reports empty replies, known bad phrases, and canned openings. Human review is still needed for nuance, factuality, and whether the reply truly follows context; a string check cannot certify conversational quality.

When a regression is found, add a specific multi-turn case and improve the shared response policy or routing. Keep model outputs out of CI unless they can be checked deterministically. Never add this curriculum to customer navigation or bulk-inject the 100 cases into production prompts.
