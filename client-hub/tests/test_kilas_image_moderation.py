"""Explicit provider safety rejection UX; synthetic transport, no inference."""
import json
import os
import unittest
from unittest.mock import patch
import requests
import db
import test_kilas_managed_offering as fixture
from kilas_ai import agent_store, autonomous_store, autonomous_runner, routing, store
from kilas_ai import selected_image, tools, chat_offering, provider_failures as failures


def rejection(code='content_policy_violation', status=400, field='code'):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({'error': {field: code, 'message': 'PRIVATE_PROVIDER_BODY'}}).encode()
    response.headers['x-request-id'] = 'req_synthetic_safety'
    return response


class ImageModerationTests(unittest.TestCase):
    setUp = fixture.ManagedOfferingTests.setUp
    client = fixture.ManagedOfferingTests.client
    submit = fixture.ManagedOfferingTests.submit

    def test_only_recognized_codes_or_types_are_content_rejections(self):
        for field in ('code', 'type'):
            for code in failures.IMAGE_REJECTION_CODES:
                self.assertTrue(failures.image_content_rejected(rejection(code, field=field)))
        for code, status in [('invalid_value', 400), ('insufficient_quota', 429), ('rate_limit_exceeded', 429),
                             ('content_policy_violation', 200)]:
            self.assertFalse(failures.image_content_rejected(rejection(code, status)))
        for body in (None, [], {'error': {'code': []}}, {'error': 'content_policy_violation'}):
            response = rejection();response._content = json.dumps(body).encode()
            self.assertFalse(failures.image_content_rejected(response))

    def test_native_rejection_keeps_prompt_model_cost_uncertainty_and_no_fallback(self):
        prompt = 'buatkan gambar spiderman'
        for code in failures.IMAGE_REJECTION_CODES:
            with self.subTest(code=code), patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), \
                 patch.object(selected_image.requests, 'post', return_value=rejection(code)) as post:
                with self.assertRaises(tools.ToolUnavailable) as caught:
                    tools.image(prompt, selected_model=chat_offering.IMAGE_MODEL)
            error = caught.exception
            self.assertEqual((error.code, str(error), error.model),
                             (failures.IMAGE_REJECTION_CODE, failures.IMAGE_REJECTION_MESSAGE, chat_offering.IMAGE_MODEL))
            self.assertTrue(error.usage['billing_unknown'])
            self.assertNotIn('provider_rejected', error.usage)
            self.assertNotIn('PRIVATE_PROVIDER_BODY', str(error))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs['json']['prompt'], prompt)
            self.assertEqual(post.call_args.kwargs['json']['model'], chat_offering.IMAGE_MODEL)

    def test_thread_sse_preserves_specific_message_and_does_not_inject_old_context(self):
        prompt = 'buatkan gambar spiderman'
        store.append_assistant(self.owner, self.thread, 'Old unrelated logo concept: PRIVATE_OLD_CONCEPT',
                               'SMART', 'openai', chat_offering.CHAT_MODEL, 'prior-concept', {})
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), \
             patch.object(selected_image.requests, 'post', return_value=rejection()) as post:
            response = self.submit(agent=False, text=prompt, key='safety_thread_00000001')
        self.assertEqual(response.status_code, 200)
        self.assertIn(failures.IMAGE_REJECTION_MESSAGE, response.text)
        self.assertNotIn('Gambar belum dapat dibuat sekarang', response.text)
        self.assertNotIn('PRIVATE_PROVIDER_BODY', response.text)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith('/images/generations'))
        self.assertEqual(post.call_args.kwargs['json']['prompt'], prompt)
        self.assertNotIn('files', post.call_args.kwargs)
        row = db.query_one('SELECT status,model,customer_charge_exempt FROM kilas_ai_usage WHERE operation_key=?', ('safety_thread_00000001',))
        self.assertEqual((row['status'], row['model'], row['customer_charge_exempt']), ('FAILED', chat_offering.IMAGE_MODEL, 1))

    def test_edit_rejection_preserves_original_reference_bytes_without_retry(self):
        source = {'filename': 'original.png', 'mime_type': 'image/png', 'content': b'synthetic-original-bytes'}
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), \
             patch.object(selected_image.requests, 'post', return_value=rejection('moderation_blocked')) as post:
            with self.assertRaises(tools.ToolUnavailable) as caught:
                tools.image('Ubah gambar ini sesuai instruksi saya.', source, selected_model=chat_offering.IMAGE_MODEL)
        self.assertEqual(caught.exception.code, failures.IMAGE_REJECTION_CODE)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith('/images/edits'))
        self.assertEqual(post.call_args.kwargs['files']['image'][1], source['content'])

    def test_queued_rejection_is_visible_terminal_once_and_preserves_direct_brief(self):
        prompt = 'buatkan gambar spiderman'
        agent_store.append(self.owner, 'assistant', 'Old unrelated visual: PRIVATE_OLD_CONCEPT', self.conversation)
        response = self.submit(text=prompt, key='safety_queue_00000001')
        self.assertIn(response.status_code, (200, 303))
        job = autonomous_store.list_jobs(self.owner)[0]
        checkpoint = json.loads(job['checkpoint_json'])
        self.assertEqual(checkpoint['image_prompt_full'], prompt)
        self.assertFalse(checkpoint.get('image_source_ids'))
        self.assertFalse(checkpoint.get('image_source_id'))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-only'}), \
             patch.object(selected_image.requests, 'post', return_value=rejection()) as post:
            for _ in range(2):
                batch = autonomous_store.claim_due(1)
                self.assertEqual(len(batch), 1)
                autonomous_runner.execute(*batch[0])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs['json']['prompt'], prompt)
        self.assertTrue(post.call_args.args[0].endswith('/images/generations'))
        row = autonomous_store.get(self.owner, job['id'])
        self.assertEqual(row['status'], 'FAILED')
        self.assertIsNone(row['next_wake_at'])
        self.assertEqual(row['last_error'], failures.IMAGE_REJECTION_CODE)
        self.assertEqual(autonomous_store.claim_due(1), [])
        self.assertIn(failures.IMAGE_REJECTION_MESSAGE, row['checkpoint_json'])
        ledger = db.query_all('SELECT status,model,customer_charge_exempt FROM kilas_ai_usage WHERE user_id=? AND operation_type=?', (self.owner, 'IMAGE_GENERATION'))
        self.assertEqual(len(ledger), 1)
        self.assertEqual((ledger[0]['status'], ledger[0]['model'], ledger[0]['customer_charge_exempt']), ('FAILED', chat_offering.IMAGE_MODEL, 1))

    def test_followup_context_is_deliberate_not_added_to_direct_request(self):
        prompt = 'buatkan gambar spiderman'
        self.assertEqual(routing.enhance_image_prompt(routing.image_prompt(prompt, 'A previous logo concept'), prompt), prompt)
        followup = 'Buat gambarnya dari konsep tadi'
        self.assertIn('A previous logo concept', routing.image_prompt(followup, 'A previous logo concept'))

    def test_rejection_copy_has_all_app_locales(self):
        from pathlib import Path
        catalog = json.loads((Path(__file__).parents[1] / 'locales/ui.json').read_text())
        self.assertEqual(set(catalog[failures.IMAGE_REJECTION_MESSAGE]), {'id', 'en', 'es', 'zh'})
        self.assertTrue(all(catalog[failures.IMAGE_REJECTION_MESSAGE].values()))


if __name__ == '__main__':
    unittest.main()
