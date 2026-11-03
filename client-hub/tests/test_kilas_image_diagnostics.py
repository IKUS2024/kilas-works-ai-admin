"""Synthetic errors only: bounded provider telemetry and no secret/prompt logging."""
import json
import os
import unittest
from unittest.mock import patch
import requests
from kilas_ai import image_diagnostics, selected_image, tools


def response(status, body, request_id='req_synthetic123'):
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps(body).encode()
    value.headers['x-request-id'] = request_id
    return value


class ImageDiagnosticsTests(unittest.TestCase):
    def run_failure(self, result):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'SYNTHETIC_SECRET_NEVER_LOG'}), \
             patch('kilas_ai.image_models.check', return_value={'available': True}), \
             patch.object(selected_image.requests, 'post', side_effect=result if isinstance(result, Exception) else None,
                          return_value=result) as post, \
             self.assertLogs('kilas_ai.image_diagnostics', level='WARNING') as logs:
            with self.assertRaises(tools.ToolUnavailable) as caught:
                selected_image.generate('gpt-image-2.5-sunburst', 'PRIVATE_PROMPT_NEVER_LOG')
        self.assertEqual(post.call_count, 1)
        text = '\n'.join(logs.output)
        for secret in ('PRIVATE_PROMPT_NEVER_LOG', 'SYNTHETIC_SECRET_NEVER_LOG', 'PRIVATE_PROVIDER_BODY'):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(len(logs.output), 1)
        return caught.exception, json.loads(logs.output[0].split('KILAS_IMAGE_FAILURE ')[1])

    def test_http_400_has_safe_status_request_id_and_parameter(self):
        error, event = self.run_failure(response(400, {'error': {'code': 'invalid_value', 'param': 'size', 'message': 'PRIVATE_PROVIDER_BODY'}}))
        self.assertEqual((event['http_status'], event['category'], event['parameter'], event['request_id']),
                         (400, 'invalid_request', 'size', 'req_synthetic123'))
        self.assertNotEqual(error.code, 'provider_quota_exhausted')

    def test_quota_branch_remains_distinct_and_not_retried(self):
        error, event = self.run_failure(response(429, {'error': {'code': 'insufficient_quota'}}))
        self.assertEqual(error.code, 'provider_quota_exhausted')
        self.assertEqual(event['category'], 'quota')
        self.assertTrue(error.usage['provider_rejected'])
        self.assertFalse(error.usage['billing_unknown'])

    def test_timeout_and_invalid_image_are_distinct(self):
        _, event = self.run_failure(requests.ReadTimeout('PRIVATE_PROVIDER_BODY'))
        self.assertEqual(event['category'], 'timeout')
        _, event = self.run_failure(response(200, {'data': [{'b64_json': 'bm90IGFuIGltYWdl'}]}))
        self.assertEqual((event['stage'], event['category']), ('image_validation', 'invalid_response'))

    def test_safety_rate_limit_and_bad_fields_do_not_expose_content(self):
        for code, expected in [('content_policy_violation', 'safety'), ('rate_limit_exceeded', 'rate_limit')]:
            with self.subTest(code=code):
                _, event = self.run_failure(response(429, {'error': {'code': code}}))
                self.assertEqual(event['category'], expected)
        with self.assertLogs('kilas_ai.image_diagnostics', level='WARNING') as logs:
            event = image_diagnostics.record('gpt-image-2.5-sunburst', None,
                response(400, {'error': {'code': 'PRIVATE_PROVIDER_BODY', 'param': 'PRIVATE_PROMPT_NEVER_LOG'}},
                         request_id='sk-SYNTHETIC_SECRET_NEVER_LOG'))
        self.assertNotIn('parameter', event)
        self.assertNotIn('request_id', event)
        self.assertNotIn('PRIVATE_', '\n'.join(logs.output))


if __name__ == '__main__':
    unittest.main()
