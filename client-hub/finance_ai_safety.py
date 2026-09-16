"""Finance AI-only validation, bounded local quotas and redacted operational events."""
import json
import logging
import os
import re
import threading
import time
from functools import wraps

from flask import make_response
from werkzeug.exceptions import HTTPException

_RATE = {}
_LOCK = threading.Lock()
_EVENTS = frozenset(('analyst_success','analyst_failure','draft_generated','confirmation_accepted',
    'confirmation_rejected','operator_replay','expired_draft','tampered_draft','invalid_draft',
    'permission_denied','allowlist_denied','rate_limited','invalid_request','not_configured',
    'upstream_failure','network_failure','timeout','invalid_result','request_failed'))
_LOG = logging.getLogger('kilas.finance_ai')
_LOG.setLevel(logging.INFO)


def event(name):
    # No free-form exception/model/request content, IDs, tokens or financial values.
    _LOG.info('FINANCE_AI event=%s', name if name in _EVENTS else 'request_failed')


def endpoint(view):
    """Observe existing auth decisions; never replace authentication or CSRF."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            response = make_response(view(*args, **kwargs))
        except HTTPException as error:
            if error.code in (401,403,404): event('permission_denied')
            raise
        if response.status_code in (301,302,401,403): event('permission_denied')
        response.headers['Cache-Control']='private, no-store'
        return response
    return wrapped


def allowlisted(env_name, business_id):
    raw=os.environ.get(env_name,'')
    if type(business_id) is not int or not 0<business_id<2**63 or not raw or len(raw)>2048:
        return False
    parts=[p.strip() for p in raw.split(',')]
    # One malformed entry invalidates the WHOLE setting, not just that entry.
    if len(parts)>100 or any(not re.fullmatch(r'[1-9][0-9]{0,18}',p) or int(p)>=2**63 for p in parts):
        return False
    return str(business_id) in parts


def configuration():
    key=os.environ.get('ANTHROPIC_API_KEY','').strip()
    model=os.environ.get('CLIENT_HUB_FINANCE_ANALYST_MODEL','').strip() or 'claude-haiku-4-5-20251001'
    if not key or len(key)>512 or any(c.isspace() for c in key) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',model):
        raise ValueError('not_configured')
    return key,model


def allow_attempt(user_id, business_id=None, kind='ai'):
    """Shared across analyst/draft endpoints in ONE process, never a DB write.

    User caps prevent hopping tenants; business caps prevent member-account rotation.
    Separate confirmation bucket leaves deterministic retry available after AI quota.
    Bounded map fails closed at capacity. No claim of distributed/global enforcement.
    """
    if kind not in ('ai','confirm'): return False
    now=time.monotonic()
    caps=[((kind,'user',user_id),6 if kind=='ai' else 30)]
    if business_id is not None: caps.append(((kind,'business',business_id),20 if kind=='ai' else 60))
    with _LOCK:
        for key in list(_RATE):
            _RATE[key]=[stamp for stamp in _RATE[key] if now-stamp<60]
            if not _RATE[key]: del _RATE[key]
        if len(_RATE)+sum(key not in _RATE for key,_ in caps)>4096:
            event('rate_limited');return False
        if any(len(_RATE.get(key,()))>=cap for key,cap in caps):
            event('rate_limited');return False
        for key,_ in caps: _RATE.setdefault(key,[]).append(now)
    return True


def json_object(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate_key')
            result[key]=value
        return result
    def invalid_constant(value):
        raise ValueError('nonfinite')
    value=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid_constant)
    if not isinstance(value,dict): raise ValueError('object_required')
    return value


def response_text(body, maximum):
    if not isinstance(body,dict) or body.get('stop_reason')!='end_turn': raise ValueError('incomplete')
    blocks=body.get('content')
    if not isinstance(blocks,list) or len(blocks)!=1 or not isinstance(blocks[0],dict) or blocks[0].get('type')!='text':
        raise ValueError('invalid_content')
    raw=blocks[0].get('text')
    if not isinstance(raw,str) or not raw.strip() or len(raw)>maximum: raise ValueError('invalid_text')
    return raw
