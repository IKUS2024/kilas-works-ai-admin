import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'client-hub'))
from kilas_core.operation_contracts import config, DEFAULT_CONFIG, OperationError, REASONS, MESSAGES


class ContractTests(unittest.TestCase):
    def test_closed_config_and_bounds(self):
        self.assertEqual(config(DEFAULT_CONFIG), DEFAULT_CONFIG)
        for change in ({'url':'https://example.com'}, {'action':'SEND_WHATSAPP'}, {'delay_hours':0},
                       {'delay_hours':169}, {'delay_hours':True}, {'max_attempts':4}, {'max_attempts':0},
                       {'followup_enabled':1}, {'review_enabled':'true'}):
            with self.subTest(change=change), self.assertRaises(OperationError):
                config({**DEFAULT_CONFIG,**change})
        with self.assertRaises(OperationError): config({})

    def test_small_deterministic_vocabulary(self):
        self.assertEqual(len(REASONS),6)
        self.assertEqual(set(MESSAGES),{'CUSTOMER_INACTIVE_FOLLOWUP','JOB_COMPLETED_REVIEW_REQUEST'})
        self.assertTrue(all(len(text)<300 for text in MESSAGES.values()))


if __name__=='__main__': unittest.main()
