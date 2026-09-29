"""Focused Automation V1 schedule, ownership, preview, claim and result checks."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-automation-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-automation-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_AUTOMATION_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import automation_runner as runner, automation_schedule as schedule, automation_store as store  # noqa: E402


class AutomationScheduleTests(unittest.TestCase):
    def test_examples_and_ambiguity(self):
        now = datetime(2026, 9, 29, 4, tzinfo=timezone.utc)
        reminder = schedule.parse("Besok jam 8 ingetin gue bayar listrik.", now=now)
        self.assertEqual(reminder["automation_type"], "REMINDER")
        self.assertEqual(reminder["next_run_at"], datetime(2026, 9, 30, 1, tzinfo=timezone.utc))
        self.assertEqual(schedule.parse("Setiap pagi jam 8 cari berita AI terbaru.", now=now)["automation_type"], "SEARCH")
        self.assertEqual(schedule.parse("Pantau harga emas di bawah Rp1.800.000 setiap hari jam 9.", now=now)["condition"],
                         {"operator": "lt", "threshold": 1800000})
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse("Pantau harga emas dan kabarin kalau di bawah Rp1.800.000.", now=now)
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse("Besok ingetin gue bayar listrik.", now=now)
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse("Besok jam 8 kirim WhatsApp ke Budi.", now=now)

    def test_iana_dst_and_explicit_zone(self):
        now = datetime(2026, 3, 6, 12, tzinfo=timezone.utc)
        spec = schedule.parse("Setiap hari jam 2 pagi waktu New York ingetin minum air.", now=now)
        self.assertEqual(spec["timezone"], "America/New_York")
        self.assertEqual(spec["next_run_at"], datetime(2026, 3, 7, 7, tzinfo=timezone.utc))
        following = schedule.next_occurrence(spec["schedule"], spec["timezone"], spec["next_run_at"])
        self.assertEqual(following, datetime(2026, 3, 9, 6, tzinfo=timezone.utc))
        with self.assertRaises(schedule.ScheduleError):
            schedule.validate_timezone("UTC+7")


class AutomationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner = repo.create_user("automation-owner@example.test", "hash")
        cls.other = repo.create_user("automation-other@example.test", "hash")

    def client_for(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as user_session:
            user_session.update(user_id=user_id, role="CLIENT_OWNER", _csrf_token="automation-csrf")
        return client

    def test_preview_confirmation_owner_gate_and_reminder(self):
        client = self.client_for(self.owner)
        instruction = "Besok jam 8 ingetin gue bayar listrik."
        preview = client.post("/kilas-ai/automation/preview", data={"csrf_token": "automation-csrf",
            "instruction": instruction, "timezone": "Asia/Jakarta"})
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Aktifkan Automation", preview.get_data(as_text=True))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_automations WHERE user_id=?", (self.owner,))["n"], 0)
        created = client.post("/kilas-ai/automation/activate", data={"csrf_token": "automation-csrf"})
        self.assertEqual(created.status_code, 303)
        item = db.query_one("SELECT * FROM kilas_automations WHERE user_id=?", (self.owner,))
        self.assertIsNotNone(item)
        self.assertIsNone(store.get(self.other, item["id"]))
        self.assertEqual(self.client_for(self.other).get(f"/kilas-ai/automation/{item['id']}/edit").status_code, 404)
        due = datetime.fromisoformat(item["next_run_at"]) + timedelta(minutes=1)
        ids = store.claim_due(now=due)
        self.assertEqual(len(ids), 1)
        self.assertEqual(store.claim_due(now=due), [])
        self.assertTrue(runner.execute(ids[0]))
        result = store.result(self.owner, ids[0])
        self.assertTrue(result["unread"])
        self.assertIsNone(store.result(self.other, ids[0]))
        self.assertEqual(self.client_for(self.other).get(f"/kilas-ai/automation/results/{ids[0]}").status_code, 404)
        self.assertEqual(client.get(f"/kilas-ai/automation/results/{ids[0]}").status_code, 200)
        self.assertFalse(store.result(self.owner, ids[0])["unread"])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=?", (self.owner,))["n"], 0)

    def test_search_uses_existing_usage_and_no_duplicate_occurrence(self):
        instruction = "Setiap hari jam 9 cari berita AI terbaru."
        spec = schedule.parse(instruction)
        automation_id = store.create(self.other, spec)
        due = spec["next_run_at"] + timedelta(minutes=1)
        ids = store.claim_due(now=due)
        self.assertEqual(len(ids), 1)
        fake = {"text": "Berita terbaru dengan sumber.", "model": "gpt-6-luna",
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "citations": [{"title": "Sumber", "url": "https://example.com/story"}]}
        with patch.object(runner.tools, "web_search", return_value=fake) as searched:
            self.assertTrue(runner.execute(ids[0]))
        searched.assert_called_once()
        self.assertEqual(db.query_one("SELECT status FROM kilas_ai_usage WHERE user_id=?", (self.other,))["status"], "COMPLETE")
        self.assertEqual(store.claim_due(now=due), [])
        self.assertEqual(store.usage_summary(self.other)["runs"], 1)
        self.assertEqual(store.get(self.other, automation_id)["status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
