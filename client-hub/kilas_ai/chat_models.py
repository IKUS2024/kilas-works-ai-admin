"""Exact Chat model catalog, read-only account access checks and owner preferences.

No inference, credential writes or provider fallback. Public model documentation
is deliberately insufficient: a configured account must pass the Models API.
"""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
import threading
from time import monotonic
from concurrent.futures import ThreadPoolExecutor
import requests

DEFAULT = 'gpt-6.1-sol'
VERIFIED_ON = '2026-10-17'
# Standard first-party API rates, USD per million tokens. No provider tool is enabled here.
CATALOG = {
    'gpt-6-luna': ('openai', 'GPT-6 Luna', '.10', '.50', '.01'),
    'gpt-6.1-sol': ('openai', 'GPT-6.1 Sol', '2', '10', '.10'),
    'gpt-6-astra': ('openai', 'GPT-6 Astra', '10', '50', '1'),
    'claude-haiku-5-5': ('anthropic', 'Claude Haiku 5.5', '.10', '.50', '.01'),
    'claude-sonnet-5-5': ('anthropic', 'Claude Sonnet 5.5', '2', '10', '.10'),
    'claude-opus-5-5': ('anthropic', 'Claude Opus 5.5', '4', '20', '.20'),
    'claude-fable-5-1': ('anthropic', 'Claude Fable 5.1', '10', '50', '.25'),
    'gemini-3.5-flash-lite': ('google', 'Gemini 3.5 Flash-Lite', '.30', '2.50', '.03'),
    'gemini-3.8-flash': ('google', 'Gemini 3.8 Flash', '.75', '3.75', '.075'),
    'gemini-4-argon': ('google', 'Gemini 4 Argon', '2', '10', '.10'),
}
KEYS = {'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY', 'google': 'GEMINI_API_KEY'}
_lock = threading.Lock()
_cache = {}
_TTL = 600

class SelectionError(ValueError):
    pass


def spec(model):
    if not isinstance(model,str) or model not in CATALOG:
        raise SelectionError('Model tidak valid. Pilih model dari daftar.')
    p, name, *_ = CATALOG[model]
    return {'id': model, 'provider': p, 'name': name}


def rates(model, input_tokens=0, now=None):
    _, _, inp, out, cached = CATALOG[model]
    now = now or datetime.now(timezone.utc)
    if model.startswith('gpt-6') and input_tokens > 272000:
        inp, out, cached = str(Decimal(inp)*2), str(Decimal(out)*Decimal('1.5')), str(Decimal(cached)*2)
    if model == 'claude-haiku-5-5' and input_tokens > 100000:
        inp, out, cached = '.50', '2.50', '.05'
    if model == 'gemini-4-argon' and now.date().isoformat() >= '2026-12-01':
        inp, out, cached = '4', '20', '.20'
    if model == 'gemini-3.8-flash' and now.date().isoformat() >= '2027-01-01':
        inp, out, cached = '1.50', '7.50', '.15'
    return {'input': Decimal(inp), 'output': Decimal(out), 'cached': Decimal(cached),
            'write': Decimal(inp)*Decimal('1.25')}


def check(model):
    item = spec(model)
    provider = item['provider']
    key = os.environ.get(KEYS[provider], '').strip()
    fingerprint = hashlib.sha256(key.encode()).digest()
    with _lock:
        prior = _cache.get(model)
        if prior and prior['fingerprint'] == fingerprint and monotonic()-prior['at'] < (_TTL if prior['available'] else 30):
            return {k:v for k,v in prior.items() if k not in ('at','fingerprint')}
    result = {**item, 'available': False, 'status': 'not_configured', 'images': False}
    if key:
        try:
            if provider == 'openai':
                url = 'https://api.openai.com/v1/models/'+model
                headers = {'Authorization': 'Bearer '+key}
                project = os.environ.get('OPENAI_PROJECT_ID','').strip()
                if project: headers['OpenAI-Project'] = project
            elif provider == 'anthropic':
                url = 'https://api.anthropic.com/v1/models/'+model
                headers = {'x-api-key':key, 'anthropic-version':'2023-06-01'}
            else:
                url = 'https://generativelanguage.googleapis.com/v1beta/models/'+model
                headers = {'x-goog-api-key':key}
            response = requests.get(url, headers=headers, timeout=(3,5))
            if response.status_code == 200:
                data = response.json()
                returned = data.get('name','').removeprefix('models/') if provider == 'google' else data.get('id')
                compatible = returned == model or bool(isinstance(returned,str) and re.fullmatch(re.escape(model)+r'-(?:20\d\d-\d\d-\d\d|\d{3})',returned))
                methods = data.get('supportedGenerationMethods', [])
                if compatible and (provider != 'google' or 'generateContent' in methods):
                    images = (data.get('capabilities',{}).get('image_input',{}).get('supported',False)
                              if provider == 'anthropic' else True)
                    result.update(available=True, status='verified', images=bool(images))
                else: result['status'] = 'unsupported'
            else:
                result['status'] = 'access_unavailable' if response.status_code in (401,403,404) else 'check_unavailable'
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            result['status'] = 'check_unavailable'
    result['checked_on'] = datetime.now(timezone.utc).isoformat()
    with _lock:
        _cache[model] = {**result, 'fingerprint':fingerprint, 'at':monotonic()}
    return result


