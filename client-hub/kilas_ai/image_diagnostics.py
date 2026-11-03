"""Allowlisted image failure telemetry; never log bodies, prompts or credentials."""
import json
import logging
import re
import requests

_CODES = {
    'insufficient_quota': 'quota', 'credit_balance_exhausted': 'quota',
    'billing_hard_limit_reached': 'quota', 'billing_not_active': 'quota',
    'content_policy_violation': 'safety', 'moderation_blocked': 'safety',
    'rate_limit_exceeded': 'rate_limit', 'invalid_api_key': 'authentication',
    'invalid_value': 'invalid_request', 'invalid_parameter': 'invalid_request',
    'unsupported_parameter': 'invalid_request', 'model_not_found': 'model_access',
    'permission_denied': 'model_access', 'server_error': 'provider_server',
}
_PARAMS = frozenset(('model', 'size', 'quality', 'background', 'output_format', 'n', 'image', 'image[]', 'prompt'))


def record(model, error, response=None, *, stage='request'):
    status = getattr(response, 'status_code', None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    category = ('timeout' if isinstance(error, requests.Timeout) else
                'network' if isinstance(error, requests.ConnectionError) else
                'invalid_response' if stage != 'request' else 'provider_error')
    event = {'model': model, 'stage': stage, 'category': category, 'http_status': status}
    if response is not None:
        try:
            detail = response.json().get('error', {})
            if isinstance(detail, dict):
                category = _CODES.get(detail.get('code')) or _CODES.get(detail.get('type')) or category
                if detail.get('param') in _PARAMS:
                    event['parameter'] = detail['param']
        except (ValueError, TypeError, AttributeError):
            pass
        if category == 'provider_error':
            category = ('authentication' if status == 401 else 'model_access' if status == 403 else
                        'rate_limit' if status == 429 else 'invalid_request' if status == 400 else
                        'provider_server' if status and status >= 500 else category)
        headers = getattr(response, 'headers', {}) or {}
        request_id = headers.get('x-request-id', '')
        if isinstance(request_id, str) and re.fullmatch(r'req_[A-Za-z0-9_-]{1,96}', request_id):
            event['request_id'] = request_id
    event['category'] = category
    logging.getLogger(__name__).warning('KILAS_IMAGE_FAILURE %s', json.dumps(event, sort_keys=True))
    return event
