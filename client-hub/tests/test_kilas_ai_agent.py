"""Focused Agent chat, proposals, ownership, connection truth and metering."""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-agent-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-agent-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_AUTOMATION_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import agent_planner, agent_store, automation_schedule as schedule, automation_store as store  # noqa: E402


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)

    def setUp(self):
        label = self._testMethodName
        self.owner = repo.create_user(f"agent-owner-{label}@example.test", "hash")
        self.other = repo.create_user(f"agent-other-{label}@example.test", "hash")

    def client_for(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state.update(user_id=user_id, role="CLIENT_OWNER", _csrf_token="agent-csrf")
        return client

    def test_empty_agent_and_connection_truth(self):
        client = self.client_for(self.owner)
        page = client.get("/kilas-ai/agent")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn("Agent Chat", body)
        self.assertIn("Belum ada koneksi eksternal", client.get("/kilas-ai/agent?view=connections").get_data(as_text=True))
        self.assertNotIn("Terhubung</", body)
        self.assertIn("Kilas Finance", self.client_for(self.owner).get("/products/start").get_data(as_text=True))
        self.assertNotIn("Pilih Kilas Assist", self.client_for(self.owner).get("/products/start").get_data(as_text=True))
        self.assertEqual(client.get("/products/assist").status_code != 404, True)

    def test_connector_request_is_honest_and_creates_no_task(self):
        client = self.client_for(self.owner)
        response = client.post("/kilas-ai/agent/chat", data={"csrf_token": "agent-csrf",
            "message": "setiap pagi cek email penting gue"})
        self.assertEqual(response.status_code, 303)
        self.assertIn("butuh akses Gmail", client.get(response.location).get_data(as_text=True))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_automations WHERE user_id=?",
                                      (self.owner,))["n"], 0)

    def test_chat_proposes_then_explicitly_activates_without_duplicate(self):
        client = self.client_for(self.owner)
        planned = {"action": "CREATE", "task_id": 0,
                   "schedule_text": "Setiap Jumat jam 16 cari berita AI terbaru.", "reply": ""}
        with patch.object(agent_planner, "propose", return_value=planned):
            response = client.post("/kilas-ai/agent/chat", data={"csrf_token": "agent-csrf",
                "message": "Setiap Jumat jam 16 cari berita AI terbaru."})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_automations WHERE user_id=?",
                                      (self.owner,))["n"], 0)
        self.assertIn("Periksa tugas ini", client.get(response.location).get_data(as_text=True))
        activated = client.post("/kilas-ai/automation/activate", data={"csrf_token": "agent-csrf"})
        self.assertEqual(activated.status_code, 303)
        self.assertIn("/kilas-ai/agent", activated.location)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_automations WHERE user_id=?",
                                      (self.owner,))["n"], 1)

    def test_pause_confirmation_and_owner_boundary(self):
        item_id = store.create(self.other, schedule.parse("Setiap hari jam 8 ingetin gue minum air."))
        owner_client = self.client_for(self.owner)
        other_client = self.client_for(self.other)
        with patch.object(agent_planner, "propose", return_value={
                "action": "PAUSE", "task_id": item_id, "schedule_text": "", "reply": ""}):
            owner_client.post("/kilas-ai/agent/chat", data={"csrf_token": "agent-csrf",
                "message": "pause tugas minum air"})
        self.assertIsNone(store.get(self.owner, item_id))
        self.assertEqual(store.get(self.other, item_id)["status"], "ACTIVE")
        with patch.object(agent_planner, "propose", return_value={
                "action": "PAUSE", "task_id": item_id, "schedule_text": "", "reply": ""}):
            other_client.post("/kilas-ai/agent/chat", data={"csrf_token": "agent-csrf",
                "message": "pause tugas minum air"})
        self.assertEqual(store.get(self.other, item_id)["status"], "ACTIVE")
        confirmed = other_client.post("/kilas-ai/agent/action", data={"csrf_token": "agent-csrf"})
        self.assertEqual(confirmed.status_code, 303)
        self.assertEqual(store.get(self.other, item_id)["status"], "PAUSED")
        self.assertNotIn("pause tugas minum air", owner_client.get("/kilas-ai/agent").get_data(as_text=True))

    def test_activity_uses_existing_run_history(self):
        item_id = store.create(self.owner, schedule.parse("Pantau harga emas di bawah Rp1.800.000 setiap hari jam 9."))
        db.execute("INSERT INTO kilas_automation_runs(automation_id,user_id,scheduled_for,status,completed_at) "
                   "VALUES (?,?,?,'SUCCEEDED',?)", (item_id, self.owner, "2026-09-30T09:00:00+00:00",
                                                "2026-09-30T09:00:00+00:00"))
        activity = self.client_for(self.owner).get("/kilas-ai/agent?view=activity").get_data(as_text=True)
        self.assertIn("Belum ada perubahan penting", activity)
        self.assertNotIn("Exception", activity)
        self.assertEqual(len(agent_store.activity(self.other)), 0)

    def test_responses_planner_is_structured_and_metered(self):
        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"status": "completed", "usage": {"input_tokens": 12, "output_tokens": 8},
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                            "action": "HELP", "task_id": 0, "schedule_text": "", "reply": "Ceritakan tugasmu."})}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-key"}), \
                patch.object(agent_planner.usage, "reserve", return_value=("FREE", ("CHAT",))) as reserved, \
                patch.object(agent_planner.usage, "finish") as finished, \
                patch.object(agent_planner.requests, "post", return_value=FakeResponse()) as posted:
            plan = agent_planner.propose(self.owner, "gabungkan beberapa sumber dan analisis risiko", [], [])
        self.assertEqual(plan["action"], "HELP")
        self.assertEqual(reserved.call_args.args[3], "SMART")
        self.assertEqual(posted.call_args.kwargs["json"]["model"], "gpt-6.1-sol")
        self.assertEqual(posted.call_args.kwargs["json"]["text"]["format"]["type"], "json_schema")
        self.assertTrue(finished.call_args.kwargs["success"])


if __name__ == "__main__":
    unittest.main()
