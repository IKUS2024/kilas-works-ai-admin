"""Focused connector ownership, OAuth state, approval, and schedule boundaries."""
import os
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-connectors-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "synthetic-connector-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ["KILAS_AI_AUTOMATION_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

from cryptography.fernet import Fernet  # noqa: E402
import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import agent_planner, connector_actions, connector_flow, connectors, google_connection, automation_schedule  # noqa: E402


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class ConnectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)

    def setUp(self):
        label = self._testMethodName
        self.owner = repo.create_user(f"connector-{label}@example.test", "hash")
        self.other = repo.create_user(f"connector-other-{label}@example.test", "hash")

    def client_for(self, user_id):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state.update(user_id=user_id, role="CLIENT_OWNER", _csrf_token="connector-csrf")
        return client

    def test_missing_google_configuration_is_truthful(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("KILAS_GOOGLE_CLIENT_ID", "KILAS_GOOGLE_CLIENT_SECRET",
                        "KILAS_GOOGLE_REDIRECT_URI", "KILAS_CONNECTOR_ENCRYPTION_KEY"):
                os.environ.pop(key, None)
            client = self.client_for(self.owner)
            page = client.get("/kilas-ai/agent?view=connections")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Koneksi Google belum tersedia", page.text)
            response = client.post("/kilas-ai/agent/connections/google/gmail",
                                   data={"csrf_token": "connector-csrf"})
            self.assertEqual(response.status_code, 303)
            self.assertNotIn("accounts.google.com", response.location)
            self.assertEqual(connectors.available_tools(self.owner), [])

    def test_oauth_state_identity_encryption_and_owner_isolation(self):
        key = Fernet.generate_key().decode()
        env = {"KILAS_GOOGLE_CLIENT_ID": "synthetic-client-id",
               "KILAS_GOOGLE_CLIENT_SECRET": "synthetic-secret",
               "KILAS_GOOGLE_REDIRECT_URI": "https://app.example.test/kilas-ai/agent/connections/google/callback",
               "KILAS_CONNECTOR_ENCRYPTION_KEY": key}
        with patch.dict(os.environ, env):
            state = {}
            url = google_connection.begin(self.owner, "gmail", state)
            raw = parse_qs(urlparse(url).query)["state"][0]
            self.assertNotIn(raw, str(db.query_all("SELECT * FROM kilas_ai_oauth_states")))
            with self.assertRaisesRegex(connectors.ConnectorError, "invalid_oauth_state"):
                google_connection.complete(self.other, state, raw, "code")
            with patch.object(google_connection.requests, "post", return_value=Response(200, {
                    "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                    "expires_in": 3600,
                    "scope": "openid email https://www.googleapis.com/auth/gmail.readonly "
                             "https://www.googleapis.com/auth/gmail.compose "
                             "https://www.googleapis.com/auth/gmail.send"})), \
                 patch.object(google_connection.requests, "get", return_value=Response(200, {
                     "sub": "synthetic-google-account", "email": "owner@example.test", "email_verified": True})):
                row = google_connection.complete(self.owner, state, raw, "code")
            self.assertEqual(row["status"], "CONNECTED")
            self.assertEqual(row["display_identity"], "owner@example.test")
            self.assertNotIn("synthetic-refresh", str(row))
            self.assertIn("gmail.send", connectors.available_tools(self.owner))
            self.assertNotIn("gmail.send", connectors.available_tools(self.other))
            with self.assertRaisesRegex(connectors.ConnectorError, "invalid_oauth_state"):
                google_connection.complete(self.owner, state, raw, "code")
            with patch.object(google_connection.requests, "post", return_value=Response(200, {})):
                google_connection.disconnect(self.owner)
            self.assertNotIn("gmail.send", connectors.available_tools(self.owner))

    def test_action_exact_payload_single_use_and_owner_boundary(self):
        business = repo.create_business(self.owner, "Connector Finance")
        with patch.object(connectors, "business_connections", side_effect=lambda user: [
                {"provider": "FINANCE", "business_id": business, "status": "CONNECTED"}]
                if user == self.owner else []):
            payload = {"branch_id": 3, "direction": "INCOME", "amount_minor": 2500000,
                       "account_id": 4, "category_id": 5, "occurred_on": "2099-01-01"}
            approval_id = connectors.propose_action(self.owner, "finance.create_transaction",
                "3", payload, business_id=business)
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_not_found"):
                connectors.claim_action(self.other, approval_id)
            row = connectors.approval(self.owner, approval_id)
            self.assertIn("payload_hash", row)
            self.assertEqual(connectors.claim_action(self.owner, approval_id)["payload"], payload)
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_already_used"):
                connectors.claim_action(self.owner, approval_id)
            connectors.finish_action(self.owner, approval_id, "UNKNOWN", error_code="provider_outcome_uncertain")
            self.assertEqual(connectors.approval(self.owner, approval_id)["status"], "UNKNOWN")

    def test_confirmed_gmail_send_cannot_be_replayed(self):
        t = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.send"]', t, t))
        approval_id = connectors.propose_action(self.owner, "gmail.send", "wilson@example.test",
            {"to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa."})
        with patch.object(connector_actions.google_tools, "gmail_send", return_value={"id": "provider-message-1"}) as send:
            self.assertEqual(connector_actions.execute(self.owner, approval_id)["id"], "provider-message-1")
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_already_used"):
                connector_actions.execute(self.owner, approval_id)
            send.assert_called_once()
        self.assertEqual(connectors.approval(self.owner, approval_id)["status"], "SUCCEEDED")

    def test_google_refresh_rotates_encrypted_access_token(self):
        key = Fernet.generate_key().decode()
        scope = "https://www.googleapis.com/auth/gmail.readonly"
        with patch.dict(os.environ, {
            "KILAS_GOOGLE_CLIENT_ID": "synthetic-client-id",
            "KILAS_GOOGLE_CLIENT_SECRET": "synthetic-secret",
            "KILAS_GOOGLE_REDIRECT_URI": "https://app.example.test/kilas-ai/agent/connections/google/callback",
            "KILAS_CONNECTOR_ENCRYPTION_KEY": key,
        }):
            stamp = connectors.stamp()
            db.execute("INSERT INTO kilas_ai_connections "
                "(user_id,provider,status,scopes_json,permission_json,credential_enc,token_expires_at,created_at,updated_at) "
                "VALUES (?,'GOOGLE','CONNECTED',?,'{}',?,?,?,?)",
                (self.owner, '["' + scope + '"]', google_connection._encrypt({
                    "access_token": "old-synthetic", "refresh_token": "refresh-synthetic"}),
                 "2020-01-01T00:00:00+00:00", stamp, stamp))
            with patch.object(google_connection.requests, "post", return_value=Response(200, {
                "access_token": "new-synthetic", "expires_in": 3600})) as refresh:
                self.assertEqual(google_connection.access_token(self.owner, scope), "new-synthetic")
            self.assertEqual(refresh.call_count, 1)
            stored = connectors.google_connection(self.owner)
            self.assertNotIn("new-synthetic", stored["credential_enc"])
            self.assertEqual(google_connection._decrypt(stored["credential_enc"])["refresh_token"],
                             "refresh-synthetic")

    def test_reply_target_must_match_verified_gmail_thread(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.readonly",'
             '"https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        thread = [{"from": "Wilson <wilson@example.test>", "message_id": "<verified@example.test>"}]
        with patch.object(connector_flow.google_tools, "gmail_thread", return_value=thread), \
             patch.object(connector_flow.google_tools, "gmail_create_draft", return_value={
                 "draft_id": "synthetic-draft", "raw_hash": "a" * 64}):
            with self.assertRaisesRegex(connectors.ConnectorError, "recipient_not_in_thread"):
                connector_flow._proposal(self.owner, "gmail.send", {
                    "to": "stranger@example.test", "subject": "Re: Jadwal", "body": "Besok jam 2 bisa.",
                    "thread_id": "thread-1"}, None)
            approval_id = connector_flow._proposal(self.owner, "gmail.send", {
                "to": "wilson@example.test", "subject": "Re: Jadwal", "body": "Besok jam 2 bisa.",
                "thread_id": "thread-1", "reply_to": "<forged@example.test>"}, None)
        payload = __import__("json").loads(connectors.approval(self.owner, approval_id)["payload_json"])
        self.assertEqual(payload["reply_to"], "<verified@example.test>")
        self.assertEqual(payload["draft_id"], "synthetic-draft")

    def test_edit_cancels_old_approval_and_preserves_target_context(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        approval_id = connectors.propose_action(self.owner, "gmail.send", "wilson@example.test",
            {"to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa."})
        client = self.client_for(self.owner)
        response = client.post(f"/kilas-ai/agent/approval/{approval_id}/edit",
                               data={"csrf_token": "connector-csrf"})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(connectors.approval(self.owner, approval_id)["status"], "CANCELLED")
        page = client.get(response.location)
        self.assertIn("wilson@example.test", page.text)
        self.assertIn("Besok jam 2 bisa.", page.text)
        with self.assertRaisesRegex(connectors.ConnectorError, "approval_already_used"):
            connectors.claim_action(self.owner, approval_id)

    def test_scheduled_gmail_draft_requires_a_later_send_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,display_identity,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','owner@example.test','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.readonly",'
             '"https://www.googleapis.com/auth/gmail.compose",'
             '"https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        plans = [
            {"tool": "gmail.search", "intent": "READ", "business_id": 0,
             "arguments": {"query": "is:important newer_than:1d"}},
            {"tool": "gmail.draft", "intent": "PREPARE", "business_id": 0,
             "arguments": {"to": "wilson@example.test", "subject": "Re: Jadwal",
                           "body": "Besok jam 2 bisa."}},
        ]
        with patch.object(connector_flow.connector_planner, "propose", side_effect=plans * 2), \
             patch.object(connector_flow.google_tools, "gmail_search", return_value=[{
                 "thread_id": "thread-1", "subject": "Jadwal"}]), \
             patch.object(connector_flow.google_tools, "gmail_thread", return_value=[{
                 "from": "Wilson <wilson@example.test>", "snippet": "Bisa besok jam 2?",
                 "message_id": "<verified@example.test>"}]), \
             patch.object(connector_flow.google_tools, "gmail_create_draft", return_value={
                 "draft_id": "synthetic-draft", "raw_hash": "a" * 64}) as prepared, \
             patch.object(connector_actions.google_tools, "gmail_send") as sent:
            for _ in range(2):
                result = connector_flow.scheduled_read(self.owner,
                    "setiap pagi cek email penting dan siapkan draf balasan", "Asia/Jakarta", run_id=77)
        self.assertIn("belum dikirim", result)
        sent.assert_not_called()
        prepared.assert_called_once()
        row = db.query_one("SELECT * FROM kilas_ai_action_approvals WHERE user_id=? ORDER BY id DESC LIMIT 1",
                           (self.owner,))
        self.assertEqual(row["status"], "PENDING")
        self.assertEqual(row["tool"], "gmail.send")
        self.assertIn("wilson@example.test", row["payload_json"])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_action_approvals "
                         "WHERE user_id=?", (self.owner,))["n"], 1)

    def test_edited_gmail_draft_cannot_be_sent_under_old_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.compose",'
             '"https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        changed = connector_actions.google_tools._raw_email(
            "stranger@example.test", "Re: Jadwal", "Besok jam 2 bisa.")
        with patch.object(connector_actions.google_tools, "_request", return_value={
                "id": "draft-1", "message": {"raw": changed}}) as api:
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_payload_changed"):
                connector_actions.google_tools.gmail_send_draft(self.owner, "draft-1", {
                    "to": "wilson@example.test", "subject": "Re: Jadwal", "body": "Besok jam 2 bisa."})
            api.assert_called_once()
        original = connector_actions.google_tools._raw_email(
            "wilson@example.test", "Re: Jadwal", "Besok jam 2 bisa.")
        with patch.object(connector_actions.google_tools, "_request", side_effect=[
                {"id": "draft-1", "message": {"raw": original}}, {"id": "sent-1"}]) as api:
            result = connector_actions.google_tools.gmail_send_draft(self.owner, "draft-1", {
                "to": "wilson@example.test", "subject": "Re: Jadwal", "body": "Besok jam 2 bisa."})
            self.assertEqual(result["id"], "sent-1")
            self.assertEqual(api.call_count, 2)

    def test_approval_payload_tamper_and_cross_business_are_rejected(self):
        business_a = repo.create_business(self.owner, "Connector A")
        business_b = repo.create_business(self.owner, "Connector B")
        visible = [{"provider": "WHATSAPP", "business_id": business_a,
                    "status": "CONNECTED", "display_identity": "Connector A"}]
        with patch.object(connectors, "business_connections", return_value=visible):
            with self.assertRaisesRegex(connectors.ConnectorError, "not_connected"):
                connectors.authorize(self.owner, "whatsapp.send", business_id=business_b)
            approval_id = connectors.propose_action(self.owner, "whatsapp.send", "conversation-a",
                {"text": "Besok jam 2 bisa."}, business_id=business_a)
            db.execute("UPDATE kilas_ai_action_approvals SET payload_json=? WHERE id=?",
                       ('{"text":"Different message"}', approval_id))
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_payload_changed"):
                connectors.claim_action(self.owner, approval_id)
            self.assertEqual(connectors.approval(self.owner, approval_id)["status"], "PENDING")

    def test_natural_schedule_without_utc_day_shift(self):
        from datetime import datetime, timezone
        near_midnight = datetime(2026, 9, 30, 17, 30, tzinfo=timezone.utc)
        cases = {
            "besok jam 5 pagi cari berita AI": (2026, 10, 2, 5, 0),
            "tomorrow at 5pm search news": (2026, 10, 2, 17, 0),
            "lusa 17:00 cari berita": (2026, 10, 3, 17, 0),
            "malam ini jam 8 cari berita": (2026, 10, 1, 20, 0),
            "next week at 8am search news": (2026, 10, 5, 8, 0),
            "setiap Senin pagi cari berita": (None, None, None, 8, 0),
            "tiap senin sampai jumat jam 8 cari berita": (None, None, None, 8, 0),
            "tanggal 1 Oktober 2027 jam setengah 8 pagi cari berita": (2027, 10, 1, 7, 30),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                spec = automation_schedule.parse(text, "Asia/Jakarta", now=near_midnight)
                run = spec["next_run_at"].astimezone(automation_schedule.ZoneInfo("Asia/Jakarta"))
                for actual, want in zip((run.year, run.month, run.day, run.hour, run.minute),
                                        (expected[0], expected[1], expected[2], expected[3])):
                    if want is not None:
                        self.assertEqual(actual, want)
        self.assertEqual(automation_schedule.parse(
            "tiap senin sampai jumat jam 8 cari berita", "Asia/Jakarta", now=near_midnight)["schedule"]["kind"],
            "weekdays")
        self.assertEqual(automation_schedule.parse(
            "every 3 hours search news", "Asia/Jakarta", now=near_midnight)["schedule"]["hours"], 3)
        self.assertEqual(automation_schedule.parse(
            "tomorrow at 5pm timezone Singapore search news", "Asia/Jakarta", now=near_midnight)["timezone"],
            "Asia/Singapore")
        with self.assertRaises(automation_schedule.ScheduleError):
            automation_schedule.parse("kemarin jam 8 cari berita", "Asia/Jakarta", now=near_midnight)

    def test_multilingual_connector_intent_examples(self):
        self.assertEqual(agent_planner.required_connection("每周一早上帮我总结重要邮件"), "Gmail")
        self.assertEqual(agent_planner.required_connection("revisar mi correo"), "Gmail")
        self.assertEqual(agent_planner.required_connection("cek jadwal Jumat"), "Google Calendar")


if __name__ == "__main__":
    unittest.main()
