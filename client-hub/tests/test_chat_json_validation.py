"""Private Chat JSON validation: synthetic accounts, no provider transport."""
import unittest
from unittest.mock import patch
import test_kilas_chat_models as fixture
from kilas_ai import store, providers
import db


class ChatJSONValidationTests(unittest.TestCase):
    setUp = fixture.RouteTests.setUp
    client = fixture.RouteTests.client

    def post(self, path, body):
        return self.client().post(path, json=body, headers={'X-CSRF-Token': 'work-csrf'})

    def test_nonobject_json_is_rejected_before_side_effects(self):
        paths = ['/kilas-ai/threads', '/kilas-ai/chat/model', '/kilas-ai/chat/image-model',
                 f'/kilas-ai/threads/{self.thread}/send', f'/kilas-ai/threads/{self.thread}/regenerate']
        before = db.query_all('SELECT * FROM kilas_ai_threads ORDER BY id')
        with patch.object(store, 'create_thread') as create, patch.object(providers, 'stream') as stream:
            for path in paths:
                for body in ([1], 'text', 17, True, [], {}):
                    with self.subTest(path=path, body=body):
                        self.assertEqual(self.post(path, body).status_code, 400)
            create.assert_not_called();stream.assert_not_called()
        self.assertEqual(before, db.query_all('SELECT * FROM kilas_ai_threads ORDER BY id'))

    def test_first_message_requires_nonempty_string(self):
        before = db.query_all('SELECT * FROM kilas_ai_threads ORDER BY id')
        for value in ({'bad': 'shape'}, ['hello'], 17, True, None, '', '  '):
            with self.subTest(value=value):
                self.assertEqual(self.post('/kilas-ai/threads', {'first_message': value}).status_code, 400)
        self.assertEqual(before, db.query_all('SELECT * FROM kilas_ai_threads ORDER BY id'))
        self.assertEqual(self.post('/kilas-ai/threads', {'first_message': 'Hello'}).status_code, 201)

    def test_send_rejects_nontext_and_preserves_missing_empty_validation(self):
        with patch.object(providers, 'stream') as stream:
            for value in ({'bad': 'shape'}, ['hello'], 17, True, None, '', '  '):
                with self.subTest(value=value):
                    response = self.post(f'/kilas-ai/threads/{self.thread}/send',
                        {'content': value, 'operation_key': 'synthetic_key_123456'})
                    self.assertEqual(response.status_code, 400)
            stream.assert_not_called()

    def test_malformed_json_and_form_navigation_stay_safe(self):
        client = self.client()
        response = client.post('/kilas-ai/threads', data='{', content_type='application/json', headers={'X-CSRF-Token': 'work-csrf'})
        self.assertEqual(response.status_code, 400)
        response = client.post('/kilas-ai/threads', data={'csrf_token': 'work-csrf'})
        self.assertEqual(response.status_code, 303)


if __name__ == '__main__':
    unittest.main()
