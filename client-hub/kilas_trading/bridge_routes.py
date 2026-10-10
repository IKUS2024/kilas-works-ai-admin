"""Narrow bearer transport handler; existing session/CSRF guards are unchanged."""
from collections import OrderedDict, deque
import threading
import time
from flask import request, jsonify
import security
from werkzeug.exceptions import RequestEntityTooLarge
from . import bridge
from .routes import bp

_rates = OrderedDict()
_rate_lock = threading.Lock()

def response(value, status=200):
    out = jsonify(value)
    out.status_code = status
    out.headers['Cache-Control'] = 'no-store'
    out.headers['Pragma'] = 'no-cache'
    return out

def limited():
    # Bounded per-worker abuse defense; no persistent IP or credential logging.
    key = request.remote_addr or 'unknown'
    current = time.monotonic()
    with _rate_lock:
        recent = _rates.pop(key, deque())
        while recent and current-recent[0] >= 60: recent.popleft()
        allowed = len(recent) < 60
        if allowed: recent.append(current)
        _rates[key] = recent
        while len(_rates) > 1024: _rates.popitem(last=False)
    return allowed

def transport():
    if request.endpoint not in ('kilas_trading.bridge_exchange','kilas_trading.bridge_telemetry'):
        return None
    if not bridge.enabled(): return response({'outcome':'DISABLED'},404)
    try:
        bridge.require(request.method == 'POST' and request.mimetype == 'application/json', 'JSON_REQUIRED',415)
        bridge.require(not request.args and not request.headers.get('Cookie'), 'COOKIE_OR_QUERY_NOT_ALLOWED',400)
        bridge.require(limited(), 'REQUEST_RATE_LIMIT',429)
        bridge.require(not request.content_length or request.content_length <= bridge.MAX_BYTES, 'PAYLOAD_TOO_LARGE',413)
        request.max_content_length = bridge.MAX_BYTES
        data = bridge.parse(request.get_data(cache=False))
        if request.endpoint == 'kilas_trading.bridge_exchange':
            bridge.require(not request.headers.get('Authorization'), 'INVALID_CREDENTIAL',401)
            result = bridge.exchange(data)
        else:
            header = request.headers.get('Authorization','')
            bridge.require(header.startswith('Bearer ') and len(header)==71, 'INVALID_CREDENTIAL',401)
            result = bridge.telemetry(header[7:],data)
        return response(result)
    except bridge.Rejected as exc:
        return response({'outcome':exc.code},exc.status)
    except RequestEntityTooLarge:
        return response({'outcome':'PAYLOAD_TOO_LARGE'},413)
    except Exception:
        # Never log/echo payload, token, code, SDK exception or database exception.
        return response({'outcome':'BRIDGE_UNAVAILABLE'},503)

@bp.record_once
def install(state):
    # Early-return only these two exact POST endpoints, which have their own
    # one-use secret/bearer authorization and no cookie authority. The existing
    # host guard is subsequently inserted ahead of this handler by app startup.
    # All session endpoints continue through the existing global CSRF check.
    state.app.before_request_funcs.setdefault(None,[]).insert(0,transport)

@bp.post('/bridge/exchange')
def bridge_exchange(): return response({'outcome':'BRIDGE_UNAVAILABLE'},503)

@bp.post('/bridge/telemetry')
def bridge_telemetry(): return response({'outcome':'BRIDGE_UNAVAILABLE'},503)

def session_action(function, allow_disabled=False):
    if not allow_disabled and not bridge.enabled(): return response({'outcome':'DISABLED'},404)
    try: return response(function())
    except bridge.Rejected as exc: return response({'outcome':exc.code},exc.status)
    except Exception: return response({'outcome':'BRIDGE_UNAVAILABLE'},503)

@bp.post('/bridge/pair')
def bridge_pair():
    def perform():
        bridge.require(not request.args)
        data = request.get_json() if request.is_json else request.form.to_dict()
        if not request.is_json:
            bridge.require(set(data)=={'csrf_token','symbol','server'})
            data.pop('csrf_token')
        return bridge.pair(security.current_user()['id'],data)
    return session_action(perform)

@bp.post('/bridge/revoke')
def bridge_revoke():
    def perform():
        bridge.require(not request.args)
        data = request.get_json() if request.is_json else request.form.to_dict()
        bridge.require(data == {} if request.is_json else set(data)=={'csrf_token'})
        return bridge.revoke(security.current_user()['id'])
    return session_action(perform, allow_disabled=True)

@bp.get('/bridge/status')
def bridge_status(): return session_action(lambda:bridge.status(security.current_user()['id']), allow_disabled=True)
