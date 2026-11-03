"""Default-off, owned first-turn Luna experiment. No public debug controls."""
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid

from PIL import Image

FLAG = 'KILAS_AI_VISION_EVAL_BATCH'
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
        if not isinstance(value, dict) or set(value) != {'owner_id', 'batch', 'starts_at', 'expires_at', 'question'}:
            return {}
        if type(value['owner_id']) is not int or not 0 < value['owner_id'] <= 2**63-1 or \
                not isinstance(value['batch'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['batch']):
            return {}
        question = value['question']
        if not isinstance(question, str) or not 1 <= len(question) <= 200 or question != question.strip() or \
                any(ord(c) < 32 for c in question):
            return {}
        for name in ('starts_at', 'expires_at'):
            if not isinstance(value[name], str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', value[name]):
                return {}
        start = datetime.fromisoformat(value['starts_at'])
        end = datetime.fromisoformat(value['expires_at'])
        if not timedelta(0) < end-start <= timedelta(minutes=30) or not start <= _now() < end:
            return {}
        value['fingerprint'] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        value['_start'], value['_end'] = start, end
        return value
    except (TypeError, ValueError, RecursionError):
        return {}


def _now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class _Grant:
    issuer: object
    context_id: int
    arm: str
    sequence: int


def _claim(config, user_id, thread_id):
    """Serialize only QA admission; no lock spans provider work or ledger writes."""
    if config['owner_id'] != user_id:
        return None
    from . import usage
    from .autonomous_store import transaction
    import db
    with transaction() as conn:
        if db.BACKEND == 'postgres':
            usage._query(conn, 'SELECT pg_advisory_xact_lock(hashtext(?))', (config['batch'],))
        owner = usage._query(conn, 'SELECT id FROM users WHERE id=?' +
                             (' FOR UPDATE' if db.BACKEND == 'postgres' else ''), (user_id,), one=True)
        if not owner or not config['_start'] <= _now() < config['_end']:
            return None
        thread = usage._query(conn, 'SELECT created_at FROM kilas_ai_threads WHERE id=? AND user_id=?',
                              (thread_id, user_id), one=True)
        if not thread or not config['_start'] <= usage._as_utc(thread[0]) < config['_end']:
            return None
        rows = usage._rows(conn, 'SELECT id,role,content FROM kilas_ai_messages WHERE thread_id=? ORDER BY id LIMIT 2', (thread_id,))
        if len(rows) != 1 or rows[0][1] != 'user' or rows[0][2] != config['question']:
            return None
        prior = usage._query(conn, 'SELECT sequence,config_fingerprint,user_id FROM kilas_ai_vision_eval_claims '
                             'WHERE batch=? AND message_id=?', (config['batch'], rows[0][0]), one=True)
        if prior:
            return prior[0] if prior[1] == config['fingerprint'] and prior[2] == user_id else None
        claimed = usage._rows(conn, 'SELECT sequence,config_fingerprint,user_id FROM kilas_ai_vision_eval_claims '
                              'WHERE batch=? ORDER BY sequence', (config['batch'],))
        if len(claimed) >= 8 or any(row[1] != config['fingerprint'] or row[2] != user_id for row in claimed):
            return None
        sequence = max((row[0] for row in claimed), default=0)+1
        if sequence > 8 or _now() >= config['_end']:
            return None
        usage._query(conn, 'INSERT INTO kilas_ai_vision_eval_claims '
                     '(user_id,batch,sequence,thread_id,message_id,config_fingerprint) VALUES (?,?,?,?,?,?)',
                     (user_id, config['batch'], sequence, thread_id, rows[0][0], config['fingerprint']))
        return sequence


def bind(context, user_id, thread_id):
    """Called only after send admission; independently recheck auth/ownership."""
    config = configured()
    if not config or config['owner_id'] != user_id or getattr(context, 'selected_model', None) != MODEL:
        return
    from flask import has_request_context, request, session
    if not has_request_context() or request.endpoint != 'kilas_ai.send' or \
            session.get('user_id') != user_id or (request.view_args or {}).get('thread_id') != thread_id:
        return
    if len(context) != 1 or context[0].get('role') != 'user' or not isinstance(context[0].get('content'), list):
        return
    blocks = context[0]['content']
    if [block.get('text') for block in blocks if block.get('type') == 'text'] != [config['question']] or \
            sum(block.get('type') == 'image_url' for block in blocks) != 1:
        return
    try:
        sequence = _claim(config, user_id, thread_id)
    except Exception:
        _log.warning('kilas_vision_eval_scope_storage_unavailable')
        return  # A missing migration/storage failure cannot enable the experiment.
    if sequence:
        context._vision_experiment = _Grant(_ISSUER, id(context), 'auto' if sequence % 2 else 'high', sequence)


def _emit(record):
    # Never accept arbitrary provider/request dictionaries here.
    try:
        print('kilas_vision_eval ' + json.dumps(record, sort_keys=True, separators=(',', ':')), flush=True)
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
    return payload, Diagnostic(grant.arm, grant.sequence, summary, payload)


def _number(value):
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


class Diagnostic:
    def __init__(self, arm, sequence, image, payload):
        self.run = uuid.uuid4().hex
        self.arm = arm
        self.sequence = sequence
        self.started = time.monotonic()
        self.first = None
        self.returned_model = 'unreported'
        self.request_id = 'unreported'
        self.http_status = None
        self.finish_reason = 'unreported'
        self.usage = {}
        effort = payload.get('reasoning_effort')
        _emit({'event': 'request', 'run': self.run, 'arm': arm, 'sequence': sequence, 'requested_model': MODEL,
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
        _emit({'event': 'response', 'run': self.run, 'arm': self.arm, 'sequence': self.sequence,
               'requested_model': MODEL, 'returned_model': self.returned_model,
               'provider_request_id': self.request_id, 'http_status': self.http_status,
               'finish_reason': self.finish_reason,
               'status': 'finished' if self.finish_reason != 'unreported' else 'incomplete',
               'duration_ms': round(1000*(time.monotonic()-self.started)),
               'ttft_ms': round(1000*(self.first-self.started)) if self.first is not None else None,
               'usage': self.usage})
