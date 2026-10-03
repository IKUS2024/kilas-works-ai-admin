"""Focused connector ownership, OAuth state, approval, and schedule boundaries."""
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
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
from kilas_ai import agent_planner, connector_actions, connector_flow, connectors, google_connection, internal_tools, automation_schedule  # noqa: E402


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError("synthetic_request_failed")


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
            self.assertEqual(page.status_code, 303)
            self.assertTrue(page.location.endswith('/kilas-ai/agent'))
            self.assertFalse(google_connection.configuration()["ready"])
            self.assertNotIn("Hubungkan Google", client.get(page.location).text)
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
            requested_scope = parse_qs(urlparse(url).query)["scope"][0]
            self.assertEqual(set(requested_scope.split()), {
                "openid", "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/gmail.send"})
            self.assertNotIn("include_granted_scopes", parse_qs(urlparse(url).query))
            self.assertNotIn(raw, str(db.query_all("SELECT * FROM kilas_ai_oauth_states")))
            with self.assertRaisesRegex(connectors.ConnectorError, "invalid_oauth_state"):
                google_connection.complete(self.other, state, raw, "code")
            with patch.object(google_connection.requests, "post", return_value=Response(200, {
                    "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                    "expires_in": 3600,
                    "scope": "openid https://www.googleapis.com/auth/userinfo.email "
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

    def test_other_google_services_cannot_start_oauth(self):
        key = Fernet.generate_key().decode()
        env = {"KILAS_GOOGLE_CLIENT_ID": "synthetic-client-id",
               "KILAS_GOOGLE_CLIENT_SECRET": "synthetic-secret",
               "KILAS_GOOGLE_REDIRECT_URI": "https://app.example.test/kilas-ai/agent/connections/google/callback",
               "KILAS_CONNECTOR_ENCRYPTION_KEY": key}
        with patch.dict(os.environ, env):
            state = {}
            for service in ("calendar", "drive", "contacts"):
                with self.assertRaisesRegex(connectors.ConnectorError, "unknown_google_service"):
                    google_connection.begin(self.owner, service, state)
            self.assertFalse(state)
        self.assertEqual(connectors.TOOLS["calendar.list"][2],
                         "https://www.googleapis.com/auth/calendar.events")
        self.assertEqual(connectors.TOOLS["calendar.get"][2],
                         "https://www.googleapis.com/auth/calendar.events")

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

    def test_gmail_send_prepares_locally_and_sends_only_after_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        with patch.object(connector_flow.google_tools, "gmail_create_draft") as draft, \
             patch.object(connector_flow.google_tools, "gmail_thread") as read, \
             patch.object(connector_actions.google_tools, "gmail_send", return_value={"id": "sent-1"}) as send:
            approval_id = connector_flow._proposal(self.owner, "gmail.send", {
                "to": "test@example.test", "subject": "Verifikasi", "body": "Pesan uji."},
                None, "Kirim email ke test@example.test")
            self.assertEqual(connectors.approval(self.owner, approval_id)["status"], "PENDING")
            draft.assert_not_called()
            read.assert_not_called()
            send.assert_not_called()
            self.assertEqual(connector_actions.execute(self.owner, approval_id)["id"], "sent-1")
            send.assert_called_once_with(self.owner, "test@example.test", "Verifikasi", "Pesan uji.")
        with self.assertRaisesRegex(connectors.ConnectorError, "approval_already_used"):
            connector_actions.execute(self.owner, approval_id)

    def test_draft_only_request_cannot_become_a_send_approval(self):
        with patch.object(connector_flow.google_tools, "gmail_create_draft") as draft:
            with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
                connector_flow._proposal(self.owner, "gmail.send", {
                    "to": "test@example.test", "subject": "Draf", "body": "Belum kirim."},
                    None, "Simpan draft email untuk test@example.test")
            draft.assert_not_called()

    def test_broad_existing_grant_remains_connected_but_other_google_tools_are_disabled(self):
        stamp = connectors.stamp()
        scopes = ['https://www.googleapis.com/auth/' + item for item in
                  ('gmail.send', 'gmail.readonly', 'gmail.compose', 'calendar.events',
                   'calendar.freebusy', 'drive.readonly', 'contacts.readonly')]
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, __import__('json').dumps(scopes), stamp, stamp))
        self.assertEqual(connectors.available_tools(self.owner), ['gmail.send'])
        for tool in ('gmail.search', 'gmail.thread', 'gmail.draft', 'calendar.list',
                     'calendar.freebusy', 'drive.search', 'contacts.search'):
            with self.assertRaisesRegex(connectors.ConnectorError, 'google_tool_disabled'):
                connectors.authorize(self.owner, tool)
        page = self.client_for(self.owner).get('/kilas-ai/agent?view=connections')
        self.assertEqual(page.status_code, 303)
        self.assertTrue(page.location.endswith('/kilas-ai/agent'))
        self.assertEqual(connectors.google_connection(self.owner)['status'],'CONNECTED')
        self.assertNotIn('Google Calendar</strong>', page.text)
        self.assertNotIn('Google Drive</strong>', page.text)
        self.assertNotIn('Google Contacts</strong>', page.text)
        self.assertNotIn('siapkan draf', page.text)

    def test_planner_advertises_only_active_google_send(self):
        from kilas_ai import connector_planner, usage
        import json
        plan = {"tool": "none", "intent": "CLARIFY", "business_id": 0,
                "arguments_json": "{}", "reply": "Fitur itu belum tersedia."}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-never-used"}), \
             patch.object(usage, "reserve", return_value=({}, [("CHAT", 1)])), \
             patch.object(usage, "finish"), \
             patch.object(agent_planner, "_output_text", return_value=json.dumps(plan)), \
             patch.object(connector_planner.requests, "post", return_value=Response(200, {
                 "status": "completed", "usage": {}})) as request:
            connector_planner.propose(self.owner, "Baca Gmail", [],
                ["gmail.send", "gmail.search", "gmail.draft", "calendar.list", "drive.search",
                 "contacts.search"], [], "Asia/Jakarta")
        sent = request.call_args.kwargs["json"]
        self.assertEqual(sent["text"]["format"]["schema"]["properties"]["tool"]["enum"],
                         ["none", "gmail.send"])
        self.assertEqual(json.loads(sent["input"][-1]["content"])["available_tools"],
                         ["gmail.send"])

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
        with patch.object(connector_flow.google_tools, "gmail_thread") as read:
            with self.assertRaisesRegex(connectors.ConnectorError, "recipient_unverified"):
                connector_flow._proposal(self.owner, "gmail.send", {
                    "to": "wilson@example.test", "subject": "Re: Jadwal", "body": "Besok jam 2 bisa.",
                    "thread_id": "thread-1"}, None, "Kirim ke wilson@example.test")
            read.assert_not_called()

    def test_new_email_recipient_is_explicit_or_uniquely_resolved_from_contacts(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        with patch.object(connector_flow.google_tools, "contacts_search") as search:
            with self.assertRaisesRegex(connectors.ConnectorError, "recipient_unverified"):
                connector_flow._proposal(self.owner, "gmail.send", {
                    "to": "", "contact_query": "Wilson", "subject": "Jadwal",
                    "body": "Besok jam 2 bisa."}, None, "Email Wilson bilang besok jam 2 bisa")
            approval_id = connector_flow._proposal(self.owner, "gmail.send", {
                "to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa."},
                None, "Email wilson@example.test bilang besok jam 2 bisa")
            self.assertEqual(connectors.approval(self.owner, approval_id)["target"], "wilson@example.test")
            search.assert_not_called()

    def test_draft_only_saves_gmail_draft_without_send_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.compose"]', stamp, stamp))
        with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
            connectors.authorize(self.owner, "gmail.draft")
        self.assertNotIn("gmail.draft", connectors.available_tools(self.owner))
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_action_approvals "
                         "WHERE user_id=?", (self.owner,))["n"], 0)

    def test_edit_cancels_old_approval_and_preserves_target_context(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        approval_id = connectors.propose_action(self.owner, "gmail.send", "wilson@example.test",
            {"to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa."})
        another_id = connectors.propose_action(self.owner, "gmail.send", "daniel@example.test",
            {"to": "daniel@example.test", "subject": "Rapat", "body": "Senin jam 10 bisa."})
        client = self.client_for(self.owner)
        approvals_page = client.get("/kilas-ai/agent")
        self.assertNotIn("wilson@example.test", approvals_page.text)
        self.assertNotIn("daniel@example.test", approvals_page.text)
        self.assertEqual(connectors.approval(self.owner, another_id)["status"], "PENDING")
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
        with patch.object(connector_flow.connector_planner, "propose") as planner, \
             patch.object(connector_flow.google_tools, "gmail_search") as search, \
             patch.object(connector_flow.google_tools, "gmail_create_draft") as draft:
            with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
                connector_flow.scheduled_read(self.owner,
                    "setiap pagi cek email penting dan siapkan draf balasan", "Asia/Jakarta", run_id=77)
            planner.assert_not_called()
            search.assert_not_called()
            draft.assert_not_called()

    def test_edited_gmail_draft_cannot_be_sent_under_old_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.send"]', stamp, stamp))
        approval_id = connectors.propose_action(self.owner, "gmail.send", "wilson@example.test", {
            "to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa.",
            "draft_id": "old-draft"})
        with patch.object(connector_actions.google_tools, "gmail_send") as send, \
             patch.object(connector_actions.google_tools, "gmail_send_draft") as draft:
            with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
                connector_actions.execute(self.owner, approval_id)
            send.assert_not_called()
            draft.assert_not_called()
        self.assertEqual(connectors.approval(self.owner, approval_id)["status"], "FAILED")

    def test_calendar_delete_uses_verified_event_and_single_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/calendar.events"]', stamp, stamp))
        with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
            connectors.authorize(self.owner, "calendar.delete")
        self.assertNotIn("calendar.delete", connectors.available_tools(self.owner))

    def test_drive_and_contacts_are_read_only_and_account_scoped(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/drive.readonly",'
             '"https://www.googleapis.com/auth/contacts.readonly"]', stamp, stamp))
        self.assertEqual(connectors.available_tools(self.owner), [])
        self.assertEqual(connectors.available_tools(self.other), [])
        for tool in ("drive.search", "drive.read", "contacts.search"):
            with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
                connectors.authorize(self.owner, tool)

    def test_whatsapp_proposal_cannot_switch_business(self):
        business_a = repo.create_business(self.owner, "WA A")
        business_b = repo.create_business(self.owner, "WA B")
        visible = [{"provider": "WHATSAPP", "business_id": business_a,
                    "status": "CONNECTED", "display_identity": "WA A"}]
        with patch.object(connectors, "business_connections", return_value=visible), \
             patch.object(connector_flow.internal_tools, "whatsapp_thread", return_value={
                 "customer_phone": "+62811111111", "messages": []}):
            with self.assertRaisesRegex(connectors.ConnectorError, "not_connected"):
                connector_flow._proposal(self.owner, "whatsapp.send", {
                    "conversation_id": "conversation-1", "text": "Besok bisa."}, business_b)
            approval_id = connector_flow._proposal(self.owner, "whatsapp.send", {
                "conversation_id": "conversation-1", "text": "Besok bisa."}, business_a)
        self.assertEqual(connectors.approval(self.owner, approval_id)["business_id"], business_a)

    def test_finance_read_binds_business_and_branch_before_service_call(self):
        business_a = repo.create_business(self.owner, "Finance A")
        business_b = repo.create_business(self.owner, "Finance B")
        scoped = []

        @contextmanager
        def scope(business_id, branch_id, actor_user_id):
            scoped.append((business_id, branch_id, actor_user_id))
            yield

        visible = [{"provider": "FINANCE", "business_id": business_a,
                    "status": "CONNECTED", "display_identity": "Finance A"}]
        with patch.object(connectors, "business_connections", return_value=visible), \
             patch.object(internal_tools.finance_branches, "scope", side_effect=scope), \
             patch.object(internal_tools.finance_service, "get_account_balance_report", return_value=[{
                 "id": 7, "name": "BCA", "currency": "IDR", "account_type": "BANK",
                 "balance_minor": 125000, "branch_id": 9}]) as report:
            result = internal_tools.finance_read(self.owner, business_a, "finance.accounts", branch_id=9)
            self.assertEqual(result[0]["balance_minor"], 125000)
            self.assertEqual(scoped, [(business_a, 9, self.owner)])
            report.assert_called_once()
            with self.assertRaisesRegex(connectors.ConnectorError, "not_connected"):
                internal_tools.finance_read(self.owner, business_b, "finance.accounts", branch_id=9)

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
        self.assertEqual(agent_planner.required_connection(
            "Check my availability tomorrow between 1 PM and 5 PM."), "Google Calendar")

    def test_contacts_empty_warm_cache_is_retried_once_without_writes(self):
        tools = connector_actions.google_tools
        result = {"results": [{"person": {"names": [{"displayName": "Google Verification Test"}],
                  "emailAddresses": [{"value": "qa@example.test"}]}}]}
        with patch.object(tools, "_request", side_effect=[{}, {}, result]) as request, \
             patch.object(tools.time, "sleep") as wait:
            rows = tools.contacts_search(self.owner, "Google Verification Test")
        self.assertEqual(rows[0]["emails"], ["qa@example.test"])
        wait.assert_called_once_with(3)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(request.call_args_list[0].kwargs["params"]["query"], "")
        for call in request.call_args_list:
            self.assertEqual(call.args[1:5], ("contacts.search", "people", "GET", "/people:searchContacts"))
        self.assertEqual(request.call_args_list[1].kwargs, request.call_args_list[2].kwargs)

    def test_connector_quota_error_is_truthful_and_stops_before_provider(self):
        from kilas_ai import connector_planner, usage
        notice = "Kuota Kilas tambahan belum cukup. Tambah Kuota untuk melanjutkan fitur ini."
        with patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-never-used"}), \
             patch.object(usage, "reserve", side_effect=usage.UsageLimit(notice)), \
             patch.object(connector_planner.requests, "post") as provider:
            with self.assertRaises(usage.UsageLimit):
                connector_planner.propose(self.owner, "Read Gmail", [], ["gmail.search"], [], "Asia/Jakarta")
            provider.assert_not_called()
        client = self.client_for(self.owner)
        with patch.object(connectors, "available_tools", return_value=["gmail.search"]), \
             patch.object(connector_flow, "handle", side_effect=usage.UsageLimit(notice)) as flow:
            response = client.post("/kilas-ai/agent/chat", data={
                "csrf_token": "connector-csrf", "message": "Find Google Verification Test in Gmail"})
        self.assertEqual(response.status_code, 303)
        page = client.get(response.location)
        self.assertIn("Kilas AI tidak mengakses koneksi akun", page.text)
        flow.assert_not_called()

    def test_production_english_schedule_keeps_google_runner_and_explicit_zone(self):
        instruction = ('Every morning at 8 AM Asia/Jakarta, check only my emails with subject '
                       '"Google Verification Test" and prepare a draft reply if something needs attention.')
        self.assertEqual(agent_planner.required_connection(instruction), "Gmail")
        client = self.client_for(self.owner)
        with patch.object(connectors, "available_tools", return_value=["gmail.send"]):
            response = client.post("/kilas-ai/agent/chat", data={
                "csrf_token": "connector-csrf", "message": instruction})
        self.assertEqual(response.status_code, 303)
        with client.session_transaction() as state:
            self.assertNotIn("automation_preview", state)
        self.assertIn("Kilas AI tidak mengakses koneksi akun", client.get(response.location).text)

    def test_calendar_planner_iso_strings_still_require_safe_offsets(self):
        tools = connector_actions.google_tools
        args = {"summary": "Google Verification Demo", "start": "2026-10-02T15:00:00+07:00",
                "end": "2026-10-02T15:30:00+07:00"}
        payload = tools._event_payload(args)
        self.assertEqual(payload["start"], {"dateTime": args["start"]})
        for bad in ({**args, "start": "2026-10-02T15:00:00"},
                    {**args, "end": "2026-10-02T14:30:00+07:00"},
                    {**args, "summary": ""}):
            with self.assertRaisesRegex(connectors.ConnectorError, "invalid_event"):
                tools._event_payload(bad)

    def test_calendar_create_is_approval_gated_and_single_use(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/calendar.events"]', stamp, stamp))
        with patch.object(connector_actions.google_tools, "calendar_create") as create:
            with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
                connectors.propose_action(self.owner, "calendar.create", "primary", {
                    "summary": "Google Verification Demo"})
            create.assert_not_called()

    def test_scheduled_self_mail_requires_explicit_owned_address_and_never_sends(self):
        with patch.object(connector_flow.google_tools, "gmail_search") as search, \
             patch.object(connector_flow.google_tools, "gmail_send") as send:
            with self.assertRaisesRegex(connectors.ConnectorError, "google_tool_disabled"):
                connector_flow.scheduled_read(self.owner,
                    "prepare a Gmail draft reply to owner@example.test", "Asia/Jakarta", run_id=89)
            search.assert_not_called()
            send.assert_not_called()

    def test_calendar_move_resolves_exact_title_and_freezes_same_event(self):
        event = {"id": "verified-event", "summary": "Google Verification Demo",
                 "start": {"dateTime": "2026-10-02T15:00:00+07:00"},
                 "end": {"dateTime": "2026-10-02T15:30:00+07:00"}}
        tools = connector_flow.google_tools
        with patch.object(tools, "calendar_named_event", return_value=event) as resolve, \
             patch.object(tools, "calendar_get", return_value=event), \
             patch.object(connectors, "propose_action", return_value=123) as proposal, \
             patch.object(tools, "calendar_update") as write:
            connector_flow._proposal(self.owner, "calendar.update", {
                "event_query": "Google Verification Demo",
                "start": "2026-10-02T15:30:00+07:00"}, None,
                "Move Google Verification Demo to 3:30 PM.")
        resolve.assert_called_once_with(self.owner, "Google Verification Demo")
        write.assert_not_called()
        self.assertEqual(proposal.call_args.args[2], "verified-event")
        payload = proposal.call_args.args[3]
        self.assertEqual(payload["summary"], "Google Verification Demo")
        self.assertEqual(payload["end"]["dateTime"], "2026-10-02T16:00:00+07:00")
        with patch.object(tools, "_request", return_value={"items": [event, event]}):
            with self.assertRaisesRegex(connectors.ConnectorError, "ambiguous_event"):
                tools.calendar_named_event(self.owner, "Google Verification Demo")
        with patch.object(tools, "_request", return_value={"items": [event], "nextPageToken": "more"}):
            with self.assertRaisesRegex(connectors.ConnectorError, "ambiguous_event"):
                tools.calendar_named_event(self.owner, "Google Verification Demo")

    def test_freebusy_renders_provider_times_in_account_timezone(self):
        with patch.object(connector_flow.google_tools, "calendar_freebusy", return_value=[{
            "start": "2026-10-02T07:00:00Z", "end": "2026-10-02T08:00:00Z"}]):
            message = connector_flow._read(self.owner, "calendar.freebusy", {
                "start": "2026-10-02T13:00:00+07:00", "end": "2026-10-02T17:00:00+07:00"},
                None, "Asia/Jakarta")
        self.assertIn("02/10/2026 14:00", message)
        self.assertIn("02/10/2026 15:00", message)
        self.assertIn("Asia/Jakarta", message)
        self.assertNotIn("07:00:00Z", message)

    def test_google_read_answer_has_no_write_stage_and_settles_usage(self):
        from kilas_ai import automation_runner, usage
        with patch.object(usage, "reserve", return_value=({}, [("CHAT", 1)])), \
             patch.object(automation_runner, "_plain_ai", return_value=(
                 "This email is a safe synthetic integration test.", "openai", "synthetic-model", {})) as answer, \
             patch.object(usage, "finish") as finish, \
             patch.object(connector_actions, "execute") as write:
            result = connector_flow._read_answer(self.owner, "Summarize the test email.",
                "This is a safe synthetic integration test.", "Asia/Jakarta")
        self.assertIn("safe synthetic", result)
        self.assertIn("verified_results", answer.call_args.args[0])
        self.assertIn("No actions are available", answer.call_args.args[0])
        finish.assert_called_once()
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
