"""Bounded Work computer-call state machine and safe human confirmation."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-work-browser-jobs-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "work-browser-jobs-test-only"
os.environ["KILAS_WORK_ENABLED"] = "true"
os.environ["KILAS_WORK_BROWSER_URL"] = "https://browser.example.test"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import repo  # noqa: E402
from kilas_work import browser_jobs, store  # noqa: E402


SCREEN = {"url": "https://example.com", "screenshot": "synthetic", "downloads": []}


class BrowserJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)

    def owner(self, name):
        return repo.create_user("work-job-" + name + "@example.test", "hash")

    def new_job(self, owner, title="Buka https://example.com dan cari informasi"):
        thread = store.create_thread(owner, "Browser")
        with patch.object(browser_jobs.browser_client, "create", return_value=SCREEN), \
             patch.object(browser_jobs, "_submit"):
            job = browser_jobs.start(owner, thread, title, "gpt-6-luna")
        return thread, job

    def test_navigation_actions_complete_without_repeating(self):
        owner = self.owner("complete")
        thread, job = self.new_job(owner)
        first = {"id": "resp-1", "call": {"call_id": "call-1", "actions": [
                 {"type": "click", "x": 20, "y": 20}]}, "answer": "", "usage": {"input_tokens": 300,
                 "output_tokens": 70}}
        final = {"id": "resp-2", "call": None, "answer": "Hasil website sudah diperiksa.",
                 "usage": {"input_tokens": 400, "output_tokens": 80}}
        with patch.object(browser_jobs.browser_client, "snapshot", return_value=SCREEN), \
             patch.object(browser_jobs.browser_client, "actions", return_value={**SCREEN, "decision": "CONTINUE", "next_action": 1}) as actions, \
             patch.object(browser_jobs.browser_client, "close"), \
             patch.object(browser_jobs, "_model_call", side_effect=[first, final]) as model:
            browser_jobs._drive(owner, job)
        self.assertEqual(store.job(owner, job)["status"], "COMPLETED")
        actions.assert_called_once_with(owner, job, "call-1", first["call"]["actions"])
        self.assertEqual(model.call_count, 2)
        self.assertIn("Hasil website", store.messages(owner, thread)[-1]["content"])

    def test_confirm_pauses_before_action_then_owner_resumes(self):
        owner = self.owner("confirm")
        _, job = self.new_job(owner, "Buka https://example.com dan siapkan formulir")
        first = {"id": "resp-3", "call": {"call_id": "call-pay", "actions": [
                 {"type": "click", "x": 80, "y": 90}]}, "answer": "", "usage": {}}
        with patch.object(browser_jobs.browser_client, "snapshot", return_value=SCREEN), \
             patch.object(browser_jobs.browser_client, "actions", return_value={**SCREEN, "decision": "CONFIRM", "next_action": 0}), \
             patch.object(browser_jobs, "_model_call", return_value=first):
            browser_jobs._drive(owner, job)
        self.assertEqual(store.job(owner, job)["status"], "PAUSED_CONFIRM")
        with patch.object(browser_jobs.browser_client, "manual", return_value=SCREEN) as manual, \
             patch.object(browser_jobs, "_submit"):
            browser_jobs.confirm(owner, job)
        manual.assert_called_once_with(owner, job, f"confirm-{job}-1", [first["call"]["actions"][0]])
        self.assertEqual(store.job(owner, job)["status"], "RUNNING")

    def test_other_owner_cannot_see_job_or_screenshot(self):
        owner, other = self.owner("private"), self.owner("other")
        _, job = self.new_job(owner)
        self.assertIsNone(store.job(other, job))
        client = self.app.test_client()
        with client.session_transaction() as state:
            state.update(user_id=other, role="CLIENT_OWNER", _csrf_token="work-csrf")
        with patch.object(browser_jobs.browser_client, "snapshot") as snapshot:
            self.assertEqual(client.get(f"/kilas-work/jobs/{job}/screenshot").status_code, 404)
            snapshot.assert_not_called()

    def test_interrupted_worker_fails_closed_without_replaying_actions(self):
        owner = self.owner("interrupted")
        _, job = self.new_job(owner)
        with patch.object(browser_jobs, "active", return_value=False), \
             patch.object(browser_jobs.browser_client, "actions") as actions:
            item = browser_jobs.reconcile(owner, job)
        self.assertEqual(item["status"], "FAILED")
        self.assertEqual(item["error_code"], "browser_interrupted")
        actions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
