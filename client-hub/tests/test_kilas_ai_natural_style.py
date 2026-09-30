"""Focused regression checks for Kilas AI's shared natural response policy."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kilas_ai import providers, response_style  # noqa: E402


class NaturalResponseStyleTests(unittest.TestCase):
    def test_chat_system_uses_shared_adaptive_style(self):
        self.assertEqual(providers.SYSTEM, response_style.CHAT_SYSTEM)
        for phrase in (
            "naturally match their level of formality",
            "Avoid canned openings",
            "Do not be artificially terse",
            "Keep continuity with the conversation",
        ):
            self.assertIn(phrase, providers.SYSTEM)

    def test_search_and_automation_keep_explanation_without_robotic_brevity(self):
        search = response_style.search_instructions("2026-09-30", "Answer directly.")
        automation = response_style.automation_task_prompt(
            "Bikinin itinerary Bali 5 hari yang santai.", "2026-09-30"
        )
        self.assertIn("Do not be artificially terse", search)
        self.assertIn("cukup lengkap dan berguna", automation)
        self.assertNotIn("secara ringkas", automation)
        self.assertIn("Bikinin itinerary Bali 5 hari yang santai.", automation)


if __name__ == "__main__":
    unittest.main()
