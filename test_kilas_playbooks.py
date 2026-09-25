"""Pure Phase 5 contracts/state tests; never imports a live app/database."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent / 'client-hub'))
from kilas_core import understanding as u
from kilas_core import playbooks as engine
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

    def test_physical_measurements_are_positive_complete_and_bounded(self):
        for field, value in [('weight','-20 kg'),('weight','gratis'),('weight','0 kg'),('volume_cbm','0'),
                             ('volume_cbm','1e99'),('dimensions','50 x 20'),('dimensions','0x20x30 cm')]:
            with self.subTest(field=field,value=value), self.assertRaises(u.UnderstandingError):
                interpretation({field:value})
        for field, value in [('weight','20 kilogram'),('volume_cbm','0,2 m3'),('dimensions','50 × 40 × 30 cm')]:
            self.assertEqual(interpretation({field:value}).fields[field],value)

    def test_correction_and_ambiguity_validation(self):
        self.assertEqual(interpretation({'origin': 'Jakarta'}, corrections=['origin']).corrections, {'origin'})
        for kwargs in ({'corrections': ['origin']}, {'ambiguous': ['sql']}, {'ambiguous': ['origin', 'origin']}):
            with self.assertRaises(u.UnderstandingError):
                interpretation(**kwargs)


class StateTests(unittest.TestCase):
    def test_logistics_known_missing_followup(self):
        book = PLAYBOOKS['LOGISTICS']
        facts = {'item': 'baju', 'weight': '20 kg', 'origin': 'Guangzhou', 'destination': 'Tangerang'}
        first = engine.decide(book, interpretation(facts))
        self.assertEqual(first.missing, ('volume_cbm|dimensions',))
        self.assertEqual(first.target_status, 'NEEDS_INFORMATION')
        reply = engine.response(first, committed=True)
        for known in ('berat', 'asal', 'tujuan', 'jenis barang'):
            self.assertNotIn(known, reply)
        second = engine.decide(book, interpretation({'volume_cbm': '0.2 m³'}), known=first.fields,
                               current_status=first.target_status, has_job=True)
        self.assertEqual(second.fields['origin'], 'Guangzhou')
        self.assertEqual(second.missing, ())
        self.assertEqual(second.target_status, 'READY_FOR_QUOTE')

    def test_correction_conflict_and_durable_uncertainty(self):
        book = PLAYBOOKS['LOGISTICS']
        known = {'origin': 'Guangzhou'}
        conflict = engine.decide(book, interpretation({'origin': 'Shanghai'}), known=known, has_job=True, current_status='NEW')
        self.assertEqual(conflict.fields['origin'], 'Guangzhou')
        self.assertEqual(conflict.uncertain, ('origin',))
        later = engine.decide(book, interpretation({'item': 'baju'}), known=conflict.fields, uncertain=conflict.uncertain,
                              has_job=True, current_status='NEEDS_INFORMATION')
        self.assertEqual(later.uncertain, ('origin',))
        corrected = engine.decide(book, interpretation({'origin': 'Shanghai'}, corrections=['origin']), known=later.fields,
                                  uncertain=later.uncertain, has_job=True, current_status='NEEDS_INFORMATION')
        self.assertEqual(corrected.fields['origin'], 'Shanghai')
        self.assertEqual(corrected.uncertain, ())

    def test_ambiguous_value_not_stored(self):
        result = engine.decide(PLAYBOOKS['LOGISTICS'], interpretation({'weight': '20 kg'}, ambiguous=['weight']))
        self.assertNotIn('weight', result.fields)
        self.assertIn('weight', result.missing)
        self.assertFalse(result.write)
        self.assertIn('pastikan berat', engine.response(result))

    def test_all_playbooks(self):
        examples = {
            'GENERIC_SERVICE': {'service': 'perbaikan AC', 'need': 'tidak dingin'},
            'LOGISTICS': {'item': 'baju', 'weight': '20 kg', 'dimensions': '50x40x30 cm', 'origin': 'Guangzhou', 'destination': 'Tangerang'},
            'SIMPLE_ORDER': {'items': 'nasi goreng', 'quantity': 2, 'fulfillment': 'pickup'},
            'BOOKING_SERVICE': {'service': 'potong rambut', 'preferred_date': 'besok', 'preferred_time': '14.00'},
            'AGENCY_PROJECT': {'requested_service': 'video perusahaan', 'brief': 'profil usaha'},
        }
        for code, fields in examples.items():
            with self.subTest(code=code):
                decision = engine.decide(PLAYBOOKS[code], interpretation(fields))
                self.assertEqual(decision.missing, ())
                self.assertEqual(decision.target_status, 'READY_FOR_QUOTE')
                self.assertTrue(decision.write)
                self.assertNotIn('tercatat', engine.response(decision))
                self.assertIn('tercatat', engine.response(decision, committed=True))
        dine_in = engine.decide(PLAYBOOKS['SIMPLE_ORDER'], interpretation(dict(examples['SIMPLE_ORDER'], fulfillment='dine_in')))
        self.assertEqual(dine_in.missing, ())
        delivery = engine.decide(PLAYBOOKS['SIMPLE_ORDER'], interpretation(dict(examples['SIMPLE_ORDER'], fulfillment='delivery')))
        self.assertEqual(delivery.missing, ('location',))
        window = engine.decide(PLAYBOOKS['BOOKING_SERVICE'], interpretation({'service': 'salon', 'preferred_date': 'besok', 'time_window': 'sore'}))
        self.assertEqual(window.missing, ())

    def test_no_lifecycle_bypass_or_separate_request_split(self):
        for status in ('QUOTED', 'APPROVED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'):
            d = engine.decide(PLAYBOOKS['GENERIC_SERVICE'], interpretation({'service': 'AC'}), has_job=True, current_status=status)
            self.assertFalse(d.write)
            self.assertEqual(d.reason, 'needs_owner')
        d = engine.decide(PLAYBOOKS['GENERIC_SERVICE'], interpretation({'service': 'AC'}, intent='NEW_REQUEST'), has_job=True, current_status='NEW')
        self.assertFalse(d.write)
        d = engine.decide(PLAYBOOKS['GENERIC_SERVICE'], interpretation({'need': 'lain'}, ambiguous=['need']),
                          known={'service': 'AC', 'need': 'rusak'}, has_job=True, current_status='READY_FOR_QUOTE')
        self.assertEqual(d.target_status, 'READY_FOR_QUOTE')
        self.assertIn('pastikan', engine.response(d))

    def test_unrelated_and_wrong_workflow(self):
        d = engine.decide(PLAYBOOKS['LOGISTICS'], interpretation(intent='UNRELATED'))
        self.assertFalse(d.write)
        self.assertIn('bisnis ini', engine.response(d))
        with self.assertRaises(u.UnderstandingError):
            engine.decide(PLAYBOOKS['LOGISTICS'], interpretation({'preferred_time': '14.00'}))


if __name__ == '__main__':
    unittest.main()
