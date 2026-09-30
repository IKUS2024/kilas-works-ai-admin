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
        named = schedule.parse(
            "Tanggal 1 Oktober 2026 jam 5 pagi kasih gue berita terbaru tentang Indonesia.",
            now=datetime(2026, 9, 30, 17, 52, tzinfo=timezone.utc))
        self.assertEqual(named["automation_type"], "SEARCH")
        self.assertEqual(named["schedule"], {"kind": "once", "year": 2026, "month": 10, "day": 1,
                                             "hour": 5, "minute": 0})
        self.assertEqual(named["next_run_at"], datetime(2026, 9, 30, 22, tzinfo=timezone.utc))
        self.assertEqual(schedule.parse("Hari ini jam 6 pagi cari berita terbaru.",
                                        now=datetime(2026, 9, 30, 17, 52, tzinfo=timezone.utc))["schedule"]["day"], 1)
        self.assertEqual(schedule.parse("Lusa jam 8 pagi ingetin gue cek laporan.",
                                        now=now)["schedule"]["day"], 1)
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

    def test_structured_recurrence_and_timezone_keep_canonical_schedule(self):
        now = datetime(2026, 9, 29, 4, tzinfo=timezone.utc)
        task = "Ingetin gue cek laporan QA."
        once = schedule.parse_structured(task, "Asia/Jakarta", "once", date="2026-09-30",
                                         time="08:00", now=now)
        self.assertEqual(once["instruction"], task)
        self.assertEqual(once["schedule"]["kind"], "once")
        self.assertEqual(once["next_run_at"], datetime(2026, 9, 30, 1, tzinfo=timezone.utc))
        bangkok = schedule.parse_structured(task, "Asia/Bangkok", "once", date="2026-09-30",
                                            time="08:00", now=now)
        self.assertEqual(bangkok["next_run_at"], once["next_run_at"])
        self.assertIn("Bangkok", schedule.describe(bangkok["schedule"], bangkok["timezone"]))
        daily = schedule.parse_structured("Cari berita AI terbaru.", "Asia/Jakarta", "daily",
                                          time="09:15", now=now)
        self.assertEqual(daily["schedule"], {"kind": "daily", "hour": 9, "minute": 15})
        weekly = schedule.parse_structured(task, "Asia/Jakarta", "weekly", weekday="0",
                                           time="09:00", now=now)
        self.assertEqual(weekly["schedule"]["weekday"], 0)
        monthly = schedule.parse_structured(task, "Asia/Jakarta", "monthly", day="31",
                                            time="09:00", now=datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(monthly["next_run_at"].month, 3)
        self.assertEqual(monthly["next_run_at"].day, 31)
        self.assertEqual(schedule.parse_structured(task, "Asia/Tokyo", "daily", time="09:00",
                                               now=now)["timezone"], "Asia/Tokyo")

    def test_structured_schedule_rejects_past_and_invalid_values(self):
        now = datetime(2026, 9, 29, 4, tzinfo=timezone.utc)
        task = "Ingetin gue cek laporan QA."
        bad = (
            {"mode": "once", "date": "2026-09-28", "time": "09:00"},
            {"mode": "once", "date": "2026-09-29", "time": "10:00"},
            {"mode": "once", "date": "2026-02-30", "time": "09:00"},
            {"mode": "weekly", "weekday": "7", "time": "09:00"},
            {"mode": "monthly", "day": "32", "time": "09:00"},
            {"mode": "daily", "time": "25:00"},
        )
        for fields in bad:
            with self.subTest(fields=fields), self.assertRaises(schedule.ScheduleError):
                schedule.parse_structured(task, "Asia/Jakarta", now=now, **fields)
        with self.assertRaises(schedule.ScheduleError):
            schedule.parse_structured(task, "UTC+7", "daily", time="09:00", now=now)


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

    def test_structured_preview_create_and_edit_preserve_existing_format(self):
        user_id = repo.create_user("automation-structured@example.test", "hash")
        client = self.client_for(user_id)
        data = {"csrf_token": "automation-csrf", "instruction": "Ingetin gue cek laporan QA.",
                "title": "Cek laporan", "timezone": "Asia/Bangkok", "schedule_mode": "once",
                "run_date": "2099-10-02", "run_time": "08:30"}
        preview = client.post("/kilas-ai/automation/preview", data=data)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("02/10/2099", preview.get_data(as_text=True))
        self.assertIn("Asia/Bangkok", preview.get_data(as_text=True))
        self.assertEqual(client.post("/kilas-ai/automation/activate",
                                     data={"csrf_token": "automation-csrf"}).status_code, 303)
        item = db.query_one("SELECT * FROM kilas_automations WHERE user_id=?", (user_id,))
        self.assertEqual(item["instruction"], data["instruction"])
        self.assertEqual(item["timezone"], "Asia/Bangkok")
        self.assertIn('value="2099-10-02"', client.get(f"/kilas-ai/automation/{item['id']}/edit").get_data(as_text=True))
        data.update(automation_id=str(item["id"]), schedule_mode="weekly", weekday="2", run_time="09:00")
        preview = client.post("/kilas-ai/automation/preview", data=data)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Rabu", preview.get_data(as_text=True))
        self.assertEqual(client.post("/kilas-ai/automation/activate", data={
            "csrf_token": "automation-csrf", "automation_id": str(item["id"])}).status_code, 303)
        changed = store.get(user_id, item["id"])
        self.assertEqual(changed["id"], item["id"])
        self.assertIn('"weekday": 2', changed["schedule_json"])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_automations WHERE user_id=?",
                                      (user_id,))["n"], 1)

    def test_existing_interval_form_stays_editable(self):
        user_id = repo.create_user("automation-interval-edit@example.test", "hash")
        spec = schedule.parse("Setiap 6 jam cari berita terbaru.")
        item_id = store.create(user_id, spec)
        page = self.client_for(user_id).get(f"/kilas-ai/automation/{item_id}/edit").get_data(as_text=True)
        self.assertIn('value="natural" selected', page)
        self.assertIn(spec["instruction"], page)
        store.set_status(user_id, item_id, "pause")
