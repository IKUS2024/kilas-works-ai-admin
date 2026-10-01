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
            requested_scope = parse_qs(urlparse(url).query)["scope"][0]
            self.assertNotIn("https://www.googleapis.com/auth/gmail.send", requested_scope)
            self.assertIn("https://www.googleapis.com/auth/userinfo.email", requested_scope)
            self.assertNotIn(raw, str(db.query_all("SELECT * FROM kilas_ai_oauth_states")))
            with self.assertRaisesRegex(connectors.ConnectorError, "invalid_oauth_state"):
                google_connection.complete(self.other, state, raw, "code")
            with patch.object(google_connection.requests, "post", return_value=Response(200, {
                    "access_token": "synthetic-access", "refresh_token": "synthetic-refresh",
                    "expires_in": 3600,
                    "scope": "openid https://www.googleapis.com/auth/userinfo.email "
                             "https://www.googleapis.com/auth/gmail.readonly "
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

    def test_calendar_oauth_requests_only_minimum_event_scopes(self):
        key = Fernet.generate_key().decode()
        env = {"KILAS_GOOGLE_CLIENT_ID": "synthetic-client-id",
               "KILAS_GOOGLE_CLIENT_SECRET": "synthetic-secret",
               "KILAS_GOOGLE_REDIRECT_URI": "https://app.example.test/kilas-ai/agent/connections/google/callback",
               "KILAS_CONNECTOR_ENCRYPTION_KEY": key}
        with patch.dict(os.environ, env):
            state = {}
            url = google_connection.begin(self.owner, "calendar", state)
            requested = set(parse_qs(urlparse(url).query)["scope"][0].split())
        self.assertIn("https://www.googleapis.com/auth/calendar.events", requested)
        self.assertIn("https://www.googleapis.com/auth/calendar.freebusy", requested)
        self.assertNotIn("https://www.googleapis.com/auth/calendar.events.readonly", requested)
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
            (self.owner, '["https://www.googleapis.com/auth/gmail.compose"]', t, t))
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
             '"https://www.googleapis.com/auth/gmail.compose"]', stamp, stamp))
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

    def test_new_email_recipient_is_explicit_or_uniquely_resolved_from_contacts(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.compose",'
             '"https://www.googleapis.com/auth/contacts.readonly"]', stamp, stamp))
        draft = {"draft_id": "synthetic-draft"}
        with patch.object(connector_flow.google_tools, "gmail_create_draft", return_value=draft), \
             patch.object(connector_flow.google_tools, "contacts_search", return_value=[
                 {"name": "Wilson", "emails": ["wilson@example.test"]}]) as search:
            approval_id = connector_flow._proposal(self.owner, "gmail.send", {
                "to": "", "contact_query": "Wilson", "subject": "Jadwal",
                "body": "Besok jam 2 bisa."}, None, "Email Wilson bilang besok jam 2 bisa")
            self.assertEqual(search.call_count, 1)
            payload = __import__("json").loads(connectors.approval(self.owner, approval_id)["payload_json"])
            self.assertEqual(payload["to"], "wilson@example.test")
            with self.assertRaisesRegex(connectors.ConnectorError, "recipient_unverified"):
                connector_flow._proposal(self.owner, "gmail.send", {
                    "to": "stranger@example.test", "contact_query": "Wilson",
                    "subject": "Jadwal", "body": "Besok jam 2 bisa."}, None,
                    "Email Wilson bilang besok jam 2 bisa")
            explicit = connector_flow._proposal(self.owner, "gmail.send", {
                "to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa."},
                None, "Email wilson@example.test bilang besok jam 2 bisa")
            self.assertEqual(connectors.approval(self.owner, explicit)["target"], "wilson@example.test")
        with patch.object(connector_flow.google_tools, "contacts_search", return_value=[
                {"emails": ["wilson@example.test", "other@example.test"]}]):
            with self.assertRaisesRegex(connectors.ConnectorError, "ambiguous_contact"):
                connector_flow._proposal(self.owner, "gmail.send", {
                    "to": "", "contact_query": "Wilson", "subject": "Jadwal",
                    "body": "Besok jam 2 bisa."}, None, "Email Wilson bilang besok jam 2 bisa")

    def test_edit_cancels_old_approval_and_preserves_target_context(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.compose"]', stamp, stamp))
        approval_id = connectors.propose_action(self.owner, "gmail.send", "wilson@example.test",
            {"to": "wilson@example.test", "subject": "Jadwal", "body": "Besok jam 2 bisa."})
        another_id = connectors.propose_action(self.owner, "gmail.send", "daniel@example.test",
            {"to": "daniel@example.test", "subject": "Rapat", "body": "Senin jam 10 bisa."})
        client = self.client_for(self.owner)
        approvals_page = client.get("/kilas-ai/agent")
        self.assertIn("wilson@example.test", approvals_page.text)
        self.assertIn("daniel@example.test", approvals_page.text)
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
            results = [connector_flow.scheduled_read(self.owner,
                "setiap pagi cek email penting dan siapkan draf balasan", "Asia/Jakarta", run_id=77)
                for _ in range(2)]
        self.assertIn("belum dikirim", results[0])
        self.assertIn("sudah disiapkan", results[1])
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

    def test_calendar_delete_uses_verified_event_and_single_approval(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/calendar.events"]', stamp, stamp))
        with patch.object(connector_flow.google_tools, "calendar_get", return_value={
                "id": "event-1", "summary": "Meeting Wilson"}) as read:
            approval_id = connector_flow._proposal(self.owner, "calendar.delete",
                                                    {"event_id": "event-1"}, None)
            read.assert_called_once_with(self.owner, "event-1")
        row = connectors.approval(self.owner, approval_id)
        self.assertIn("Meeting Wilson", row["payload_json"])
        with patch.object(connector_actions.google_tools, "calendar_delete", return_value={
                "id": "event-1"}) as delete:
            self.assertEqual(connector_actions.execute(self.owner, approval_id)["id"], "event-1")
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_already_used"):
                connector_actions.execute(self.owner, approval_id)
            delete.assert_called_once()

    def test_drive_and_contacts_are_read_only_and_account_scoped(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/drive.readonly",'
             '"https://www.googleapis.com/auth/contacts.readonly"]', stamp, stamp))
        self.assertIn("drive.search", connectors.available_tools(self.owner))
        self.assertIn("contacts.search", connectors.available_tools(self.owner))
        self.assertNotIn("drive.search", connectors.available_tools(self.other))
        self.assertFalse(any(tool.startswith("drive.") and connectors.TOOLS[tool][1] != "READ"
                             for tool in connectors.TOOLS))
        with patch.object(connector_flow.google_tools, "drive_search", return_value=[{
                "id": "file-1", "name": "Proposal Wilson", "mimeType": "text/plain"}]), \
             patch.object(connector_flow.google_tools, "drive_read", return_value={
                 "file": {"name": "Proposal Wilson"}, "content": "Verified proposal text"}):
            self.assertIn("Verified proposal text", connector_flow._read(self.owner, "drive.search",
                {"query": "Wilson", "read": True}, None))
        with patch.object(connector_flow.google_tools, "contacts_search", return_value=[{
                "name": "Wilson", "emails": ["wilson@example.test"], "phones": [], "organizations": []}]):
            self.assertIn("wilson@example.test", connector_flow._read(self.owner, "contacts.search",
                {"query": "Wilson"}, None))

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
             patch.object(connector_flow, "handle", side_effect=usage.UsageLimit(notice)):
            response = client.post("/kilas-ai/agent/chat", data={
                "csrf_token": "connector-csrf", "message": "Find Google Verification Test in Gmail"})
        self.assertEqual(response.status_code, 303)
        page = client.get(response.location)
        self.assertIn(notice, page.text)
        self.assertNotIn("Periksa tujuan dan izin", page.text)

    def test_production_english_schedule_keeps_google_runner_and_explicit_zone(self):
        from datetime import datetime, timezone
        instruction = ('Every morning at 8 AM Asia/Jakarta, check only my emails with subject '
                       '"Google Verification Test" and prepare a draft reply if something needs attention. '
                       'Never send email automatically.')
        self.assertEqual(agent_planner.required_connection(instruction), "Gmail")
        self.assertEqual(agent_planner.required_connection(
            "Create an event called Google Verification Demo tomorrow at 3 PM"), "Google Calendar")
        client = self.client_for(self.owner)
        with patch.object(connectors, "available_tools", return_value=["gmail.search", "gmail.draft"]):
            response = client.post("/kilas-ai/agent/chat", data={
                "csrf_token": "connector-csrf", "message": instruction})
        self.assertEqual(response.status_code, 303)
        with client.session_transaction() as state:
            stored = state["automation_preview"]["spec"]
            self.assertIs(stored["condition"]["connector_read"], True)
            self.assertEqual(stored["timezone"], "Asia/Jakarta")
        spec = automation_schedule.parse(instruction, "Asia/Bangkok",
            now=datetime(2026, 10, 1, 7, tzinfo=timezone.utc))
        self.assertEqual(spec["timezone"], "Asia/Jakarta")
        self.assertEqual(spec["schedule"], {"kind": "daily", "hour": 8, "minute": 0})
        with self.assertRaises(automation_schedule.ScheduleError):
            automation_schedule.parse(instruction + " Then send email to everyone.")

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
        with patch.object(connector_actions.google_tools, "calendar_create", return_value={
                "id": "verified-created-event"}) as create:
            approval_id = connector_flow._proposal(self.owner, "calendar.create", {
                "summary": "Google Verification Demo", "start": "2026-10-02T15:00:00+07:00",
                "end": "2026-10-02T15:30:00+07:00"}, None)
            create.assert_not_called()
            connector_actions.execute(self.owner, approval_id)
            with self.assertRaisesRegex(connectors.ConnectorError, "approval_already_used"):
                connector_actions.execute(self.owner, approval_id)
            create.assert_called_once()

    def test_scheduled_self_mail_requires_explicit_owned_address_and_never_sends(self):
        stamp = connectors.stamp()
        db.execute("INSERT INTO kilas_ai_connections "
            "(user_id,provider,status,display_identity,scopes_json,permission_json,credential_enc,created_at,updated_at) "
            "VALUES (?,'GOOGLE','CONNECTED','owner@example.test',?,'{}','encrypted-fixture',?,?)",
            (self.owner, '["https://www.googleapis.com/auth/gmail.compose"]', stamp, stamp))
        plans = {"tool": "gmail.draft", "intent": "PREPARE", "arguments": {
            "to": "owner@example.test", "subject": "Re: Google Verification Test", "body": "Safe test."}}
        tools = connector_flow.google_tools
        with patch.object(tools, "gmail_search", return_value=[{
                "thread_id": "self-thread", "subject": "Google Verification Test"}]), \
             patch.object(tools, "gmail_thread", return_value=[{
                "from": "Owner <owner@example.test>", "message_id": "<safe@example.test>"}]), \
             patch.object(connector_flow.connector_planner, "propose", return_value=plans), \
             patch.object(tools, "gmail_create_draft", return_value={"draft_id": "safe-draft"}) as draft, \
             patch.object(tools, "gmail_send") as send, \
             patch.object(tools, "gmail_send_draft") as send_draft:
            first = connector_flow._scheduled_gmail_draft(self.owner, "prepare a draft reply", {}, "Asia/Jakarta", 88)
            self.assertIn("Tidak ada draf", first)
            draft.assert_not_called()
            second = connector_flow._scheduled_gmail_draft(self.owner,
                "prepare a draft reply to owner@example.test", {}, "Asia/Jakarta", 89)
            self.assertIn("belum dikirim", second)
            draft.assert_called_once()
            send.assert_not_called()
            send_draft.assert_not_called()
        self.assertEqual(connectors.approval_for_key(self.owner,
            __import__('hashlib').sha256(b'automation-draft:89').hexdigest()[:48])["status"], "PENDING")

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
