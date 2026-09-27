"""Model excerpts cannot strip negation from customer-authorized Job transitions."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assist_reply


class ActionEvidenceTests(unittest.TestCase):
    def infer(self, text, evidence, status, intent):
        value = dict(reply='Saya bantu periksa.', intent=intent, confidence=.95,
                     knowledge_used=[], evidence=evidence,
                     insight=dict(action='Tindak lanjuti permintaan', job_status=status))
        with patch.object(assist_reply, 'relevant_knowledge', return_value={}), \
                patch.object(assist_reply.ai_router, 'complete',
                             return_value=(json.dumps(value), 'end_turn', None)):
            return assist_reply.generate(123, text, [])[1]

    def test_payment_excerpt_cannot_remove_negation_or_condition(self):
        for text, evidence in (
            ('Saya belum mau bayar', 'mau bayar'),
            ('Jangan kirim invoice dulu', 'kirim invoice'),
            ('Kalau saya mau bayar, bagaimana caranya?', 'mau bayar'),
            ('Apakah bisa minta rekening?', 'minta rekening'),
        ):
            with self.subTest(text=text):
                result = self.infer(text, evidence, 'DIKERJAKAN', 'PAYMENT')
                self.assertNotEqual(result['job_status'], 'DIKERJAKAN')
                self.assertEqual(result['_payment_evidence'], '')

    def test_payment_evidence_must_match_its_own_clause(self):
        result = self.infer('Jangan kirim invoice. Saya mau bayar nanti.',
                            'kirim invoice', 'DIKERJAKAN', 'PAYMENT')
        self.assertNotEqual(result['job_status'], 'DIKERJAKAN')
        self.assertEqual(result['_payment_evidence'], '')

    def test_explicit_payment_request_keeps_status(self):
        for text, evidence in (
            ('Kirim invoice, saya mau bayar', 'Kirim invoice, saya mau bayar'),
            ('Belum pesan paket lain, tapi saya mau bayar paket ini', 'saya mau bayar paket ini'),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.infer(text, evidence, 'DIKERJAKAN', 'PAYMENT')['job_status'], 'DIKERJAKAN')

    def test_cancel_excerpt_cannot_remove_negation_or_condition(self):
        for text, evidence in (
            ('Jangan batal dulu', 'batal'),
            ('Saya tidak jadi batal', 'batal'),
            ('Apakah bisa batal?', 'batal'),
            ('Kalau batal nanti bagaimana?', 'batal'),
        ):
            with self.subTest(text=text):
                self.assertIsNone(self.infer(text, evidence, 'BATAL', 'CANCEL')['job_status'])

    def test_explicit_cancellation_keeps_status(self):
        for text in ('Saya batal lanjut', 'Saya tidak jadi', 'Saya nggak jadi pesan'):
            with self.subTest(text=text):
                self.assertEqual(self.infer(text, text, 'BATAL', 'CANCEL')['job_status'], 'BATAL')


if __name__ == '__main__':
    unittest.main()
