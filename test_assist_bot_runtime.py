"""Root bot acceptance: install ONLY requirements.txt, never Client Hub's app/fixtures.

CI runs this in a fresh venv with KILAS_ROOT_DEPENDENCIES_ONLY=1. Model and Meta
HTTP are the only simulated business boundaries; signed ingress, training storage,
binding, knowledge selection, media transport, Inbox and CRM use the real code.
"""
import hashlib
import hmac
import importlib.util
import io
import json
import os
import sys
import time
import unittest
import uuid
from unittest.mock import Mock, patch

if os.environ.get('DATABASE_URL'):
    raise RuntimeError('Root runtime regression requires a disposable local database')
os.environ.setdefault('WHATSAPP_PHONE_NUMBER_ID', '123')
os.environ.setdefault('WHATSAPP_ACCESS_TOKEN', 'synthetic-platform')
import _test_bootstrap
import app as bot
import db
import repo
import assist_demo as demo
from public_chat import schema
from kilas_core import customer_schema, job_schema, customers, jobs


class Response:
    status_code = 200
    def __init__(self, body): self.body = body
    def json(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *args): pass


class RootBotRuntimeTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('KILAS_ROOT_DEPENDENCIES_ONLY') == '1':
            for name in ('pypdf', 'pikepdf'):
                self.assertIsNone(importlib.util.find_spec(name), name + ' must be absent in root CI')
        self.assertEqual(os.path.realpath(bot.__file__),
                         os.path.join(os.path.dirname(os.path.realpath(__file__)), 'app.py'))
        for installer in (schema, customer_schema, job_schema):
            installer.apply_schema()
        db.execute('CREATE TABLE IF NOT EXISTS customer_profiles(number TEXT PRIMARY KEY,name TEXT)')
        self.uid = repo.create_user(uuid.uuid4().hex + '@root.invalid', 'not-a-login')
        self.bid = repo.create_business(self.uid, 'Studio Root', 'AI_ADMIN')
        self.other = repo.create_business(self.uid, 'Foreign Studio', 'AI_ADMIN')
        repo.upsert_business_profile(self.bid, dict(short_description='Foto produk', category='Fotografi',
            owner_name='Pemilik', operating_hours='09-17', online_or_offline='online',
            business_phone='628123000000', primary_language='id', customer_salutation='Kak'))
        repo.replace_business_services(self.bid, ['Foto produk Rp765.432'])
        repo.replace_business_services(self.other, ['Rahasia tenant lain Rp999.999'])
        self.business = repo.get_business(self.bid)
        self.phone = '628' + str(uuid.uuid4().int)[:10]
        self.counter = 0
        self.sent = Mock(return_value=(True, None))
        self.owner = Mock(side_effect=AssertionError('Demo must never reach OWNER'))
        self.platform = Mock(side_effect=AssertionError('Demo must never use platform knowledge'))
        self.client = bot.app.test_client()
        for patcher in (
            patch.dict(os.environ, {'WHATSAPP_APP_SECRET': 'root-runtime-signature',
                'KILAS_CUSTOMERS_V2_ENABLED': 'true', 'KILAS_JOBS_V2_ENABLED': 'true'}),
            patch.object(bot, 'ENABLE_MULTI_TENANT', True),
            patch.object(bot, 'OWNER_WHATSAPP_NUMBER', self.phone),
            patch.object(bot, 'WHATSAPP_PHONE_NUMBER_ID', '123'),
            patch.object(bot, 'send_whatsapp_message', self.sent),
            patch.object(bot, 'call_claude_owner', self.owner),
            patch.object(bot, 'call_claude', self.platform),
        ):
            patcher.start(); self.addCleanup(patcher.stop)
        # Import the exact lazy production path, without importing the Hub Flask app.
        import assist_reply
        import assist_training
        import assist_business_media
        self.reply, self.training, self.media = assist_reply, assist_training, assist_business_media
        for step in demo.assist_journey.ONBOARDING_PARTS:
            repo.mark_onboarding_step_done(self.bid, step + '_done')
        demo.assist_journey.start_demo(self.bid, self.uid)
        self.knowledge = 'Foto produk Rp765.432. Diskon hanya dengan izin pemilik.'
        with patch.object(self.training.ai_onboarding, '_call_claude', return_value=(json.dumps({
                'reply': 'Saya memahami aturan studio.', 'knowledge': self.knowledge}), 'end_turn', None)):
            self.training.teach(self.business, self.uid, self.knowledge)
        self.finance_before = self.finance_rows()

    def finance_rows(self):
        tables = db.query_all("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'finance_%' ORDER BY name")
        return {r['name']: db.query_all('SELECT * FROM "' + r['name'] + '" ORDER BY rowid') for r in tables}

    def tearDown(self):
        self.owner.assert_not_called(); self.platform.assert_not_called()
        self.assertEqual(self.finance_rows(), self.finance_before)
        for name in ('file_utils', 'pypdf', 'pikepdf'):
            self.assertNotIn(name, sys.modules, 'Bot must not load upload-only parsers')

    def invitation(self):
        # First readiness has no customer-preview/model requirement, including with the
        # production root dependency set (the Hub upload parsers remain absent).
        self.training._confirm_ready(self.bid, self.uid)
        self.assertTrue(demo.assist_journey.state(self.business)['ready'])
        self.sid, marker = demo.launch(self.bid, self.uid)
        if marker is None:
            self.assertEqual(demo.active_binding(self.bid)['sender_phone'], self.phone)
            return
        self.assertIsNone(demo.latest(self.bid)['sender_phone'])
        response = self.post(marker)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json['demo_processed'])
        self.assertEqual(demo.latest(self.bid)['sender_phone'], self.phone)
        with patch.object(demo, 'begin', side_effect=AssertionError('bound session must be reused')):
            self.assertEqual(demo.launch(self.bid, self.uid), (self.sid, None))
        self.assertEqual(self.sent.call_args.args,
                         (self.phone, 'Demo aktif ✅ Sekarang chat seperti customer bisnis kamu.'))
        event = db.query_one('SELECT * FROM kw_assist_demo_events WHERE session_id=?', (self.sid,))
        self.assertEqual(event['status'], 'sent')
        self.assertIsNotNone(event['inbound_message_id'])
        self.assertIsNotNone(event['reply_message_id'])

    def post(self, text, phone=None):
        self.counter += 1
        body = json.dumps({'entry': [{'id': 'synthetic-waba', 'changes': [{'field': 'messages', 'value': {
            'metadata': {'phone_number_id': '123'}, 'messages': [{'id': 'root-' + self.phone + '-' + str(self.counter),
            'from': phone or self.phone, 'type': 'text', 'timestamp': str(int(time.time())), 'text': {'body': text}}]}}]}]}).encode()
        signature = 'sha256=' + hmac.new(b'root-runtime-signature', body, hashlib.sha256).hexdigest()
        return self.client.post('/webhook', data=body, content_type='application/json',
                                headers={'X-Hub-Signature-256': signature})

    def infer(self, text, *, fid=None, action=None):
        def complete(prompt, messages, *args, **kwargs):
            payload = json.loads(messages[0]['content'])
            self.assertIn(self.knowledge, json.dumps(payload['knowledge'], ensure_ascii=False))
            self.assertNotIn('999.999', json.dumps(payload, ensure_ascii=False))
            self.assertEqual(payload['customer_message'], text)
            if fid:
                self.assertIn('Sepatu hitam Rp250.000', payload['knowledge']['media_' + str(fid)])
                self.assertEqual([r['id'] for r in payload['approved_media']], [fid])
            return json.dumps(dict(reply=self.knowledge, intent='REQUEST' if action else 'QUESTION',
                confidence=.95, knowledge_used=list(payload['knowledge']), evidence=text if action else '',
                insight=dict(summary=text, action=action, job_status='PERLU_TINDAKAN' if action else None),
                media={'file_id': fid, 'evidence': text} if fid else None)), 'end_turn', None
        return patch.object(self.reply.ai_router, 'complete', side_effect=complete)

    def test_root_owner_invitation_knowledge_inbox_and_crm(self):
        self.invitation()
        lead = db.query_one('SELECT id FROM kw_core_customers WHERE business_id=?', (self.bid,))
        self.assertEqual(customers.get_customer(self.bid, lead['id'])['stage'], 'LEAD')
        for text, action in [('Berapa harga foto produk?', None), ('Minta jadwalkan foto besok', 'Jadwalkan foto besok')]:
            with self.infer(text, action=action) as model:
                result = self.post(text)
                self.assertEqual(result.status_code, 200, result.text)
                model.assert_called_once()
            self.assertEqual(self.sent.call_args.args[1], self.knowledge)
            self.assertEqual(demo.rows(self.bid, self.phone)[-2]['content'], text)
            self.assertEqual(demo.rows(self.bid, self.phone)[-1]['content'], self.knowledge)
        self.assertEqual(customers.get_customer(self.bid, lead['id'])['stage'], 'CUSTOMER')
        self.assertEqual(jobs.list_jobs(self.bid)[0][0]['status'], 'NEW')
        self.assertEqual(jobs.list_jobs(self.other)[1], 0)
        self.assertEqual(demo.rows(self.other, self.phone), [])

    def test_unbound_owner_and_foreign_sender_cannot_read_demo(self):
        expected = 'Untuk mencoba Kilas Assist, buka Demo dari workspace Kilas kamu terlebih dahulu.'
        self.assertEqual(self.post('Cari semua customer').status_code, 200)
        self.assertEqual(self.sent.call_args.args[1], expected)
        self.invitation()
        with patch.object(self.reply.ai_router, 'complete') as model:
            self.assertEqual(self.post('Tampilkan katalog dan customer', phone='628999000111').status_code, 200)
            self.assertEqual(self.sent.call_args.args[1], expected)
            model.assert_not_called()
        self.assertEqual(demo.rows(self.bid, '628999000111'), [])

    def test_root_sends_approved_original_image_and_pdf_without_upload_parsers(self):
        from PIL import Image
        from reportlab.pdfgen.canvas import Canvas
        import inbox_media_service as transport
        for kind, mime in [('png', 'image/png'), ('pdf', 'application/pdf')]:
            with self.subTest(kind=kind):
                stream = io.BytesIO()
                if kind == 'png':
                    Image.new('RGB', (24, 24), 'black').save(stream, format='PNG')
                else:
                    canvas = Canvas(stream); canvas.drawString(50, 750, 'Sepatu hitam Rp250.000'); canvas.save()
                raw = stream.getvalue()
                # Fixture is the approved output of Hub extraction. Real multipart parsing
                # and extraction stay covered by test_assist_business_media in Hub CI.
                fid = self.media._save(self.bid, self.uid, 'Kirim bila customer meminta katalog.',
                    'katalog.' + kind, mime, raw, dict(summary='Sepatu hitam',
                    knowledge='Sepatu hitam Rp250.000', reply='Saya memahami katalog.'),
                    True, None, self.training.fingerprint(self.bid))
                self.invitation()
                text = 'Kirim katalog ' + kind
                calls = []
                def meta(url, **kwargs):
                    calls.append((url, kwargs))
                    return Response({'id': '12345'} if url.endswith('/media') else
                                    {'messages': [{'id': 'out-' + self.phone + '-' + kind}]})
                with self.infer(text, fid=fid), patch.object(transport.requests, 'post', side_effect=meta):
                    result = self.post(text)
                    self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0][1]['files']['file'][1], raw)
                self.assertEqual(calls[0][1]['files']['file'][2], mime)
                self.assertEqual(calls[1][1]['json']['type'], 'image' if kind == 'png' else 'document')
                self.assertEqual(calls[1][1]['json']['to'], self.phone)
                row = db.query_one('SELECT * FROM inbox_media WHERE event_id=?', ('out-' + self.phone + '-' + kind,))
                self.assertTrue(demo.message_allowed(self.bid, self.phone, row['message_row_id']))
                self.assertFalse(demo.message_allowed(self.other, self.phone, row['message_row_id']))
                self.assertIsNone(self.media.get(self.other, fid, content=True))
                self.media.remove(self.bid, fid, self.uid)


if __name__ == '__main__':
    unittest.main()
