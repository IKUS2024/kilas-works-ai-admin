"""Pure Phase 5 contracts/state tests; never imports a live app/database."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent / 'client-hub'))
from kilas_core import understanding as u
from kilas_core.playbook_definitions import PLAYBOOKS, select


def interpretation(fields=None, text='pesan', intent='REQUEST', corrections=(), ambiguous=()):
    fields = fields or {}
    return u.parse(json.dumps(dict(intent=intent, fields=fields, evidence={k: text for k in fields},
                                  corrections=list(corrections), ambiguous=list(ambiguous))), text)


class ContractTests(unittest.TestCase):
    def test_category_mapping_fallback(self):
        for category, code in [('Logistik', 'LOGISTICS'), ('Restaurant', 'SIMPLE_ORDER'), ('Salon', 'BOOKING_SERVICE'),
                               ('Videografi agency', 'AGENCY_PROJECT'), ('Bengkel', 'GENERIC_SERVICE'), ('Unknown', 'GENERIC_SERVICE')]:
            self.assertEqual(select(category).code, code)
        self.assertEqual(len(PLAYBOOKS), 5)

    def test_typo_message_bounded_facts(self):
        text = 'mau krim 20 kg bju dr Guangzhou ke Tangerang'
        result = interpretation({'item': 'baju', 'weight': '20 kg', 'origin': 'Guangzhou', 'destination': 'Tangerang'}, text)
        self.assertEqual(result.fields['item'], 'baju')
        with self.assertRaises(TypeError):
            result.fields['item'] = 'changed'

    def test_invalid_model_output(self):
        base = dict(intent='REQUEST', fields={}, evidence={}, corrections=[], ambiguous=[])
        invalid = ['bad', '[]', 'null', '{"intent":"REQUEST","intent":"HUMAN"}', 'x' * 12001]
        for key, value in [('actions', ['CREATE_JOB']), ('job_id', 'foreign'), ('status', 'APPROVED'), ('sql', 'INSERT'), ('payment', True)]:
            invalid.append(json.dumps(dict(base, **{key: value})))
        for field in ('price', 'stock', 'balance', 'payment_status', 'send_whatsapp', 'job_id'):
            invalid.append(json.dumps(dict(base, fields={field: 'value'}, evidence={field: 'pesan'})))
        invalid += [json.dumps(dict(base, intent='CREATE_JOB')), json.dumps(dict(base, fields={'quantity': True}, evidence={'quantity': 'pesan'})),
                    json.dumps(dict(base, fields={'quantity': float('nan')}, evidence={'quantity': 'pesan'})),
                    json.dumps(dict(base, fields={'item': 'baju'}, evidence={'item': 'not stated'}))]
        for raw in invalid:
            with self.subTest(raw=raw[:100]), self.assertRaises(u.UnderstandingError):
                u.parse(raw, 'pesan')

    def test_no_facts_in_unsupported_intents(self):
        for intent in ('UNRELATED', 'HUMAN', 'BUSINESS_QUESTION', 'UNSUPPORTED'):
            self.assertEqual(interpretation(intent=intent).intent, intent)
            with self.assertRaises(u.UnderstandingError):
                interpretation({'item': 'baju'}, intent=intent)

    def test_correction_and_ambiguity_validation(self):
        self.assertEqual(interpretation({'origin': 'Jakarta'}, corrections=['origin']).corrections, {'origin'})
        for kwargs in ({'corrections': ['origin']}, {'ambiguous': ['sql']}, {'ambiguous': ['origin', 'origin']}):
            with self.assertRaises(u.UnderstandingError):
                interpretation(**kwargs)


if __name__ == '__main__':
    unittest.main()
