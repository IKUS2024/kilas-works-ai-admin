"""Disposable PostgreSQL Bridge runtime and concurrency; no real DB allowed."""
import finance_workspace_postgres_qa as gate
import unittest
from public_chat import schema
from kilas_core import customer_schema,job_schema,finance_bridge_schema
from kilas_finance_bridge_cases import BridgeCases

class BridgePostgresTests(BridgeCases,unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gate.db.init_schema()
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema()
        finance_bridge_schema.apply_schema();finance_bridge_schema.apply_schema()
    def setUp(self):self.seed_bridge()

if __name__=='__main__':unittest.main(verbosity=2)
