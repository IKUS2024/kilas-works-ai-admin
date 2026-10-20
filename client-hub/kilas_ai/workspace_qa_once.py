"""One owner-approved browser QA job; no general model or billing policy change."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
import db
from . import autonomous_store as store, usage

KEY = 'qa-budget-calculator-20261020-v1'
OWNER_ID = 9
MODEL = 'gpt-6-luna'
SERVICE_ID = 'srv-da7ti2psrm7s73dh9i2g'
EXPIRES_AT = datetime(2026, 10, 20, 4, 5, 55, tzinfo=timezone.utc)
MAX_CALLS = 3
MAX_OUTPUT = 16384
MAX_CONTEXT = 1050000
SANDBOX_RESERVE = 8880
TOTAL_BOUND_MICRO_USD = 915681  # Ceiling including cache writes and 10% regional uplift.
PROMPT = ('Buat proyek Python kalkulator anggaran mini dalam ZIP dengan README.md dan main.py. '
          'main.py harus menjalankan assert 100000-35000-15000==50000, menulis output/hasil.txt '
          'berisi sisa=50000, dan mencetak TEST_OK. Lalu jalankan kode Python main.py di sandbox '
          'sekali. Berikan ZIP sumber dan file hasil.')
_active = ContextVar('kilas_qa_once', default=None)


def _approval():
    from . import workspace_execution as execution, chat_models
    prices = chat_models.rates(MODEL, MAX_CONTEXT)
    if (os.environ.get('RENDER_SERVICE_ID') != SERVICE_ID or store.now() >= EXPIRES_AT
            or execution.MAX_SECONDS != 60 or execution.RESERVE_MICRO_USD != SANDBOX_RESERVE
            or prices['input'] > Decimal('.20') or prices['write'] > Decimal('.25')
            or prices['output'] > Decimal('.75')):
        raise ValueError('qa_budget_unavailable')


def request_key(owner, model, text, prepared):
    if owner != OWNER_ID or text.strip() != PROMPT:
        return None
    _approval()
    if model != MODEL or prepared:
        raise ValueError('Model pilihan tidak tersedia. Permintaan tidak dialihkan ke model lain.')
    return KEY


def claim(conn, key):
    if key is None:
        return
    _approval()
    if key != KEY:
        raise ValueError('qa_scope_invalid')
    if db.BACKEND == 'postgres':
        usage._query(conn, 'SELECT pg_advisory_xact_lock(74110601)', ())
    if usage._query(conn, 'SELECT id FROM kilas_agent_steps WHERE idempotency_key=?', (KEY,), one=True):
        raise ValueError('Permintaan ini sudah diterima.')


@contextmanager
def for_job(job, step):
    checkpoint = json.loads(job['checkpoint_json'])
    key = checkpoint.get('qa_budget_key')
    targeted = job['user_id'] == OWNER_ID and checkpoint.get('request_full', '').strip() == PROMPT
    if not key and not targeted:
        yield
        return
    _approval()
    if (not targeted or key != KEY or step['idempotency_key'] != KEY or step['worker'] != 'PROJECT'
            or checkpoint.get('author_model') != MODEL or not checkpoint.get('generate_outputs')
            or job['mode'] != 'ONE_SHOT' or job['max_steps'] != 1 or job['max_attempts'] != 1):
        raise ValueError('qa_scope_invalid')
    token = _active.set({'calls': 0})
    try:
        yield
    finally:
        _active.reset(token)


def before_author(model):
    scope = _active.get()
    if scope is not None:
        _approval()
        if model != MODEL or scope['calls'] >= MAX_CALLS:
            raise ValueError('qa_model_call_limit')


def before_send(model, payload):
    scope = _active.get()
    if scope is None:
        return
    before_author(model)
    if (payload.get('model') != MODEL or type(payload.get('max_output_tokens')) is not int
            or not 0 < payload['max_output_tokens'] <= MAX_OUTPUT
            or any(tool.get('type') != 'function' for tool in payload.get('tools', []))):
        raise ValueError('qa_scope_invalid')
    payload['service_tier'] = 'default'  # Never Fast/Priority for this one job.
    scope['calls'] += 1  # A failed/unknown dispatch consumes its attempt too.
