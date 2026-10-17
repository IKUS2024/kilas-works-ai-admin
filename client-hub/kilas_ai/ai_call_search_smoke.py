"""Default-off, once-only approved public-news Call/search QA child.

The sole input is a pinned synthetic browser capture. Normal provider setup,
access and usage policies are retained. Hard fences permit one Google socket,
one normal Call envelope and one normal WEB_SEARCH/HTTP dispatch. No retries.
"""
import base64
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from threading import Lock, Timer
import time
import wave

RUN = 'call-search-news-20261017-0943'
IDENT = hashlib.sha256(RUN.encode()).hexdigest()[:32]
ARM = 'KILAS_AI_CALL_SMOKE_RUN'
SERVICE = 'srv-da7ti2psrm7s73dh9i2g'
RAW_SHA = 'dc3170ff1cecf5d6a41170037847421a8f283ff7943e821492464f2f23292967'
CORE = os.environ.get('RENDER_GIT_COMMIT', '')
CORE = CORE if re.fullmatch('[a-f0-9]{40}', CORE) else 'unavailable'
SESSION_SECONDS = 55  # Connection/cleanup also bounded by the 60s process alarm.
INPUT_SECONDS = 12    # Pinned 5.8s speech plus its natural silence tail.
SPOKEN_WAIT_SECONDS = 30
MAX_JSON_BYTES = 8192
MAX_QUERY_BYTES = 512
PAUSE_AT_MS = 2220
PAUSE_MS = 800


def json_bytes(value):
    return len(json.dumps(value).encode('utf-8'))


def validate_send(message):
    """Bound setup/tool evidence before forwarding; preserve production setup."""
    if 'setup' in message:
        value = message['setup']
        if (json_bytes(message) > MAX_JSON_BYTES
                or value['realtimeInputConfig']['automaticActivityDetection']['disabled'] is not False
                or value['generationConfig']['maxOutputTokens'] != 1024):
            raise ValueError('setup_changed')
    if 'toolResponse' in message and json_bytes(message) > MAX_JSON_BYTES:
        raise ValueError('tool_response_fence')


def usage_summary(used):
    """Bounded non-content provider usage; retain modality splits when present."""
    if not isinstance(used, dict):
        return {}
    result = {k: v for k, v in used.items() if k in ('promptTokenCount', 'responseTokenCount',
        'totalTokenCount', 'thoughtsTokenCount', 'cachedContentTokenCount') and type(v) is int and 0 <= v <= 10**9}
    for key in ('promptTokensDetails', 'responseTokensDetails', 'cacheTokensDetails'):
        values = used.get(key)
        if isinstance(values, list):
            result[key] = [{'modality': item['modality'], 'tokenCount': item['tokenCount']}
                for item in values[:8] if isinstance(item, dict)
                and item.get('modality') in ('TEXT', 'AUDIO', 'IMAGE', 'VIDEO')
                and type(item.get('tokenCount')) is int and 0 <= item['tokenCount'] <= 10**9]
    return result


def replay_response(data):
    """Synthetic-only public response fixture; no input, headers or reasoning."""
    value = {key: data[key] for key in ('status', 'incomplete_details', 'max_tool_calls', 'output', 'usage') if key in data}
    error = data.get('error')
    value['error'] = ({key: error[key] for key in ('code', 'type', 'param') if isinstance(error.get(key), str)
                       and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,80}', error[key])}
                      if isinstance(error, dict) else None if error is None else {'present': True})
    if isinstance(value.get('output'), list):
        value['output'] = [{key: item[key] for key in ('id', 'type', 'status') if key in item}
                           if isinstance(item, dict) and item.get('type') == 'reasoning' else item
                           for item in value['output']]
    size = json_bytes(value)
    return {'truncated': True, 'serialized_bytes': size} if size > 32768 else {
        'truncated': False, 'serialized_bytes': size, 'response': value}


