"""Offline simulator coverage. No migration runner, production DB, or live model calls."""
import ast
import sys
import unittest
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
        # Fail if Core gains a live module dependency or direct IO/dynamic-import capability.
        allowed_imports = {"dataclasses", "datetime", "os", "re", "collections.abc",
                           "contracts", "service"}
        for path in (HUB / "kilas_core").rglob("*.py"):
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


if __name__ == "__main__":
    unittest.main()
