"""Focused regression checks for Kilas AI's shared natural response policy."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kilas_ai import providers, response_style, tools  # noqa: E402
import kilas_ai_conversation_eval as curriculum_eval  # noqa: E402


class NaturalResponseStyleTests(unittest.TestCase):
    def test_chat_system_uses_shared_adaptive_style(self):
        self.assertEqual(providers.SYSTEM, response_style.CHAT_SYSTEM)
        self.assertEqual(providers.MODEL_TIERS["FAST"]["openai"], "gpt-6-luna")
        for phrase in (
            "naturally match their level of formality",
            "Avoid canned openings",
            "Do not be artificially terse",
            "Keep continuity with the conversation",
            "Do not automatically greet",
            "Do not append a generic follow-up",
            "prefer a few natural paragraphs",
            "yang kedua",
        ):
            self.assertIn(phrase, providers.SYSTEM)

    def test_fast_luna_prompt_is_calibrated_without_forced_slang(self):
        style = response_style.CHAT_SYSTEM
        self.assertIn("bro, weh, kak, gue, or lu", style)
        self.assertIn("do not repeat those forms mechanically", style)
        self.assertIn("generic textbook explanation", style)
        self.assertIn("simple calculation, short translation", style)

    def test_search_and_automation_keep_explanation_without_robotic_brevity(self):
        search = response_style.search_instructions("2026-09-30", "Answer directly.")
        automation = response_style.automation_task_prompt(
            "Bikinin itinerary Bali 5 hari yang santai.", "2026-09-30"
        )
        self.assertIn("Do not be artificially terse", search)
        self.assertIn("Do not append a generic follow-up", search)
        self.assertIn("cukup lengkap dan berguna", automation)
        self.assertNotIn("secara ringkas", automation)
        self.assertIn("Bikinin itinerary Bali 5 hari yang santai.", automation)

    def test_policy_covers_corrections_multilingual_clarification_and_tool_truth(self):
        style = response_style.BASE_STYLE
        for phrase in ("user corrects you", "code-switching", "clarifying question only when",
                       "recommendations, explain tradeoffs", "email, or website action",
                       "preserve constraints that still apply"):
            self.assertIn(phrase, style)

    def test_actual_search_and_research_payloads_use_same_policy(self):
        payloads = []
        def fake_request(payload):
            payloads.append(payload)
            return {"output": [{"type": "web_search_call"}, {"type": "message", "content": [{
                "type": "output_text", "text": "One verified finding [1]", "annotations": [{
                    "type": "url_citation", "url": "https://example.com/source", "title": "Source"}]}]}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}
        with patch.dict(os.environ, {"KILAS_AI_OPENAI_WEB_MODEL": "test-web-model"}), \
                patch.object(tools, "_request", side_effect=fake_request):
            list(tools.web_search_steps([{"role": "user", "content": "Find a current source"}],
                                        mode="FAST", plan="FREE"))
            tools._synthesize_research(["One verified finding"],
                                       [{"title": "Source", "url": "https://example.com/source"}])
        self.assertEqual(len(payloads), 2)
        for payload in payloads:
            self.assertIn(response_style.BASE_STYLE, payload["instructions"])
        self.assertNotIn("Answer this straightforward question concisely", payloads[0]["instructions"])

    def test_internal_curriculum_and_golden_cases(self):
        cases = curriculum_eval.curriculum()
        gold = curriculum_eval.golden()
        self.assertEqual(len(cases), 100)
        self.assertEqual(len(gold), 40)
        self.assertEqual(set(cases), {f"C{number:03d}" for number in range(1, 101)})
        self.assertEqual(len({row["scenario_id"] for row in gold}), 40)
        self.assertEqual({row["category"] for row in cases.values()},
                         {"casual_id", "formal_id", "english", "multilingual", "correction",
                          "recommendation", "technical", "writing", "tools", "automation"})
        for case in cases.values():
            for field in ("first_user", "prior_assistant", "follow_up", "desired", "avoid"):
                self.assertTrue(case[field].strip(), (case["id"], field))
            self.assertNotEqual(case["first_user"], case["follow_up"])
        self.assertTrue(all(row["scenario_id"] in cases and row["regression_focus"] for row in gold))
        self.assertEqual(curriculum_eval.evaluate_candidate(cases["C001"], "Maksud tadi yang mana?"),
                         ["known_bad_pattern"])
        self.assertEqual(curriculum_eval.evaluate_candidate(cases["C001"],
                         "Karimunjawa saja. Kita lanjut dari rencana yang lebih tenang tadi."), [])

    def test_training_stays_internal_and_no_customer_mode_selector(self):
        root = Path(__file__).resolve().parent.parent
        chat = (root / "templates" / "kilas_ai" / "home.html").read_text(encoding="utf-8")
        self.assertNotIn("Conversation Standard", chat)
        self.assertNotIn('name="mode"', chat)
        self.assertNotIn('>Fast<', chat)
        self.assertNotIn('>Smart<', chat)
        self.assertNotIn('>Expert<', chat)


if __name__ == "__main__":
    unittest.main()
