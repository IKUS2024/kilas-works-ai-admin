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
os.environ["KILAS_AI_AUTONOMOUS_ENABLED"] = "true"
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

    def test_empty_work_and_hidden_connections(self):
        client=self.client_for(self.owner)
        body=client.get('/kilas-ai/agent').text
        self.assertIn('+ Work baru',body)
        self.assertNotIn('Connections',body)
        self.assertNotIn('Advanced settings',body)
        self.assertEqual(client.get('/kilas-ai/agent?view=connections').status_code,303)
        self.assertIn('Kilas Finance',client.get('/products/start').text)
        self.assertNotIn('Pilih Kilas Assist',client.get('/products/start').text)
        self.assertNotEqual(client.get('/products/assist').status_code,404)

    def test_connector_request_honest_no_task_no_connector_call(self):
        from kilas_ai import connector_flow, autonomous_store
        client=self.client_for(self.owner)
        with patch.object(connector_flow,'handle',side_effect=AssertionError('Work invoked connector')):
            response=client.post('/kilas-ai/agent/chat',data={'csrf_token':'agent-csrf','message':'setiap pagi cek email penting gue'})
        self.assertEqual(response.status_code,303)
        self.assertIn('Work tidak mengakses koneksi akun',client.get(response.location).text)
        self.assertEqual(autonomous_store.list_jobs(self.owner),[])
        self.assertEqual(agent_planner.required_connection('cek kalender besok'),'Google Calendar')
        self.assertEqual(agent_planner.required_connection('rangkum laporan Finance'),'Kilas Finance')

    def test_schedule_persists_without_legacy_preview_and_duplicate_is_rejected(self):
        from kilas_ai import autonomous_store
        client=self.client_for(self.owner)
        data={'csrf_token':'agent-csrf','message':'Setiap Jumat jam 16 cari berita AI terbaru.','operation_key':'test_work_request_unique_20261002'}
        with patch.object(agent_planner,'propose',side_effect=AssertionError('No legacy preview')):
            self.assertEqual(client.post('/kilas-ai/agent/chat',data=data).status_code,303)
            self.assertEqual(client.post('/kilas-ai/agent/chat',data=data).status_code,409)
        jobs=autonomous_store.list_jobs(self.owner)
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['mode'],'RECURRING')
        self.assertNotIn('Periksa tugas ini',client.get('/kilas-ai/agent').text)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_automations WHERE user_id=?',(self.owner,))['n'],0)

    def test_named_date_task_uses_saved_timezone(self):
        from kilas_ai import autonomous_store
        client=self.client_for(self.owner)
        store.set_timezone(self.owner,'Asia/Bangkok')
        client.post('/kilas-ai/agent/chat',data={'csrf_token':'agent-csrf','message':'Tanggal 1 Oktober 2099 jam 5 pagi cari berita terbaru tentang Indonesia.'})
        jobs=autonomous_store.list_jobs(self.owner)
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['next_wake_at'],'2099-09-30T22:00:00+00:00')
        self.assertIn('05.00 ICT',client.get('/kilas-ai/agent').text)

    def test_explicit_timezone_preferences_remain_owner_scoped(self):
        client=self.client_for(self.owner)
        response=client.post('/kilas-ai/work/preferences',json={'timezone':'Asia/Jayapura','manual':True},headers={'X-CSRF-Token':'agent-csrf'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(store.setting(self.owner),'Asia/Jayapura')
        self.assertEqual(store.setting(self.other),'Asia/Jakarta')

    def test_work_pause_resume_owner_boundary(self):
        from kilas_ai import autonomous_store
        own_conversation=agent_store.new_conversation(self.other)
        job=autonomous_store.create(self.other,'Riset berita terbaru',conversation_id=own_conversation)
        owner_client=self.client_for(self.owner)
        other_client=self.client_for(self.other)
        owner_client.post('/kilas-ai/agent/chat',data={'csrf_token':'agent-csrf','message':'pause pekerjaan '+str(job)})
        self.assertEqual(autonomous_store.get(self.other,job)['status'],'PLANNING')
        other_client.post('/kilas-ai/agent/chat',data={'csrf_token':'agent-csrf','message':'pause pekerjaan '+str(job)})
        self.assertEqual(autonomous_store.get(self.other,job)['status'],'PAUSED')
        other_client.post('/kilas-ai/agent/chat',data={'csrf_token':'agent-csrf','message':'resume pekerjaan '+str(job)})
        self.assertEqual(autonomous_store.get(self.other,job)['status'],'PLANNING')

    def test_old_automation_history_preserved_separate_from_work_notifications(self):
        item_id=store.create(self.owner,schedule.parse('Pantau harga emas di bawah Rp1.800.000 setiap hari jam 9.'))
        db.execute("INSERT INTO kilas_automation_runs(automation_id,user_id,scheduled_for,status,completed_at) VALUES (?,?,?,'SUCCEEDED',?)",(item_id,self.owner,'2026-09-30T09:00:00+00:00','2026-09-30T09:00:00+00:00'))
        self.assertEqual(len(agent_store.activity(self.owner)),1)
        self.assertEqual(len(agent_store.activity(self.other)),0)
        self.assertEqual(self.client_for(self.owner).get('/kilas-ai/agent?view=activity').status_code,303)

    def test_simple_agent_planner_defaults_to_luna_and_account_timezone(self):
        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5},
                        "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                            "action": "CREATE", "task_id": 0,
                            "schedule_text": "Besok jam 8 pagi cari berita terbaru.",
                            "reply": ""})}]}]}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only-key"}, clear=False), \
                patch.object(agent_planner.usage, "reserve", return_value=("FREE", ("CHAT",))) as reserved, \
                patch.object(agent_planner.usage, "finish") as finished, \
                patch.object(agent_planner.requests, "post", return_value=FakeResponse()) as posted:
            plan = agent_planner.propose(self.owner, "besok jam 8 kasih berita terbaru", [], [],
                                         "Asia/Jakarta")
        self.assertEqual(plan["action"], "CREATE")
        self.assertEqual(reserved.call_args.args[3], "SMART")
        payload = posted.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gpt-6-luna")
        self.assertIn("saved timezone: Asia/Jakarta", payload["instructions"])
        self.assertIn("do not ask them to choose WIB/WITA/WIT", payload["instructions"])
        self.assertTrue(finished.call_args.kwargs["success"])

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
        self.assertEqual(posted.call_args.kwargs["json"]["model"], "gpt-6-luna")
        self.assertEqual(posted.call_args.kwargs["json"]["text"]["format"]["type"], "json_schema")
        self.assertTrue(finished.call_args.kwargs["success"])


if __name__ == "__main__":
    unittest.main()