def catalog():
    with ThreadPoolExecutor(max_workers=5,thread_name_prefix='chat-access') as pool:
        items = list(pool.map(check,CATALOG))
    default = next((m['id'] for m in items if m['id']==DEFAULT and m['available']), None)
    default = default or next((m['id'] for m in items if m['available']), None)
    return {'models':items, 'default':default, 'pricing_verified_on':VERIFIED_ON,
            'notice':'Pilihan berlaku untuk jawaban Chat. Search, gambar dan Work adalah layanan Kilas terpisah. Kode tidak dijalankan di Chat.'}


def warmup():
    def run():
        result = catalog()
        print('KILAS_CHAT_MODELS '+json.dumps({m['id']:m['status'] for m in result['models']},separators=(',',':')),flush=True)
    threading.Thread(target=run, name='kilas-chat-model-access', daemon=True).start()


def owned(user_id, surface, ident):
    from . import store, agent_store
    if surface not in ('thread','conversation') or type(ident) is not int or ident <= 0:
        raise SelectionError('Percakapan tidak valid.')
    row = store.thread(user_id, ident) if surface=='thread' else agent_store.conversation(user_id, ident)
    if not row:
        raise SelectionError('Percakapan tidak ditemukan.')


def preference(user_id, surface, ident):
    import db
    owned(user_id,surface,ident)
    row = db.query_one('SELECT model FROM kilas_ai_chat_model_selections WHERE user_id=? AND surface=? AND conversation_id=?',
                       (user_id,surface,ident))
    return row['model'] if row else None


def choose(user_id, surface, ident, model=None):
    import db
    owned(user_id,surface,ident)
    model = model or preference(user_id,surface,ident) or catalog()['default']
    if not model or not check(model)['available']:
        raise SelectionError('Model ini belum tersedia untuk akun layanan. Pilih model lain yang tersedia.')
    db.execute('INSERT INTO kilas_ai_chat_model_selections(user_id,surface,conversation_id,model) VALUES (?,?,?,?) '
               'ON CONFLICT(user_id,surface,conversation_id) DO UPDATE SET model=excluded.model',
               (user_id,surface,ident,model))
    return model


def bind(context, model):
    # Only routes pass an allowlisted, account-checked model. Never put this instruction in user text.
    spec(model)
    context.selected_model = model
    return context


def validate_messages(model, messages):
    item = check(model)
    if not item['available']:
        raise SelectionError('Model pilihan tidak tersedia. Permintaan tidak dialihkan ke model lain.')
    for message in messages:
        for block in message['content'] if isinstance(message['content'],list) else []:
            if block.get('type') == 'image_url' and not item['images']:
                raise SelectionError('Model ini belum mendukung gambar pada akun layanan. Pilih model lain atau hapus lampiran gambar.')
            if block.get('type') not in ('text','image_url'):
                raise SelectionError('Lampiran ini belum kompatibel dengan model pilihan.')


def estimate(model, input_tokens, output_tokens, cached_tokens=0, write_tokens=0, now=None):
    prices = rates(model, input_tokens, now)
    cached = max(0,min(int(input_tokens),int(cached_tokens)))
    writes = max(0,min(int(input_tokens)-cached,int(write_tokens)))
    return ((Decimal(int(input_tokens)-cached-writes)*prices['input'] + Decimal(cached)*prices['cached']
             + Decimal(writes)*prices['write'] + Decimal(int(output_tokens))*prices['output'])/Decimal(1000000))


def request_model(user_id, surface, ident, value=None):
    # Old clients without a selection keep their established route. New UI always sends its explicit choice.
    model=value or preference(user_id,surface,ident)
    return choose(user_id,surface,ident,model) if model else None
