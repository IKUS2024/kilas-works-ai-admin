"""Explicit V1 capabilities; proposals never grant execution authority."""
import json
import os
import re
from dataclasses import dataclass, field


@dataclass
class Result:
    status: str
    summary: str
    output: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    verified: bool = False
    delay: int = 3600


# No external writer is registered in V1. Approval does not manufacture a capability.
FIELDS = {
    ('AI_TEXT', 'write'): {'prompt'}, ('WEB', 'search'): {'query'},
    ('WATCH', 'observe'): {'query', 'operator', 'threshold'},
    ('MARKET', 'observe'): {'symbol', 'timeframe', 'operator', 'threshold'},
    ('FILE', 'create'): {'name', 'format', 'content'},
    ('CODE', 'inspect'): {'repo', 'paths'}, ('CODE', 'patch'): {'repo', 'patch'},
    ('CODE', 'test'): {'repo'}, ('CODE', 'diff'): {'repo'},
    ('EXTERNAL', 'push'): {'repo'}, ('EXTERNAL', 'merge'): {'repo'},
    ('EXTERNAL', 'deploy'): {'target'}, ('EXTERNAL', 'publish'): {'target', 'content'},
    ('UNAVAILABLE', 'request'): {'capability'},
}


def sensitive(worker, action):
    return worker == 'EXTERNAL'


def market_request(text):
    return bool(re.search(r'(?i)\b(?:XAUUSD|XAGUSD|BTCUSD|ETHUSD|OHLC|candles?|forex|saham|trading|market signal|sinyal|indikator teknikal|setup valid)\b', text or ''))


def validate_step(step):
    fields = FIELDS.get((step.get('worker'), step.get('action')))
    data = step.get('input')
    if fields is None or not isinstance(data, dict) or set(data) != fields:
        raise ValueError('unsupported_step_input')
    if len(json.dumps(data, allow_nan=False).encode()) > 18000:
        raise ValueError('input_too_large')
    if any(not isinstance(v, (str, int, float, list)) or isinstance(v, bool) for v in data.values()):
        raise ValueError('invalid_input')
    if step['worker'] in ('WATCH', 'MARKET'):
        if data['operator'] not in ('lt', 'gt', 'change') or (data['operator'] != 'change' and not isinstance(data['threshold'], (int, float))):
            raise ValueError('invalid_condition')
        if step['worker'] == 'WATCH' and market_request(str(data['query'])):
            raise ValueError('market_requires_provider')
    if step['worker'] == 'CODE' and step['action'] == 'inspect':
        if not isinstance(data['paths'], list) or not 1 <= len(data['paths']) <= 8 or any(not isinstance(p, str) for p in data['paths']):
            raise ValueError('invalid_paths')


def capabilities():
    from . import market_worker, code_worker
    return [{'worker': worker, 'action': action, 'input_fields': sorted(fields),
             'available': worker not in ('EXTERNAL', 'UNAVAILABLE') and (worker != 'MARKET' or market_worker.provider is not None) and (worker != 'CODE' or bool(os.environ.get('KILAS_AI_CODE_REPOSITORIES'))),
             'repository_aliases': sorted(code_worker.repositories()) if worker == 'CODE' else [],
             'requires_approval': sensitive(worker, action)} for (worker, action), fields in FIELDS.items()]


def execute(job, step):
    data = json.loads(step['input_json'])
    validate_step({'worker': step['worker'], 'action': step['action'], 'input': data})
    if step['worker'] in ('EXTERNAL', 'UNAVAILABLE'):
        if step['worker'] == 'UNAVAILABLE' and data['capability'] == 'market_data_provider':
            return Result('WAITING_CAPABILITY', 'Market data provider is not configured.', {'reason': 'provider_not_configured'})
        return Result('WAITING_CAPABILITY', 'Kemampuan ini belum tersedia. Tidak ada tindakan eksternal dijalankan.', {'reason': 'adapter_not_configured'})
    if step['worker'] == 'CODE':
        from .code_worker import run
    elif step['worker'] == 'MARKET':
        from .market_worker import run
    else:
        from .content_worker import run
    return run(job, step, data)
