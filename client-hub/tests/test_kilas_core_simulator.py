"""Offline simulator coverage. No migration runner, production DB, or live model calls."""
import ast
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from unittest.mock import Mock, patch

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUB))
from kilas_core.adapters.simulator import FAILURE_REPLY, simulate_message
from kilas_core import service


class SimulationStore:
    """Only the six allowed simulator persistence capabilities are exposed."""
    def __init__(self):
        self.rows = []
        self.audits = []
        self.progress = []

    def get_ai_settings(self, business_id):
        return {"normalized_config": {"business_name": str(business_id)}}

    def get_simulation_history(self, business_id, session_token, limit=20):
        return [r for r in self.rows if r["business_id"] == business_id
                and r["session_token"] == session_token][-limit:]

    def reserve_simulation_user_message(self, business_id, session_token, content):
        if sum(r["role"] == "user" and r["business_id"] == business_id for r in self.rows) >= 30:
            return False
        self.save_simulation_message(business_id, session_token, "user", content)
        return True

    def save_simulation_message(self, business_id, session_token, role, content):
        self.rows.append(dict(id=len(self.rows)+1, business_id=business_id,
                              session_token=session_token, role=role, content=content))

    def mark_onboarding_step_done(self, business_id, step):
        self.progress.append((business_id, step))

    def write_audit(self, actor_id, business_id, action, detail):
        self.audits.append((actor_id, business_id, action, detail))


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.store = SimulationStore()
        self.provider = Mock(return_value=("Jawaban", None))

    def send(self, payload=None, **changes):
        args = dict(business={"id": 7, "business_name": "Seven"}, session_token="session-7",
                    actor_id=1, payload={"message": " Halo "} if payload is None else payload,
                    repository=self.store, reply_provider=self.provider)
        args.update(changes)
        return simulate_message(**args)

    def test_core_called_and_existing_ui_contract_retained(self):
        with patch.object(service, "process_message", wraps=service.process_message) as core:
            body, code = self.send()
        self.assertEqual((body, code), ({"reply": "Jawaban", "message_id": 2}, 200))
        core.assert_called_once()
        self.assertEqual(core.call_args.args[0].business_id, 7)
        self.assertEqual([r["content"] for r in self.store.rows], ["Halo", "Jawaban"])
        self.assertEqual(self.store.progress, [(7, "simulated_done")])
        self.provider.assert_called_once_with({"id": 7, "business_name": "Seven"},
                                              {"business_name": "7"}, [], "Halo")

    def test_tenant_and_session_history_are_separate(self):
        self.store.save_simulation_message(8, "session-7", "user", "Other tenant secret")
        self.store.save_simulation_message(7, "another-session", "user", "Other session secret")
        for n in range(12):
            self.store.save_simulation_message(7, "session-7", "assistant", str(n))
        self.send({"message": "new", "business_id": 8, "conversation_id": "another-session",
                   "actor_type": "system", "channel": "whatsapp", "session_token": "forged"})
        self.assertEqual([r["content"] for r in self.provider.call_args.args[2]],
                         [str(n) for n in range(2, 12)])
        self.assertEqual(self.provider.call_args.args[0]["id"], 7)

    def test_invalid_messages_media_ids_and_scope_have_no_writes(self):
        for payload in ({"message": ""}, {"message": None}, {"message": 7},
                        {"message": "x" * 16001}, [], {"message": "hi", "media": ["a.jpg"]},
                        {"message": "hi", "attachments": ["a.pdf"]},
                        {"message": "hi", "external_message_id": "event-1"}):
            self.assertEqual(self.send(payload)[1], 400)
        for changes in (dict(business=None), dict(business={"id": 0}), dict(actor_id=None)):
            self.assertEqual(self.send(**changes)[1], 404)
        self.assertEqual(self.send(session_token=None)[1], 400)
        self.provider.assert_not_called()
        self.assertEqual(self.store.rows, [])
        self.assertEqual(self.store.progress, [])

    def test_repeated_external_id_rejected_but_legacy_text_is_new_attempt(self):
        payload = {"message": "same", "external_message_id": "event-1"}
        for _ in range(2):
            self.assertEqual(self.send(payload), ({"error": "unsupported_external_message_id"}, 400))
        self.provider.assert_not_called()
        for _ in range(2):
            self.assertEqual(self.send({"message": "same"})[1], 200)
        self.assertEqual(len(self.store.rows), 4)
        self.assertEqual(self.provider.call_count, 2)

    def test_provider_failure_preserves_reserved_attempt_and_generic_history(self):
        for raised in (False, True):
            with self.subTest(raised=raised):
                self.setUp()
                if raised:
                    self.provider.side_effect = RuntimeError("SECRET")
                else:
                    self.provider.return_value = (None, "SECRET")
                body, code = self.send()
                self.assertEqual((body["reply"], code), (FAILURE_REPLY, 200))
                self.assertEqual([r["role"] for r in self.store.rows], ["user", "assistant"])
                self.assertEqual(self.store.audits, [(1, 7, "simulation_error", "provider_error")])
                self.assertEqual(self.store.progress, [(7, "simulated_done")])
                self.provider.assert_called_once()

    def test_quota_rejection_never_calls_provider_or_appends_assistant(self):
        for n in range(30):
            self.store.save_simulation_message(7, "other-browser", "user", str(n))
        before = list(self.store.rows)
        body, code = self.send()
        self.assertEqual(code, 429)
        self.assertEqual(body["error"], "daily_simulation_quota")
        self.assertIsNone(body["message_id"])
        self.assertEqual(self.store.rows, before)
        self.assertEqual(self.store.progress, [])
        self.provider.assert_not_called()
        self.assertEqual(self.send(business={"id": 8, "business_name": "Eight"})[1], 200)

    def test_no_whatsapp_jobs_finance_search_or_checkout_capability(self):
        # Runtime spies catch accidental calls even if exceptions are swallowed by the core.
        forbidden = ("send_whatsapp", "create_job", "create_transaction", "create_finance_invoice",
                     "search_products", "create_checkout", "record_invoice_payment")
        spies = {name: Mock(side_effect=AssertionError(name)) for name in forbidden}
        for name, spy in spies.items():
            setattr(self.store, name, spy)
        self.provider.return_value = ("[CREATE_JOB] [PAYMENT] [SEND_WHATSAPP]", None)
        self.send({"message": "Buat invoice dan kirim WhatsApp sekarang"})
        for spy in spies.values():
            spy.assert_not_called()
        # Phase 1 safety boundary: the simulator processing path itself must never gain live
        # business-write/IO dependencies. Later Kilas Core packages (Customers, Jobs, etc.) may
        # legitimately persist data, so inspect the exact Phase 1 execution modules rather than
        # every future file placed under kilas_core/.
        allowed_imports = {"dataclasses", "datetime", "os", "re", "collections.abc",
                           "contracts", "service"}
        phase1_modules = (
            HUB / "kilas_core" / "contracts.py",
            HUB / "kilas_core" / "service.py",
            HUB / "kilas_core" / "flags.py",
            HUB / "kilas_core" / "adapters" / "simulator.py",
        )
        for path in phase1_modules:
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(n.name in allowed_imports for n in node.names), str(path))
                elif isinstance(node, ast.ImportFrom):
                    self.assertTrue(node.module in allowed_imports or
                                    (node.module is None and node.level and
                                     all(n.name == "service" for n in node.names)), str(path))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("open", "exec", "eval", "__import__"))


