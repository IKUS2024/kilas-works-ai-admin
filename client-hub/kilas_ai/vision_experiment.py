"""Default-off, owned first-turn Luna experiment. No public debug controls."""
import base64
from dataclasses import dataclass
import io
import json
import logging
import os
import re
import time
import uuid

from PIL import Image

FLAG = 'KILAS_AI_VISION_EVAL_THREADS'
MODEL = 'gpt-6-luna'
_ISSUER = object()
_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def configured():
    raw = os.environ.get(FLAG, '')
    if not raw or len(raw) > 2048:
        return {}
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        if not isinstance(value, dict) or not 1 <= len(value) <= 8:
            return {}
        if any(not re.fullmatch(r'[1-9][0-9]{0,18}', key) or int(key) > 2**63-1 or
               arm not in ('auto', 'high') for key, arm in value.items()):
            return {}
        return value
    except (TypeError, ValueError, RecursionError):
        return {}


@dataclass(frozen=True)
class _Grant:
    issuer: object
    context_id: int
    arm: str


def bind(context, user_id, thread_id):
    """Called only after send admission; independently recheck auth/ownership."""
    arm = configured().get(str(thread_id))
    if not arm or getattr(context, 'selected_model', None) != MODEL:
        return
    from flask import has_request_context, request, session
    if not has_request_context() or request.endpoint != 'kilas_ai.send' or \
            session.get('user_id') != user_id or (request.view_args or {}).get('thread_id') != thread_id:
        return
    from . import store
    if not store.thread(user_id, thread_id):
        return
    rows = store.messages(user_id, thread_id, 2)
    if len(rows) != 1 or rows[0]['role'] != 'user':
        return
    context._vision_experiment = _Grant(_ISSUER, id(context), arm)


def _emit(record):
    # Never accept arbitrary provider/request dictionaries here.
    try:
        _log.info('kilas_vision_eval %s', json.dumps(record, sort_keys=True, separators=(',', ':')))
    except Exception:
        pass  # Optional diagnostics must not interrupt Chat or its metering.


def begin(context, payload):
    grant = getattr(context, '_vision_experiment', None)
    if not isinstance(grant, _Grant) or grant.issuer is not _ISSUER or grant.context_id != id(context) or \
            payload.get('model') != MODEL or grant.arm not in ('auto', 'high'):
        return payload, None
    rows = [row for row in payload['messages'] if row.get('role') != 'system']
    if len(rows) != 1 or rows[0].get('role') != 'user' or not isinstance(rows[0].get('content'), list):
        return payload, None
    blocks = rows[0]['content']
    images = [block for block in blocks if block.get('type') == 'image_url']
    if len(images) != 1:
        return payload, None
    part = images[0].get('image_url', {})
    if 'detail' in part:
        return payload, None  # This experiment compares omission with high, only.
    url = part.get('url', '')
    if not isinstance(url, str) or len(url) > 7*1024*1024:
        return payload, None
    match = re.fullmatch(r'data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)', url)
    if not match:
        return payload, None
    try:
        raw = base64.b64decode(match[2], validate=True)
        if not raw or len(raw) > 5*1024*1024:
            return payload, None
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if not 0 < width*height <= 20_000_000:
                return payload, None
            image.verify()
    except Exception:
        return payload, None
    if grant.arm == 'high':
        changed = [dict(block, image_url=dict(block['image_url'], detail='high'))
                   if block.get('type') == 'image_url' else block for block in blocks]
        payload = dict(payload, messages=[dict(row, content=changed) if row is rows[0] else row
                                         for row in payload['messages']])
    summary = {'mime': match[1], 'width': width, 'height': height, 'bytes': len(raw),
               'detail': grant.arm, 'detail_explicit': grant.arm == 'high'}
    return payload, Diagnostic(grant.arm, summary, payload)


def _number(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


class Diagnostic:
    def __init__(self, arm, image, payload):
        self.run = uuid.uuid4().hex
        self.arm = arm
        self.started = time.monotonic()
        self.first = None
        self.returned_model = 'unreported'
        self.request_id = 'unreported'
        self.http_status = None
        self.finish_reason = 'unreported'
        self.usage = {}
        effort = payload.get('reasoning_effort')
        _emit({'event': 'request', 'run': self.run, 'arm': arm, 'requested_model': MODEL,
               'image_count': 1, 'images': [image],
               'reasoning_effort': effort if effort in ('none', 'low', 'medium', 'high', 'xhigh', 'max') else 'unreported',
               'max_completion_tokens': _number(payload.get('max_completion_tokens'))})

    def response(self, response):
        status = response.status_code
        self.http_status = status if type(status) is int and 100 <= status <= 599 else None
        ident = response.headers.get('x-request-id', '')
        if isinstance(ident, str) and re.fullmatch(r'req_[A-Za-z0-9_-]{1,100}', ident):
            self.request_id = ident

    def model(self, actual):
        if isinstance(actual, str) and re.fullmatch(r'gpt-6-luna(?:-(?:20\d\d-\d\d-\d\d|\d{3}))?', actual):
            self.returned_model = actual

    def tokens(self, usage):
        details = usage.get('prompt_tokens_details') or {}
        if not isinstance(details, dict):
            details = {}
        self.usage = {'input_tokens': _number(usage.get('prompt_tokens')),
                      'output_tokens': _number(usage.get('completion_tokens')),
                      'cached_input_tokens': _number(details.get('cached_tokens')),
                      'cache_write_input_tokens': _number(details.get('cache_write_tokens'))}

    def delta(self):
        if self.first is None:
            self.first = time.monotonic()

    def finish(self, reason):
        if reason in ('stop', 'length', 'refusal', 'content_filter'):
            self.finish_reason = reason

    def end(self):
        _emit({'event': 'response', 'run': self.run, 'arm': self.arm,
               'requested_model': MODEL, 'returned_model': self.returned_model,
               'provider_request_id': self.request_id, 'http_status': self.http_status,
               'finish_reason': self.finish_reason,
               'status': 'finished' if self.finish_reason != 'unreported' else 'incomplete',
               'duration_ms': round(1000*(time.monotonic()-self.started)),
               'ttft_ms': round(1000*(self.first-self.started)) if self.first is not None else None,
               'usage': self.usage})
