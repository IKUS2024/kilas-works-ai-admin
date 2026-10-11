"""Publication integrity and offline runner barriers; no external operations."""
import builtins
import hashlib
import json
from pathlib import Path
import unittest

from run_offline_tests import forbidden, guarded_import

ROOT = Path(__file__).resolve().parent


class PublicationTests(unittest.TestCase):
    def test_complete_manifest_inventory_and_hashes(self):
        manifest = json.loads((ROOT / 'publication-manifest.json').read_text())
        prefix = 'client-hub/tools/kilas_trading_windows/'
        inventory = {prefix + str(p.relative_to(ROOT)).replace('\\', '/')
                     for p in ROOT.rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc'
                     and p.name != 'publication-manifest.json'}
        self.assertEqual(inventory, {entry['path'] for entry in manifest['files']})
        self.assertEqual(len(inventory), len(manifest['files']))
        for entry in manifest['files']:
            content = (ROOT / entry['path'].removeprefix(prefix)).read_bytes()
            self.assertEqual(entry['bytes'], len(content), entry['path'])
            self.assertEqual(entry['lines'], len(content.splitlines()), entry['path'])
            self.assertEqual(entry['sha256'], hashlib.sha256(content).hexdigest(), entry['path'])

    def test_pinned_contract_matches_current_server_when_in_repository(self):
        server = ROOT.parents[1] / 'kilas_trading'
        if not server.is_dir():
            self.skipTest('Standalone Windows bundle: cloud CI checks current server parity')
        pinned = ROOT / 'cloud-contract-db035'
        for entry in json.loads((pinned / 'manifest.json').read_text())['files']:
            self.assertEqual((pinned / 'kilas_trading' / entry['name']).read_bytes(),
                             (server / entry['name']).read_bytes(), entry['name'])

    def test_private_terminal_pin_and_policy_remain_unset(self):
        from mt5_demo_session import DATA
        from mt5_demo_adapter import DemoTestPolicy
        from demo_auto_controller import Blocked
        self.assertEqual(DATA, 'REVIEW_REQUIRED_LOCAL_DEMO_DATA_PATH')
        policy = json.loads((ROOT / 'demo_test_policy.unset.json').read_text())
        self.assertTrue(all(v is None for k, v in policy.items() if k != 'schema_version'))
        with self.assertRaisesRegex(Blocked, 'POLICY_UNSET'):
            DemoTestPolicy.parse(policy)

    def test_offline_barriers_reject_native_and_external_operations(self):
        importing = guarded_import(builtins.__import__)
        for name in ('MetaTrader5', 'MetaTrader5.native'):
            with self.assertRaisesRegex(RuntimeError, 'OFFLINE_NATIVE_SDK_IMPORT_BLOCKED'):
                importing(name)
        with self.assertRaisesRegex(RuntimeError, 'OFFLINE_EXTERNAL_OPERATION_BLOCKED'):
            forbidden()


if __name__ == '__main__':
    unittest.main()