class RouteTests(unittest.TestCase):
    """Real hub hooks, authentication, repository SQL and provider; disposable minimal schema.

    The schema below is only a test fixture for existing tables. No migration files are read
    or executed. Startup seeders/diagnostics are stubbed; init_schema is a failing tripwire.
    """
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="kilas-core-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.env = patch.dict(os.environ, {
            "DATABASE_URL": "", "CLIENT_HUB_DB_PATH": str(Path(cls.temp.name) / "simulator.db"),
            "RUN_MIGRATIONS_ON_BOOT": "false", "SECRET_KEY": "phase1-test-only",
            "CLIENT_HUB_ENV": "development", "KILAS_CORE_V2_ENABLED": "false",
            "KILAS_CORE_V2_TEST_BUSINESS_IDS": "", "ANTHROPIC_API_KEY": "",
            "WHATSAPP_ACCESS_TOKEN": "",
        })
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        cls.db = importlib.import_module("db")
        assert cls.db.BACKEND == "sqlite"
        assert Path(cls.db.SQLITE_PATH).parent == Path(cls.temp.name)
        cls.addClassCleanup(cls.db.reset_connection_for_new_db_path)
        cls.db.get_connection().executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email TEXT UNIQUE,
                password_hash TEXT,
                role TEXT,
                full_name TEXT
            );
            CREATE TABLE businesses (
                id INTEGER PRIMARY KEY,
                tenant_slug TEXT UNIQUE,
                business_name TEXT,
                package TEXT,
                status TEXT,
                whatsapp_connected INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE business_memberships (business_id INTEGER, user_id INTEGER);
            CREATE TABLE business_profiles (business_id INTEGER PRIMARY KEY, category TEXT);
            CREATE TABLE platform_workspace_scope (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                business_id INTEGER NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE platform_workspace_outbound (
                event_id TEXT PRIMARY KEY,
                customer_phone TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE ai_settings (business_id INTEGER, normalized_config_json TEXT);
            CREATE TABLE simulation_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER, session_token TEXT, role TEXT, content TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP, flagged_wrong INTEGER DEFAULT 0, flag_note TEXT);
            CREATE TABLE onboarding_status (business_id INTEGER PRIMARY KEY, simulated_done INTEGER, updated_at TEXT);
            CREATE TABLE audit_log (id INTEGER PRIMARY KEY, actor_user_id INTEGER, business_id INTEGER,
                action TEXT, detail TEXT, project_id INTEGER);
        """)
        cls.migration_guard = patch.object(cls.db, "init_schema", side_effect=AssertionError("No migrations"))
        cls.migrations = cls.migration_guard.start()
        cls.addClassCleanup(cls.migration_guard.stop)
        with patch("catalog_service.seed_catalog_if_needed"), patch("talent_service.seed_talents_if_needed"), \
                patch("ai_usage.startup_schema_check"):
            cls.hub = importlib.import_module("app")
        assert Path(cls.hub.__file__).resolve() == HUB / "app.py", "Never import root WhatsApp app"
        cls.app = cls.hub.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.repo = importlib.import_module("repo")
        cls.ai = importlib.import_module("ai_onboarding")
        cls.finance = importlib.import_module("finance_service")

    def setUp(self):
        db = self.db
        conn = db.get_connection()
        conn.set_authorizer(None)
        for table in ("platform_workspace_outbound", "platform_workspace_scope",
                      "users", "businesses", "business_memberships", "ai_settings", "simulation_messages",
                      "onboarding_status", "audit_log"):
            db.execute("DELETE FROM " + table)
        db.execute("DELETE FROM sqlite_sequence WHERE name='simulation_messages'")
        for uid in (1, 2):
            db.execute("INSERT INTO users(id,role) VALUES (?, 'CLIENT_OWNER')", (uid,))
        for bid in (7, 8):
            db.execute(
                "INSERT INTO businesses(id,business_name,package,status) VALUES (?, ?, 'AI_ADMIN', 'ACTIVE')",
                (bid, str(bid)),
            )
            db.execute("INSERT INTO business_memberships VALUES (?, 1)", (bid,))
            db.execute("INSERT INTO ai_settings (business_id,normalized_config_json) VALUES (?, ?)", (bid, '{"description":"Tenant ' + str(bid) + '"}'))
            db.execute("INSERT INTO onboarding_status VALUES (?, 0, NULL)", (bid,))
        db.execute(
            "INSERT INTO businesses(id,business_name,package,status) VALUES (9, 'Archived', 'AI_ADMIN', 'ARCHIVED')"
        )
        db.execute("INSERT INTO business_memberships VALUES (9, 1)")
        self.flag = patch.dict(os.environ, {"KILAS_CORE_V2_ENABLED": "true",
                                          "KILAS_CORE_V2_TEST_BUSINESS_IDS": "7,8"})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user_id=1, role="CLIENT_OWNER", sim_token_7="session-7",
                           sim_token_8="session-8", _csrf_token="csrf-test")
        self.network_patch = patch("requests.sessions.Session.request", side_effect=AssertionError("No live network"))
        self.network = self.network_patch.start()
        self.addCleanup(self.network_patch.stop)
        self.denied_writes = []
        def authorize(action, table, column, database, source):
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                if table not in ("simulation_messages", "onboarding_status", "audit_log", "sqlite_sequence"):
                    if not (table == "businesses" and action == sqlite3.SQLITE_UPDATE and column == "id"):
                        self.denied_writes.append((action, table, column))
                        return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        conn.set_authorizer(authorize)
        self.addCleanup(conn.set_authorizer, None)

    def tearDown(self):
        self.network.assert_not_called()
        self.migrations.assert_not_called()
        self.assertEqual(self.denied_writes, [])

    def post(self, payload=None, bid=7, csrf=True, client=None):
        return (client or self.client).post(f"/business/{bid}/simulate/message",
                    json=payload if payload is not None else {"message": "Halo"},
                    headers={"X-CSRF-Token": "csrf-test"} if csrf else {})

    def rows(self):
        return self.db.query_all("SELECT * FROM simulation_messages ORDER BY id")

    def test_flag_off_legacy_and_flag_on_parity(self):
        for enabled, allowed, expect_core in (("false", "7,8", False), ("true", "8", False),
                                               ("true", "7,8", True)):
            self.setUpFlag(enabled, allowed)
            with patch.object(self.ai, "simulate_customer_reply", return_value=("Reply", None)) as provider, \
                    patch.object(service, "process_message", wraps=service.process_message) as core:
                response = self.post({"message": "  Halo  "})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"reply": "Reply", "message_id": len(self.rows())})
            self.assertEqual(core.call_count, int(expect_core))
            provider.assert_called_once()
            self.assertEqual(provider.call_args.args[3], "Halo")
            self.assertEqual(self.rows()[-2]["content"], "Halo")
        self.assertEqual(self.db.query_one("SELECT simulated_done FROM onboarding_status WHERE business_id=7")
                         ["simulated_done"], 1)

    def setUpFlag(self, enabled, allowed):
        os.environ["KILAS_CORE_V2_ENABLED"] = enabled
        os.environ["KILAS_CORE_V2_TEST_BUSINESS_IDS"] = allowed

    def test_unauthorized_unknown_archived_and_stale_actor_fail_closed(self):
        with patch.object(self.ai, "simulate_customer_reply") as provider:
            self.assertEqual(self.post(bid=999).status_code, 404)
            self.assertEqual(self.post(bid=9).status_code, 404)
            with self.client.session_transaction() as session:
                session["user_id"] = 2
            self.assertEqual(self.post().status_code, 404)
            with self.client.session_transaction() as session:
                session["user_id"] = 999
            self.assertEqual(self.post().status_code, 302)
            anonymous = self.app.test_client()
            with anonymous.session_transaction() as session:
                session["_csrf_token"] = "csrf-test"
            self.assertEqual(self.post(client=anonymous).status_code, 302)
        provider.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_csrf_and_simulation_session_required_across_products(self):
        with patch.object(self.ai, "simulate_customer_reply") as provider:
            self.assertEqual(self.post(csrf=False).status_code, 400)
            with self.client.session_transaction() as session:
                del session["sim_token_7"]
            self.assertEqual(self.post().get_json(), {"error": "no_session"})
            with self.client.session_transaction() as session:
                session["active_product"] = "finance"
            response = self.post()
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json(), {"error": "no_session"})
        provider.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_tenant_session_and_payload_forgery_isolation(self):
        self.repo.save_simulation_message(8, "session-7", "user", "TENANT_SECRET")
        self.repo.save_simulation_message(7, "other-session", "user", "SESSION_SECRET")
        for n in range(12):
            self.repo.save_simulation_message(7, "session-7", "assistant", str(n))
        with patch.object(self.ai, "simulate_customer_reply", return_value=("Reply", None)) as provider:
            response = self.post({"message": "new", "business_id": 8, "session_token": "other-session",
                                  "channel": "whatsapp", "actor_type": "system"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(provider.call_args.args[0]["id"], 7)
        self.assertEqual(provider.call_args.args[1], {"description": "Tenant 7"})
        self.assertEqual([r["content"] for r in provider.call_args.args[2]], [str(n) for n in range(2, 12)])
        self.assertEqual((self.rows()[-1]["business_id"], self.rows()[-1]["session_token"]), (7, "session-7"))

    def test_quota_real_repository_thirty_first_rejected_across_sessions(self):
        for n in range(29):
            self.repo.save_simulation_message(7, "other-browser", "user", str(n))
        with patch.object(self.ai, "simulate_customer_reply", return_value=("Reply", None)) as provider:
            self.assertEqual(self.post().status_code, 200)
            before = self.rows()
            response = self.post()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.get_json()["error"], "daily_simulation_quota")
            self.assertEqual(self.rows(), before)
            self.assertEqual(self.post(bid=8).status_code, 200)
        self.assertEqual(provider.call_count, 2)

    def test_provider_exception_and_invalid_output_keep_coherent_attempt(self):
        for provider in (Mock(side_effect=RuntimeError("secret")), Mock(return_value=(None, "secret")),
                         Mock(return_value=(None, None))):
            with patch.object(self.ai, "simulate_customer_reply", provider):
                response = self.post()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["reply"], FAILURE_REPLY)
            provider.assert_called_once()
        self.assertEqual(len(self.rows()), 6)
        self.assertEqual(len(self.db.query_all("SELECT * FROM audit_log")), 3)
        self.assertNotIn("secret", repr(self.rows()))

    def test_actual_provider_never_executes_whatsapp_jobs_finance_actions(self):
        targets = ("create_transaction", "create_finance_invoice", "record_invoice_payment")
        spies = []
        for name in targets:
            guard = patch.object(self.finance, name, side_effect=AssertionError("No Finance writes"))
            spies.append(guard.start())
            self.addCleanup(guard.stop)
        # Exercise actual existing simulator provider, mocking only its model transport.
        with patch.object(self.ai, "_call_claude", return_value=("[CREATE_JOB] [SEND_WHATSAPP]", "end_turn", None)) as model:
            response = self.post({"message": "Buat job dan invoice lalu kirim WhatsApp"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["reply"], "[CREATE_JOB] [SEND_WHATSAPP]")
        model.assert_called_once()
        self.assertEqual(model.call_args.kwargs["max_tokens"], 300)
        self.assertEqual(model.call_args.kwargs["model"], self.ai.CLIENT_HUB_SIMULATION_MODEL)
        for spy in spies:
            spy.assert_not_called()
        self.assertEqual(len(self.rows()), 2)

    def test_unsupported_media_event_ids_and_malformed_body_before_quota(self):
        with patch.object(self.ai, "simulate_customer_reply") as provider:
            for payload in ([], {"message": 1}, {"message": "hi", "media_references": ["x.jpg"]},
                            {"message": "hi", "external_message_id": "same"}):
                for _ in range(2):
                    self.assertEqual(self.post(payload).status_code, 400)
        provider.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_browser_payload_cannot_enable_rollout(self):
        self.setUpFlag("false", "7")
        with patch.object(self.ai, "simulate_customer_reply", return_value=("Legacy", None)), \
                patch.object(service, "process_message") as core:
            response = self.post({"message": "Halo", "KILAS_CORE_V2_ENABLED": True,
                                  "KILAS_CORE_V2_TEST_BUSINESS_IDS": "7"})
        self.assertEqual(response.get_json()["reply"], "Legacy")
        core.assert_not_called()

    def test_flag_off_legacy_error_audit_and_history_preserved(self):
        self.setUpFlag("false", "7")
        with patch.object(self.ai, "simulate_customer_reply", return_value=(None, "legacy-error")), \
                patch.object(service, "process_message") as core:
            response = self.post()
        core.assert_not_called()
        self.assertEqual(response.get_json(), {"reply": FAILURE_REPLY, "message_id": 2})
        self.assertEqual(self.db.query_one("SELECT detail FROM audit_log")["detail"], "legacy-error")
        self.assertEqual([r["role"] for r in self.rows()], ["user", "assistant"])

    def test_concurrent_quota_last_slot_uses_existing_atomic_reservation(self):
        for n in range(29):
            self.repo.save_simulation_message(7, "other", "user", str(n))
        barrier = Barrier(2)
        def reserve(number):
            try:
                barrier.wait(timeout=5)
                return self.repo.reserve_simulation_user_message(7, str(number), "hello")
            finally:
                self.db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(self.rows()), 30)


if __name__ == "__main__":
    unittest.main()
