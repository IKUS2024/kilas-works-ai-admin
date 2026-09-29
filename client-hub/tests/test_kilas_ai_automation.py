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
    def test_watch_number_formats(self):
        self.assertEqual(runner._numeric_value("Rp1.800.000"), 1800000)
        self.assertEqual(runner._numeric_value("1800000.0"), 1800000)
        self.assertEqual(runner._numeric_value("1,800,000"), 1800000)

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

    def test_weekly_monthly_interval_and_safe_reminder(self):
        now = datetime(2026, 9, 29, 4, tzinfo=timezone.utc)
        weekly = schedule.parse("Setiap Senin jam 9 cari lowongan admin terbaru.", now=now)
        self.assertEqual(weekly["schedule"]["weekday"], 0)
        monthly = schedule.parse("Setiap tanggal 25 jam 8 ingetin bayar internet.", now=now)
        self.assertEqual(monthly["schedule"]["day"], 25)
        interval = schedule.parse("Setiap 6 jam cari berita terbaru.", now=now)
        self.assertEqual(interval["schedule"]["hours"], 6)
        self.assertEqual(schedule.parse("Besok jam 8 ingetin gue beli tiket.", now=now)["automation_type"], "REMINDER")
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse("Setiap 0 jam cari berita terbaru.", now=now)
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse("Besok jam 8 beli tiket untuk saya.", now=now)


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
        self.assertTrue(store.has_setting(self.owner))
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
        chat = client.get(f"/kilas-ai?automation_result={ids[0]}")
        self.assertIn("Lanjutkan dari hasil Automation", chat.get_data(as_text=True))
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
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_automation_runs WHERE user_id=? AND attempt_count>0",
                                      (self.other,))["n"], 1)
        self.assertEqual(store.get(self.other, automation_id)["status"], "ACTIVE")
        store.set_status(self.other, automation_id, "pause")

    def test_access_csrf_active_limit_pause_resume_and_delete(self):
        owner = repo.create_user("automation-limit@example.test", "hash")
        client = self.client_for(owner)
        self.assertEqual(self.app.test_client().get("/kilas-ai/automation").status_code, 302)
        self.assertEqual(client.post("/kilas-ai/automation/timezone", data={"timezone": "Asia/Jakarta"}).status_code, 400)
        self.assertEqual(client.post("/kilas-ai/automation/timezone", data={"csrf_token": "automation-csrf",
            "timezone": "UTC+7"}).status_code, 303)
        spec = schedule.parse("Setiap hari jam 8 ingetin gue minum air.")
        first = store.create(owner, spec)
        with self.assertRaises(store.AutomationError):
            store.create(owner, spec)
        store.set_status(owner, first, "pause")
        self.assertEqual(store.get(owner, first)["status"], "PAUSED")
        second = store.create(owner, spec)
        with self.assertRaises(store.AutomationError):
            store.set_status(owner, first, "resume")
        store.set_status(owner, second, "delete")
        self.assertIsNone(store.get(owner, second))
        store.set_status(owner, first, "resume")
        self.assertEqual(store.get(owner, first)["status"], "ACTIVE")
        self.assertEqual(store.usage_summary(owner)["active"], 1)
        store.set_status(owner, first, "pause")

    def test_watch_only_alerts_on_match_or_meaningful_change(self):
        owner = repo.create_user("automation-watch@example.test", "hash")
        spec = schedule.parse("Pantau harga emas di bawah Rp1.800.000 setiap hari jam 9.")
        automation_id = store.create(owner, spec)
        fake_search = {"text": "Harga emas dengan sumber.", "model": "gpt-6-luna",
                       "usage": {"input_tokens": 5, "output_tokens": 5},
                       "citations": [{"title": "Sumber", "url": "https://example.com/gold"}]}
        next_due = spec["next_run_at"] + timedelta(minutes=1)
        with patch.object(runner.tools, "web_search", return_value=fake_search), \
             patch.object(runner, "_plain_ai", side_effect=[
                 ('{"value":1700000,"summary":"Harga di bawah batas."}', "openai", "gpt-6-luna", {}),
                 ('{"value":1700000,"summary":"Harga tetap."}', "openai", "gpt-6-luna", {}),
                 ('{"value":1690000,"summary":"Harga berubah."}', "openai", "gpt-6-luna", {})]):
            ids = []
            for _ in range(3):
                claimed = store.claim_due(now=next_due)
                self.assertEqual(len(claimed), 1)
                ids += claimed
                self.assertTrue(runner.execute(claimed[0]))
                row = store.get(owner, automation_id)
                next_due = datetime.fromisoformat(row["next_run_at"]) + timedelta(minutes=1)
        self.assertEqual(store.result(owner, ids[0])["result_text"], "Harga di bawah batas.")
        self.assertIsNone(store.result(owner, ids[1])["result_text"])
        self.assertEqual(store.result(owner, ids[2])["result_text"], "Harga berubah.")

    def test_billable_run_cap_pauses_without_provider_call(self):
        owner = repo.create_user("automation-run-limit@example.test", "hash")
        spec = schedule.parse("Setiap hari jam 9 cari berita terbaru.")
        automation_id = store.create(owner, spec)
        due = spec["next_run_at"] + timedelta(minutes=1)
        for index in range(10):
            moment = (due - timedelta(minutes=index + 2)).isoformat()
            db.execute("INSERT INTO kilas_automation_runs(automation_id,user_id,scheduled_for,status,attempt_count,started_at) "
                       "VALUES (?,?,?,'SUCCEEDED',1,?)", (automation_id, owner, moment, moment))
        self.assertEqual(store.claim_due(now=due), [])
        self.assertEqual(store.get(owner, automation_id)["status"], "PAUSED_QUOTA")

    def test_plan_downgrade_pauses_excess_due_automation(self):
        owner = repo.create_user("automation-downgrade@example.test", "hash")
        now = datetime.now(timezone.utc)
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) "
                   "VALUES (?,'PLUS','ACTIVE',?,?)",
                   (owner, (now - timedelta(days=1)).isoformat(), (now + timedelta(days=2)).isoformat()))
        spec = schedule.parse("Setiap hari jam 8 ingetin gue minum air.")
        first = store.create(owner, spec)
        second = store.create(owner, spec)
        db.execute("UPDATE kilas_ai_subscriptions SET period_end=? WHERE user_id=?",
                   ((now - timedelta(minutes=1)).isoformat(), owner))
        due = spec["next_run_at"] + timedelta(minutes=1)
        claimed = store.claim_due(now=due)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(store.get(owner, first)["status"], "ACTIVE")
        self.assertEqual(store.get(owner, second)["status"], "PAUSED_QUOTA")
        self.assertTrue(runner.execute(claimed[0]))
        store.set_status(owner, first, "pause")


if __name__ == "__main__":
    unittest.main()
