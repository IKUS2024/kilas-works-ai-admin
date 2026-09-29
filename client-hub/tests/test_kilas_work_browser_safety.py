"""Safety guard for public Work browser access and side effects."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kilas_work.browser_safety import BrowserSafetyError, classify_action, require_public_url  # noqa: E402


def public_resolver(host, port, **kwargs):
    return [(None, None, None, None, ("93.184.215.14", port))]


def private_resolver(host, port, **kwargs):
    return [(None, None, None, None, ("10.0.0.2", port))]


class BrowserSafetyTests(unittest.TestCase):
    def test_public_only(self):
        self.assertEqual(require_public_url("https://example.com/", public_resolver), "https://example.com/")
        for target in ("http://127.0.0.1", "https://localhost", "file:///etc/passwd",
                       "http://169.254.169.254", "https://service.internal", "https://user:pass@example.com"):
            with self.subTest(target=target), self.assertRaises(BrowserSafetyError):
                require_public_url(target, public_resolver)
        with self.assertRaises(BrowserSafetyError):
            require_public_url("https://rebind.example", private_resolver)

    def test_handoff_and_irreversible_confirmation(self):
        self.assertEqual(classify_action({"type": "click"}, target_text="Search"), "ALLOW")
        self.assertEqual(classify_action({"type": "click"}, target_text="Pay now"), "CONFIRM")
        self.assertEqual(classify_action({"type": "click"}, target_text="Hapus akun"), "CONFIRM")
        self.assertEqual(classify_action({"type": "type", "text": "secret"}, target_type="password"), "HANDOFF")
        self.assertEqual(classify_action({"type": "click"}, page_text="Enter your verification code"), "HANDOFF")
        with self.assertRaises(BrowserSafetyError):
            classify_action({"type": "execute_shell"})


if __name__ == "__main__":
    unittest.main()