def armed():
    try:
        expiry = datetime.fromisoformat(os.environ['KILAS_AI_CALL_SMOKE_EXPIRES_AT'].replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (os.environ.get(ARM) == RUN and os.environ.get('RENDER_SERVICE_ID') == SERVICE
                and expiry.tzinfo is not None and now < expiry <= now + timedelta(minutes=30))
    except (KeyError, ValueError, TypeError):
        return False


def launch():
    if not armed():
        return False
    subprocess.Popen([sys.executable, '-m', 'kilas_ai.ai_call_search_smoke'], close_fds=True)
    return True


def fixture():
    path = Path(__file__).resolve().parents[1] / 'tests/fixtures/ai_call_synthetic/search-indonesia.wav'
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('fixture_invalid')
        raw = wav.readframes(wav.getnframes())
    if len(raw) != 185600 or hashlib.sha256(raw).hexdigest() != RAW_SHA:
        raise ValueError('fixture_changed')
    return raw


def paused_fixture():
    raw = fixture()  # Verify the original pinned capture before augmentation.
    at = PAUSE_AT_MS*32
    return raw[:at]+bytes(PAUSE_MS*32)+raw[at:]


class SearchFence:
    """Inspect only the one public QA request; never record auth headers."""
    def __init__(self, result, check, reserve, finish, post, owner):
        self.result, self.check = result, check
        self.original_reserve, self.original_finish, self.original_post = reserve, finish, post
        self.owner, self.lock = owner, Lock()

    def reserve(self, owner, thread, key, mode, tool, **kwargs):
        self.check()
        with self.lock:
            self.result['search_reserve_attempts'] += 1
            if (self.result['search_reserve_attempts'] != 1 or owner != self.owner or thread is not None
                    or not key.startswith('call-web-') or (mode, tool) != ('FAST', 'WEB')):
                raise ValueError('search_reserve_fence')
        value = self.original_reserve(owner, thread, key, mode, tool, **kwargs)
        if value[1]:
            self.result['search_operation'] = key
            self.result['search_reserved'] = True
        return value

    def finish(self, owner, key, operations, **kwargs):
        value = self.original_finish(owner, key, operations, **kwargs)
        if key == self.result.get('search_operation'):
            self.result['search_settled'] = True
            self.result['search_finished_success'] = kwargs.get('success') is True
        return value

    def post(self, url, **kwargs):
        from . import ai_call_public_search as search
        self.check()
        payload = kwargs.get('json', {})
        expected = search.public_query('general', datetime.now(timezone.utc).strftime('%Y-%m-%d'))
        with self.lock:
            if (self.result['web_http_requests'] != 0 or not self.result.get('search_reserved')
                    or json_bytes(payload) > MAX_JSON_BYTES or len(expected.encode('utf-8')) > MAX_QUERY_BYTES
                    or url != 'https://api.openai.com/v1/responses'
                    or payload.get('model') != 'gpt-6-luna' or payload.get('input') != expected
                    or payload.get('tools') != [{'type': 'web_search'}] or payload.get('tool_choice') != 'required'
                    or payload.get('max_tool_calls') != 1 or payload.get('max_output_tokens') != 2048
                    or payload.get('store') is not False):
                raise ValueError('web_request_fence')
            self.result['web_http_requests'] += 1
            self.result['public_query'] = expected
            self.result['web_model'] = payload['model']
            self.result['web_request_bytes'] = json_bytes(payload)
            self.result['web_query_bytes'] = len(expected.encode('utf-8'))
        before = time.monotonic()
        try:
            response = self.original_post(url, **kwargs)
        except search.tools.requests.Timeout as error:
            self.result['web_timeout_kind'] = ('connect' if isinstance(error, search.tools.requests.ConnectTimeout)
                else 'read' if isinstance(error, search.tools.requests.ReadTimeout) else 'timeout_unspecified')
            raise
        finally:
            self.result['web_http_ms'] = round((time.monotonic()-before)*1000)
        self.result['web_http_status'] = response.status_code
        try:
            data = response.json()
        except Exception:
            return response
        if not isinstance(data, dict):
            return response
        from .ai_call_search_contract import envelope_summary
        self.result['web_response_envelope'] = envelope_summary(data)
        self.result['web_response_fixture'] = replay_response(data)
        if response.status_code >= 400:
            # Only non-content machine error fields; never message/body/headers.
            error = data.get('error', {})
            self.result['web_error'] = {k: v for k, v in error.items() if k in ('code', 'type', 'param')
                and isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,80}', v)} if isinstance(error,dict) else {}
        else:
            self.result['web_completed_searches'] = sum(item.get('type') == 'web_search_call' and item.get('status') == 'completed'
                for item in data.get('output', []) if isinstance(item, dict))
            used = data.get('usage', {})
            self.result['web_usage'] = {k: v for k, v in used.items() if k in ('input_tokens','output_tokens','total_tokens')
                                      and type(v) is int and v >= 0} if isinstance(used,dict) else {}
        return response


def completion_status(result, turns):
    """Observe the model turn after either tool result, including failures."""
    if result.get('response_turn_target') and turns >= result['response_turn_target']:
        return 'completed_transport' if result.get('bridge', {}).get('available') else 'completed_failure_transport'
    return None


def run():
    if not armed():
        return
    os.environ[ARM] = 'off'
    from . import ai_call as calls, ai_call_budget as budget
    from . import ai_call_public_search as search
    import db
    call = None
    timer = None
    owner = None
    original_connect = calls.wire.connect
    original_reserve, original_finish, original_post = search.usage.reserve, search.usage.finish, search.tools.requests.post
    began = time.monotonic()
    deadline = began+SESSION_SECONDS
    result = {'run': RUN, 'core_revision': CORE, 'status': 'stopped_no_retry', 'synthetic_only': True,
              'provider_connections': 0, 'search_reserve_attempts': 0, 'web_http_requests': 0,
              'search_reserved': False, 'search_settled': False, 'tool_calls': 0,
              'input_text': '', 'response_text': '', 'completed_responses': 0, 'response_turns': [],
              'gemini_usage_events': [], 'source_frames': 0, 'manual_markers': 0,
              'fixture_original_sha256': RAW_SHA, 'fixture_pause_at_ms': PAUSE_AT_MS,
              'fixture_pause_ms': PAUSE_MS, 'semantic_review_required': True,
              'physical_android_verified': False, 'fx_verified': False}
    accepted_hash, sent_hash = hashlib.sha256(), hashlib.sha256()
    sent_bytes = 0
    current_text = ''

    def tick():
        return round((time.monotonic()-began)*1000)

    def check():
        if time.monotonic() >= deadline:
            raise ValueError('diagnostic_deadline')
        if result.get('bridge_sent_ms') is not None and tick()-result['bridge_sent_ms'] >= SPOKEN_WAIT_SECONDS*1000:
            raise ValueError('spoken_response_timeout')
        if call is not None and call.closed.is_set():
            raise ValueError('call_closed')

    class ProbeSocket:
        def __init__(self, socket):
            self.socket = socket

        def __getattr__(self, name):
            return getattr(self.socket, name)

        def send(self, payload):
            nonlocal sent_bytes
            check()
            message = json.loads(payload)
            validate_send(message)
            inner = message.get('realtimeInput', {})
            if any(k in inner for k in ('activityStart','activityEnd','audioStreamEnd')) or 'clientContent' in message:
                result['manual_markers'] += 1
                raise ValueError('manual_marker_forbidden')
            if 'setup' in message:
                value = message['setup']
                result['setup_sha256'] = hashlib.sha256(json.dumps(message,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                result['setup_bytes'] = json_bytes(message)
            responses = message.get('toolResponse', {}).get('functionResponses', [])
            if responses:
                result['tool_response_bytes'] = json_bytes(message)
                if len(responses) != 1 or responses[0].get('name') != search.NAME:
                    raise ValueError('unexpected_tool_response')
                bridge = responses[0].get('response', {})
                result['bridge'] = {k: bridge[k] for k in ('available','reason','checked_on','findings','sources') if k in bridge}
                result['response_turn_target'] = (call.turns if call else 0)+1
            audio_raw = None
            if 'audio' in inner:
                audio_raw = base64.b64decode(inner['audio']['data'],validate=True)
                if sent_bytes+len(audio_raw) > INPUT_SECONDS*32000:
                    raise ValueError('input_fence')
            answer = self.socket.send(payload)
            if responses:
                result['bridge_sent_ms'] = tick()
            if 'audio' in inner:
                sent_hash.update(audio_raw);sent_bytes += len(audio_raw)
            if responses and not responses[0].get('response', {}).get('available'):
                result['search_failure'] = responses[0].get('response', {}).get('reason','search_unavailable')
            return answer

        def recv(self):
            nonlocal current_text
            raw = self.socket.recv()
            message = calls.wire.message(raw)
            if 'toolCall' in message:
                items = message['toolCall'].get('functionCalls', [])
                result['tool_calls'] += len(items)
                result.setdefault('first_tool_call_ms',tick())
                if (result['tool_calls'] != 1 or len(items) != 1 or items[0].get('name') != search.NAME
                        or items[0].get('args') != {'country':'ID','topic':'general'}):
                    raise ValueError('unexpected_tool_call')
            content = message.get('serverContent', {})
            text = content.get('inputTranscription', {}).get('text', '')
            if isinstance(text,str):result['input_text'] = (result['input_text']+text)[:2048]
            text = content.get('outputTranscription', {}).get('text', '')
            if isinstance(text,str):
                current_text = (current_text+text)[:2048]
                result['response_text'] = (result['response_text']+text)[:4096]
            if any(p.get('inlineData') for p in content.get('modelTurn',{}).get('parts',[]) if isinstance(p,dict)):
                result.setdefault('first_audio_ms',tick())
            if content.get('turnComplete') and content.get('interactionStatus') != 'IN_PROGRESS':
                result['completed_responses'] += 1
                result['response_turns'].append({'text':current_text,'complete_ms':tick()});current_text = ''
                result['last_complete_ms'] = tick()
            used = message.get('usageMetadata')
            if isinstance(used,dict) and len(result['gemini_usage_events']) < 8:
                result['gemini_usage_events'].append(usage_summary(used))
            return raw

    def connect_once():
        check();result['provider_connections'] += 1
        if result['provider_connections'] != 1:raise ValueError('no_second_connection')
        return ProbeSocket(original_connect())

    try:
        payload = paused_fixture()
        result['fixture_sha256'] = hashlib.sha256(payload).hexdigest()
        result['fixture_input_ms'] = len(payload)//32
        value = budget.config()
        if db.BACKEND != 'postgres' or not value:raise ValueError('production_policy_required')
        owner = value['allowed_owner']
        if budget.owned(owner, IDENT):
            result['status'] = 'already_attempted_no_retry';return
        if (value.get('reserve') != 250000 or os.environ.get('KILAS_AI_OPENAI_WEB_MODEL') != 'gpt-6-luna'
                or not search.configured()):raise ValueError('configuration_changed')
        if not budget.status(owner)['available']:
            budget.end(owner,IDENT);result['status'] = 'account_unavailable_no_retry';return
        fence = SearchFence(result,check,original_reserve,original_finish,original_post,owner)
        calls.wire.connect = connect_once
        search.usage.reserve, search.usage.finish, search.tools.requests.post = fence.reserve, fence.finish, fence.post
        print('KILAS_AI_CALL_SEARCH_SMOKE '+json.dumps({'run':RUN,'status':'started','deadline_seconds':SESSION_SECONDS,
              'max_call_reservations':1,'max_search_reservations':1,'max_web_requests':1,
              'input_ms':len(payload)//32}),flush=True)
        call = calls.start(owner,IDENT)
        def no_renewal():raise calls.CallError('call_smoke_limit')
        call.fund = no_renewal
        timer = Timer(max(0,deadline-time.monotonic()),lambda:call.stop('call_smoke_limit'))
        timer.daemon = True;timer.start()
        cursor = 0

        def drain():
            nonlocal cursor
            check()
            snapshot = call.snapshot(cursor);cursor = snapshot['next_index']
            for frame in snapshot['frames']:
                if frame['type'] == 'sources' and frame.get('citations'):
                    result['source_frames'] += 1
            if call.output_bytes > 15*48000 or call.turns > 2:raise ValueError('output_fence')

        while call.state == 'CONNECTING':drain();time.sleep(.02)
        clock = time.monotonic();result['input_started_ms'] = tick()
        accepted = 0
        while True:
            drain()
            complete = completion_status(result,call.turns)
            if complete:
                result['status'] = complete;break
            if (call.turns and not result['tool_calls'] and tick()-result.get('last_complete_ms',tick()) > 2000):
                raise ValueError('tool_not_invoked')
            if accepted >= INPUT_SECONDS*32000:
                # Polling keeps the normal client heartbeat; no extra PCM or
                # funding is needed while observing the same pending response.
                time.sleep(.2);continue
            raw = payload[accepted:accepted+6400] if accepted < len(payload) else bytes(6400)
            time.sleep(max(0,clock+(accepted+len(raw))/32000-time.monotonic()))
            drain()
            complete = completion_status(result,call.turns)
            if complete:
                result['status'] = complete;break
            call.accept(call.expected,raw);accepted_hash.update(raw);accepted += len(raw)
    except Exception as error:
        safe = {'diagnostic_deadline','spoken_response_timeout','call_closed','fixture_changed','fixture_invalid',
                'production_policy_required','configuration_changed','no_second_connection','input_fence',
                'output_fence','manual_marker_forbidden','setup_changed','unexpected_tool_call',
                'unexpected_tool_response','tool_response_fence','tool_not_invoked','search_reserve_fence','web_request_fence'}
        result['code'] = str(error) if type(error) is ValueError and str(error) in safe else 'diagnostic_failed'
        if call is None and owner is not None:
            try:budget.end(owner,IDENT)
            except Exception:pass
    finally:
        if timer:timer.cancel()
        if call is not None:
            result.update(duration_ms=tick(),accepted_bytes=call.input_bytes,sent_bytes=sent_bytes,
                          sent_chunks=call.sent_chunks,queued_bytes=call.queued,output_ms=call.output_bytes/48,
                          dispatch_matches_accepted=accepted_hash.digest()==sent_hash.digest(),dispatched_sha256=sent_hash.hexdigest(),
                          search_diagnostics=call.public_search.diagnostic(), turn_timing=call.turn_timing.report())
            before = time.monotonic();calls.end(call.owner,call.ident)
            result['end_ms'] = round((time.monotonic()-before)*1000);result['post_end_frames'] = len(call.frames)
            until = min(began+59, time.monotonic()+4)
            while time.monotonic()<until and (budget.active(call.owner,call.ident,call.capability)
                    or call.public_search.job is not None):time.sleep(.05)
            result['call_settled'] = not budget.active(call.owner,call.ident,call.capability)
            result['search_worker_finished'] = call.public_search.job is None
        calls.wire.connect = original_connect
        search.usage.reserve, search.usage.finish, search.tools.requests.post = original_reserve, original_finish, original_post
        db._discard_cached_connection()
        print('KILAS_AI_CALL_SEARCH_SMOKE '+json.dumps(result,sort_keys=True),flush=True)


if __name__ == '__main__':
    signal.alarm(60)  # Entire QA process, including connection and cleanup.
    run()
