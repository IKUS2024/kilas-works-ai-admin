import unittest
import test_finance_phase2a as fixture
from public_chat import schema
from kilas_core import customer_schema, job_schema, finance_bridge_schema, whatsapp_schema
import kilas_finance_bridge_cases

class BridgeTests(kilas_finance_bridge_cases.BridgeCases,unittest.TestCase):
    def setUp(self):
        fixture.ReceivablesTests.setUp(self)
        schema.apply_schema();customer_schema.apply_schema();job_schema.apply_schema()
        finance_bridge_schema.apply_schema();finance_bridge_schema.apply_schema();whatsapp_schema.apply_schema()
        self.seed_bridge()

if __name__=='__main__':unittest.main()
