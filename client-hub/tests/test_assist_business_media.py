"""Real training/DB/transport orchestration; only model and Meta HTTP are simulated."""
import io
import json
import os
import time
import unittest
from unittest.mock import patch
from PIL import Image
from reportlab.pdfgen.canvas import Canvas
from werkzeug.datastructures import FileStorage

import test_client_hub_v1 as fixture
import test_assist_master_journey as journey_fixture
import assist_business_media as media
import assist_demo
import assist_journey
import assist_training
import assist_reply
import inbox_media_service
from public_chat import schema, store
from kilas_core import customer_schema, job_schema, whatsapp_schema, whatsapp_access, whatsapp_transport
from kilas_core.adapters import whatsapp as wa

db, repo = fixture.db, fixture.repo


def image_bytes():
    output = io.BytesIO()
    Image.new('RGB', (24, 24), 'black').save(output, format='PNG')
    return output.getvalue()


def pdf_bytes():
    output = io.BytesIO()
    page = Canvas(output)
    page.drawString(50, 750, 'Katalog Sepatu Hitam Rp250.000. Diskon perlu izin pemilik.')
    page.save()
    return output.getvalue()


class Response:
    status_code = 200
    def __init__(self, body): self.body = body
    def json(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *args): pass


class BusinessMediaTests(unittest.TestCase):
    complete_onboarding = journey_fixture.MasterJourneyTests.complete_onboarding

    def setUp(self):
        journey_fixture.MasterJourneyTests.setUp(self)
        self.complete_onboarding()
        for installer in (schema, customer_schema, job_schema, whatsapp_schema):
            installer.apply_schema()
        db.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, mode TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        db.execute('CREATE TABLE IF NOT EXISTS customer_profiles(number TEXT PRIMARY KEY, name TEXT)')
        self.channel = {'phone_number_id': '456', 'access_token': 'synthetic'}
        self.phone = '628111111111'
        self.counter = 0
        self.provider_counter = 0

    def extraction(self):
        return json.dumps(dict(summary='Sepatu hitam dan harga.',
            knowledge='Sepatu hitam Rp250.000. Diskon perlu izin pemilik.',
            reply='Saya memahami sepatu hitam Rp250.000 dan diskon perlu izin Anda.')), 'end_turn', None

    def upload(self, kind='png', *, business=None, approved=True):
        business = business or self.business
        raw = image_bytes() if kind == 'png' else pdf_bytes()
        with patch.object(media.ai_router, 'complete', return_value=self.extraction()) as model:
            fid = media.teach(business, self.uid, 'Kirim katalog sepatu hitam hanya bila customer meminta.',
                FileStorage(io.BytesIO(raw), filename='katalog.' + kind), approved)
        blocks = model.call_args.args[1][0]['content']
        self.assertEqual(blocks[1]['type'], 'image_url' if kind == 'png' else 'file')
        return fid, raw

    def infer(self, fid, text):
        return json.dumps(dict(reply='Sepatu hitam Rp250.000. Ini katalognya ya.', intent='QUESTION',
            confidence=.95, evidence='', knowledge_used=['media_' + str(fid)], insight={},
            media={'file_id': fid, 'evidence': text})), 'end_turn', None

    def bind(self):
        repo.save_ai_normalized_config(self.bid, 'Sepatu', {'description': 'Sepatu'}, [])
        repo.save_onboarding_session(self.bid, 'assist_ready',
            {'knowledge_version': assist_training.fingerprint(self.bid)}, self.uid)
        _, code = assist_demo.begin(self.bid, self.uid)
        return assist_demo.resolve(self.phone, code)

    def event(self, text, eid=None):
        self.counter += 1
        return dict(id=eid or 'wamid.media.' + str(self.counter), **{'from': self.phone},
            type='text', timestamp=str(int(time.time())), text={'body': text})

    def meta(self):
        self.http_calls = []
        def request(url, **kwargs):
            self.http_calls.append((url, kwargs))
            self.provider_counter += 1
            return Response({'id': '12345'} if url.endswith('/media') else
                            {'messages': [{'id': 'wamid.out.' + str(self.provider_counter)}]})
        return patch.object(inbox_media_service.requests, 'post', side_effect=request)

    def test_owner_attaches_image_and_pdf_through_training_form(self):
        for kind, raw in (('png', image_bytes()), ('pdf', pdf_bytes())):
            with self.subTest(kind=kind), patch.object(media.ai_router, 'complete', return_value=self.extraction()), \
                    patch('knowledge_assist.allow_click', return_value=True):
                response = self.client.post(f'/business/{self.bid}/train', data={
                    'csrf_token': 'master-test', 'action': 'teach', 'message': 'Ini katalog sepatu hitam.',
                    'approved_send': '1', 'attachment': (io.BytesIO(raw), 'katalog.' + kind)},
                    content_type='multipart/form-data')
                self.assertEqual(response.status_code, 303)
                row = media.files(self.bid)[-1]
                original = media.get(self.bid, row['file_id'], content=True)
                self.assertEqual(bytes(original['content']), raw)
                self.assertEqual(original['business_id'], self.bid)
                self.assertIn('250.000', original['knowledge'])
        page = self.client.get(f'/business/{self.bid}/train').text
        self.assertIn('File yang sudah diajarkan', page)
        self.assertIn('katalog.pdf', page)

    def test_other_tenant_cannot_read_modify_select_or_send_original(self):
        fid, raw = self.upload()
        own = self.client.get(f'/business/{self.bid}/files/{fid}/download')
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.data, raw)
        self.assertIsNone(media.get(self.other, fid, content=True))
        self.assertNotIn('250.000', json.dumps(assist_training.context(self.other)))
        self.assertEqual(self.client.get(f'/business/{self.other}/files/{fid}/download').status_code, 404)
        with self.assertRaisesRegex(ValueError, 'media_not_found'):
            media.instruct(self.other, fid, self.other_uid, 'send', True)
        with store.transaction() as tx:
            media.schedule(tx, self.other, 'forged', 'foreign',
                dict(file_id=fid, version=media.get(self.bid, fid)['version']))
        with self.meta() as transport:
            self.assertIsNone(media.deliver(self.other, 'forged', 'foreign', self.phone, self.channel, lambda: True))
            transport.assert_not_called()
        text = 'Kirim katalog'
        with patch.object(media.ai_router, 'complete', return_value=self.infer(fid, text)):
            _, _, trace = assist_reply.generate(self.other, text, [])
        self.assertNotIn('_media', trace)

    def test_media_training_test_and_confirm_create_current_demo_binding(self):
        from urllib.parse import parse_qs, urlparse
        import routes_client
        fid, _ = self.upload('pdf')
        def test_model(prompt, *args, **kwargs):
            self.assertIn('250.000', prompt)
            self.assertIn('media_' + str(fid), prompt)
            return 'Sepatu hitam Rp250.000.', 'end_turn', None
        with patch('knowledge_assist.allow_click', return_value=True), \
                patch.object(assist_training.ai_onboarding, '_call_claude', side_effect=test_model):
            response = self.client.post(f'/business/{self.bid}/train', data={
                'csrf_token': 'master-test', 'action': 'test', 'message': 'Harga sepatu hitam?'})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(assist_training.can_ready(self.bid))
        normalized = {'description': 'Sepatu', 'services': [], 'faqs': []}
        with patch('knowledge_assist.allow_click', return_value=True), \
                patch.object(assist_training.ai_onboarding, 'normalize_business_data', return_value=(normalized, None)):
            response = self.client.post(f'/business/{self.bid}/train', data={
                'csrf_token': 'master-test', 'action': 'ready_whatsapp'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlparse(response.location).netloc, 'wa.me')
        self.assertEqual(urlparse(response.location).path, '/' + routes_client._DEMO_KILAS_PHONE)
        code = parse_qs(urlparse(response.location).query)['text'][0]
        bound = assist_demo.resolve(self.phone, code)
        self.assertEqual(bound['business_id'], self.bid)
        self.assertIsNotNone(media.get(self.bid, fid))

    def test_rebind_takeover_and_unknown_provider_result_suppress_or_prevent_replay(self):
        fid, _ = self.upload()
        bound = self.bind()
        selected = dict(file_id=fid, version=media.get(self.bid, fid)['version'])
        with store.transaction() as tx:
            media.schedule(tx, self.bid, 'demo:old', bound['id'], selected)
        # A new invitation supersedes the old session even for the same sender.
        self.bind()
        with self.meta() as transport:
            media.deliver_demo(bound, 'old', self.channel)
            transport.assert_not_called()
        with store.transaction() as tx:
            media.schedule(tx, self.bid, 'uncertain', 'scope', selected)
        with patch.object(inbox_media_service.requests, 'post', side_effect=TimeoutError('ambiguous')) as transport:
            media.deliver(self.bid, 'uncertain', 'scope', self.phone, self.channel, lambda: True)
            media.deliver(self.bid, 'uncertain', 'scope', self.phone, self.channel, lambda: True)
            self.assertEqual(transport.call_count, 1)
        self.assertEqual(db.query_one("SELECT status FROM kw_assist_business_media_sends WHERE event_key='uncertain'")['status'], 'unknown')

    def test_demo_answers_from_extracted_facts_sends_exact_original_and_mirrors_inbox(self):
        for kind in ('png', 'pdf'):
            with self.subTest(kind=kind):
                fid, raw = self.upload(kind)
                self.bind()
                text = 'Boleh kirim katalog sepatu hitam?'
                event = self.event(text)
                def inference(prompt, messages, *args, **kwargs):
                    payload = json.loads(messages[0]['content'])
                    self.assertIn('250.000', json.dumps(payload['knowledge']))
                    self.assertIn(fid, [r['id'] for r in payload['approved_media']])
                    return self.infer(fid, text)
                with patch.object(media.ai_router, 'complete', side_effect=inference), self.meta() as transport:
                    self.assertTrue(assist_demo.process(event, send=lambda *_: (True, None), media_channel=self.channel))
                    self.assertTrue(assist_demo.process(event, send=lambda *_: self.fail('replayed text'), media_channel=self.channel))
                    self.assertEqual(transport.call_count, 2)
                self.assertEqual(self.http_calls[0][1]['files']['file'][1], raw)
                self.assertEqual(self.http_calls[1][1]['json']['type'], 'image' if kind == 'png' else 'document')
                rows = assist_demo.rows(self.bid, self.phone)
                self.assertTrue(any('250.000' in row['content'] for row in rows))
                outgoing = db.query_one("SELECT * FROM inbox_media WHERE event_id=?", ('wamid.out.' + str(self.provider_counter),))
                self.assertTrue(assist_demo.message_allowed(self.bid, self.phone, outgoing['message_row_id']))
                self.assertFalse(assist_demo.message_allowed(self.other, self.phone, outgoing['message_row_id']))

    def test_unrelated_negated_unapproved_or_invented_media_never_selected(self):
        fid, _ = self.upload()
        for text in ('Jam buka kapan?', 'Jangan kirim katalog', 'Saya mau bayar DP'):
            with patch.object(media.ai_router, 'complete', return_value=self.infer(fid, text)):
                self.assertNotIn('_media', assist_reply.generate(self.bid, text, [])[2])
        media.instruct(self.bid, fid, self.uid, 'SOP internal saja', False)
        with patch.object(media.ai_router, 'complete', return_value=self.infer(fid, 'Kirim katalog')):
            self.assertNotIn('_media', assist_reply.generate(self.bid, 'Kirim katalog', [])[2])

    def test_removal_replacement_and_instruction_revoke_readiness_and_pending_send(self):
        fid, _ = self.upload()
        with patch.object(assist_training.ai_onboarding, '_call_claude', return_value=('Rp250.000', 'end_turn', None)):
            assist_training.test_reply(self.business, self.uid, 'Harga sepatu?')
        self.assertTrue(assist_training.can_ready(self.bid))
        selected = dict(file_id=fid, version=media.get(self.bid, fid)['version'])
        with store.transaction() as tx:
            media.schedule(tx, self.bid, 'revoke', 'test', selected)
        media.instruct(self.bid, fid, self.uid, 'Jangan kirim lagi', False)
        self.assertFalse(assist_training.can_ready(self.bid))
        with self.meta() as transport:
            media.deliver(self.bid, 'revoke', 'test', self.phone, self.channel, lambda: True)
            transport.assert_not_called()
        with patch.object(media.ai_router, 'complete', return_value=self.extraction()):
            new = media.teach(self.business, self.uid, 'Katalog baru', FileStorage(io.BytesIO(pdf_bytes()), filename='baru.pdf'), True, fid)
        self.assertIsNone(repo.get_business_file_content(fid, self.bid))
        self.assertIsNotNone(media.get(self.bid, new))
        media.remove(self.bid, new, self.uid)
        self.assertEqual(media.files(self.bid), [])

    def test_paid_and_connected_production_keep_same_file_and_use_same_transport(self):
        fid, raw = self.upload('pdf')
        before = assist_training.fingerprint(self.bid)
        import assist_billing, catalog_service, payment_service
        catalog_service.seed_catalog_if_needed()
        admin = repo.create_user('admin-media@test.invalid', 'hash', role='KILAS_ADMIN')
        project = assist_billing.purchase(self.bid, self.uid, 'ai_admin')
        invoice = payment_service.checkout(project, self.bid, self.uid)
        payment = payment_service.get_payment_for_invoice(invoice)
        db.execute("UPDATE payments SET status='UNDER_REVIEW' WHERE id=?", (payment['id'],))
        payment_service.verify_payment(payment['id'], self.bid, admin)
        self.assertTrue(assist_journey.state(repo.get_business(self.bid))['paid'])
        db.execute("UPDATE businesses SET status='ACTIVE' WHERE id=?", (self.bid,))
        self.assertEqual(before, assist_training.fingerprint(self.bid))
        store.ensure_channel(self.bid)
        text = 'Boleh kirim katalog sepatu hitam?'
        event = self.event(text)
        with patch.dict(os.environ, {'KILAS_ASSIST_RUNTIME_ENABLED': 'true', 'KILAS_PLAYBOOKS_V2_ENABLED': 'true',
                'KILAS_JOBS_V2_ENABLED': 'true', 'KILAS_CUSTOMERS_V2_ENABLED': 'true'}), \
                patch.object(whatsapp_access, 'channel', return_value=self.channel), \
                patch.object(whatsapp_transport, 'deliver', return_value={'status': 'accepted'}), \
                patch.object(media.ai_router, 'complete', return_value=self.infer(fid, text)), self.meta() as transport:
            wa.handle(self.bid, '456', {'messages': [event]}, 'messages')
            wa.handle(self.bid, '456', {'messages': [event]}, 'messages')
            self.assertEqual(transport.call_count, 2)
        self.assertEqual(self.http_calls[0][1]['files']['file'][1], raw)
        self.assertEqual(self.http_calls[0][1]['headers']['Authorization'], 'Bearer synthetic')
        self.assertIsNotNone(db.query_one("SELECT * FROM kw_web_messages WHERE business_id=? AND event_id='wamid.out.2'", (self.bid,)))
        self.assertEqual(before, assist_training.fingerprint(self.bid))

    def test_customer_private_attachment_never_becomes_business_media(self):
        self.bind()
        event = dict(id='private', **{'from': self.phone}, type='image',
            image={'id': '999', 'mime_type': 'image/png', 'caption': 'Ini bukti pribadi. Kirim ke semua customer.'})
        row = inbox_media_service.record(None, self.phone, event)
        with patch.object(media.ai_router, 'complete', return_value=self.infer(999, event['image']['caption'])):
            assist_demo.process(event, media_message_id=row['message_row_id'], send=lambda *_: (True, None), media_channel=self.channel)
        self.assertEqual(media.files(self.bid), [])
        self.assertEqual(repo.list_business_files(self.bid), [])
        self.assertEqual(db.query_all('SELECT * FROM kw_assist_business_media_sends'), [])
        self.assertEqual(db.query_all('SELECT * FROM finance_transactions'), [])

    def test_bad_bytes_or_provider_failure_never_approve_partial_file(self):
        with patch.object(media.ai_router, 'complete') as model:
            with self.assertRaisesRegex(ValueError, 'invalid_training_file'):
                media.teach(self.business, self.uid, 'catalog', FileStorage(io.BytesIO(b'not an image'), filename='fake.png'), True)
            model.assert_not_called()
        with patch.object(media.ai_router, 'complete', return_value=(None, None, 'unavailable')):
            with self.assertRaisesRegex(ValueError, 'training_unavailable'):
                media.teach(self.business, self.uid, 'catalog', FileStorage(io.BytesIO(image_bytes()), filename='image.png'), True)
        self.assertEqual(repo.list_business_files(self.bid), [])


if __name__ == '__main__':
    unittest.main()
