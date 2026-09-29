"""Real Chromium Work session isolation, actions and owner handoff in CI."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kilas_work.browser_runtime import BrowserRuntime, BrowserRuntimeError  # noqa: E402


class RealBrowserTests(unittest.TestCase):
    def test_public_site_and_isolated_action_loop(self):
        runtime = BrowserRuntime()
        try:
            opened = runtime.create(101, 9001, "https://example.com/")
            self.assertTrue(opened["url"].startswith("https://example.com"))
            self.assertGreater(len(opened["screenshot"]), 1000)
            with self.assertRaises(BrowserRuntimeError):
                runtime.snapshot(102, 9001)
            page = runtime._sessions[(101, 9001)]["page"]
            page.set_content("<input aria-label='Query'><button onclick=\"document.body.dataset.clicked='yes'\">Search</button>")
            position = page.locator("input").bounding_box()
            actions = [{"type": "click", "x": int(position["x"] + 5), "y": int(position["y"] + 5)},
                       {"type": "type", "text": "Kilas Work"}]
            result = runtime.actions(101, 9001, actions, call_id="search-once")
            self.assertEqual(result["decision"], "CONTINUE")
            self.assertEqual(page.locator("input").input_value(), "Kilas Work")
            runtime.actions(101, 9001, actions, call_id="search-once")
            self.assertEqual(page.locator("input").input_value(), "Kilas Work")
            page.set_content("<button onclick=\"document.body.dataset.clicked='yes'\">Pay now</button>")
            position = page.locator("button").bounding_box()
            click = [{"type": "click", "x": int(position["x"] + 5), "y": int(position["y"] + 5)}]
            paused = runtime.actions(101, 9001, click, call_id="pay-needs-confirmation")
            self.assertEqual(paused["decision"], "CONFIRM")
            self.assertNotEqual(page.locator("body").get_attribute("data-clicked"), "yes")
            runtime.actions(101, 9001, click, call_id="confirmed-by-owner", manual=True)
            self.assertEqual(page.locator("body").get_attribute("data-clicked"), "yes")
            page.set_content("<p>Enter your verification code</p><input type=password>")
            position = page.locator("input").bounding_box()
            self.assertEqual(runtime.actions(101, 9001, [{"type": "click", "x": int(position["x"] + 5),
                "y": int(position["y"] + 5)}], call_id="otp-pause")["decision"], "HANDOFF")
            self.assertTrue(runtime.close(101, 9001))
        finally:
            for owner_id, job_id in list(runtime._sessions):
                runtime.close(owner_id, job_id)
            if runtime._browser:
                runtime._browser.close()
            if runtime._driver:
                runtime._driver.stop()


if __name__ == "__main__":
    unittest.main()
