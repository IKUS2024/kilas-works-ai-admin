"""The production composition root is inert without explicit future setup."""
import tempfile
import unittest
from pathlib import Path

from btc_integration_client import build_btc_worker
from mt5_demo_adapter import Journal, MT5DemoAdapter
from test_mt5_demo_adapter import FakeSDK


class AssemblyTests(unittest.TestCase):
    def test_default_assembly_has_no_credentials_activation_or_sdk_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = FakeSDK()
            def forbidden():
                raise AssertionError('Assembly must not read/attach SDK')
            sdk.account_info = forbidden
            adapter = MT5DemoAdapter(sdk, Journal(root/'broker.sqlite'))
            worker = build_btc_worker(adapter, control_ledger=root/'control.sqlite',
                                      decision_ledger=root/'decisions.sqlite')
            client = worker.integration
            self.assertFalse(client.activation_enabled)
            self.assertFalse(client.authority_valid())
            self.assertFalse(client.readiness()['ready'])
            self.assertIsNone(client.transport.endpoint)
            self.assertIsNone(client.transport.provider)
            self.assertFalse(client.transport.authorized)
            self.assertFalse(adapter.execute)
            self.assertEqual(worker.threads, [])
            self.assertEqual(worker.coordination.threads, [])
            self.assertEqual((sdk.checks, sdk.sends), ([], []))

    def test_no_scope_or_evidence_cannot_schedule_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sdk = FakeSDK()
            adapter = MT5DemoAdapter(sdk, Journal(root/'broker.sqlite'))
            worker = build_btc_worker(adapter, control_ledger=root/'control.sqlite',
                                      decision_ledger=root/'decisions.sqlite')
            self.assertIsNone(worker.integration.analyze_once())
            self.assertEqual(worker.integration.status()['runtime_model'], 'gpt-6.1-sol')
            self.assertEqual(worker.integration.status()['reasoning'], 'medium')
            self.assertEqual((sdk.checks, sdk.sends), ([], []))


if __name__ == '__main__':
    unittest.main()
