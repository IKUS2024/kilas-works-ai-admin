"""One owner-approved browser QA job; no general model or billing policy change."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
import db
from . import autonomous_store as store, usage

OLD_KEY = 'qa-budget-calculator-20261020-v1'
KEY = 'qa-budget-calculator-20261020-retry1'
PREVIOUS_JOB_ID = 31
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
    _prior_undispatched(conn)
    if (usage._query(conn, 'SELECT id FROM kilas_agent_steps WHERE idempotency_key=?', (KEY,), one=True)
            or usage._query(conn, 'SELECT id FROM kilas_agent_events WHERE event_key=?', (KEY+':rearmed',), one=True)):
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
    token = _active.set({'calls': 0, 'job': job, 'step': step})
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


def _prior_undispatched(conn):
    row = usage._query(conn, "SELECT j.user_id,j.status,s.status,s.output_json FROM kilas_agent_jobs j JOIN kilas_agent_steps s ON s.job_id=j.id WHERE j.id=? AND s.idempotency_key=?", (PREVIOUS_JOB_ID, OLD_KEY), one=True)
    expected = {'execution': 'not_run', 'reason': 'execution_quota_exhausted',
                'execution_diagnostic': {'code': 'execution_quota_exhausted', 'phase': 'customer_reservation'}}
    if not row or tuple(row[:3]) != (OWNER_ID, 'FAILED', 'FAILED') or json.loads(row[3]) != expected:
        raise ValueError('qa_rearm_prior_unverified')
    for sql, params in (
        ('SELECT id FROM kilas_ai_usage WHERE operation_key LIKE ?', (OLD_KEY+'%',)),
        ('SELECT id FROM kilas_ai_usage WHERE operation_key=?', ('execution:'+OLD_KEY,)),
        ('SELECT id FROM kilas_workspace_executions WHERE operation_key=?', ('execution:'+OLD_KEY,)),
        ('SELECT id FROM kilas_agent_artifacts WHERE job_id=?', (PREVIOUS_JOB_ID,))):
        if usage._query(conn, sql, params, one=True):
            raise ValueError('qa_rearm_prior_dispatched')


def audit_rearm(conn, job_id, key):
    if key == KEY:
        store.event(conn, job_id, 'QA_REARMED', json.dumps({'previous_job_id': PREVIOUS_JOB_ID,
            'previous_key': OLD_KEY, 'funding': 'SERVER_QA', 'bound_micro_usd': TOTAL_BOUND_MICRO_USD,
            'expires_at': EXPIRES_AT.isoformat()}), KEY+':rearmed', unread=False)


def resource_check(conn, owner):
    from datetime import timedelta
    now = store.now()
    if db.BACKEND == 'postgres':
        usage._query(conn, 'SELECT id FROM users WHERE id=? FOR UPDATE', (owner,), one=True)
    burst = max(1, int(os.environ.get('KILAS_AI_BURST_PER_MINUTE', '30')))
    hourly = max(burst, int(os.environ.get('KILAS_AI_MAX_PER_HOUR', '300')))
    for seconds, ceiling in ((60, burst), (3600, hourly)):
        cutoff = (now-timedelta(seconds=seconds)).isoformat()
        count = usage._query(conn, 'SELECT COUNT(DISTINCT operation_key) FROM kilas_ai_usage WHERE user_id=? AND created_at>=?', (owner, cutoff), one=True)[0]
        count += usage._query(conn, "SELECT COUNT(*) FROM kilas_agent_events e JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE j.user_id=? AND e.kind='QA_MODEL_RESERVED' AND e.created_at>=?", (owner, cutoff), one=True)[0]
        if count >= ceiling:raise usage.UsageLimit('Terlalu banyak permintaan dalam waktu singkat. Coba lagi sebentar.')
    pending = usage._query(conn, "SELECT COUNT(DISTINCT operation_key) FROM kilas_ai_usage WHERE user_id=? AND status='PENDING' AND created_at>=?", (owner, (now-timedelta(minutes=10)).isoformat()), one=True)[0]
    if pending >= 3:raise usage.UsageLimit('Masih ada permintaan yang diproses. Tunggu jawabannya lalu coba lagi.')


def reserve_model(conn, owner, key, tool, profile):
    scope = _active.get()
    if scope is None:return None
    before_author(MODEL)
    if (owner != OWNER_ID or key != KEY+'-tools-'+str(scope['calls']) or tool != 'CHAT'
            or not profile or profile.get('selected_model') != MODEL):
        raise ValueError('qa_scope_invalid')
    resource_check(conn, owner)
    if usage._query(conn, 'SELECT id FROM kilas_agent_events WHERE event_key=?', (key+':reserved',), one=True):
        raise ValueError('duplicate_tool_dispatch')
    store.event(conn, scope['job']['id'], 'QA_MODEL_RESERVED',
        json.dumps({'funding': 'SERVER_QA', 'model': MODEL, 'call': scope['calls']+1,
                    'upper_bound_micro_usd': 302267}), key+':reserved', unread=False)
    return 'SERVER_QA', ('CHAT',)


def finish_model(owner, key, operations, success, provider, model, measured):
    scope = _active.get()
    if scope is None:return False
    if owner != OWNER_ID or not key.startswith(KEY+'-tools-') or operations != ('CHAT',) or model != MODEL:
        raise ValueError('qa_scope_invalid')
    with store.transaction() as conn:
        if not usage._query(conn, 'SELECT id FROM kilas_agent_events WHERE event_key=?', (key+':reserved',), one=True):
            raise ValueError('qa_reservation_missing')
        safe = {k: measured.get(k) for k in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'billing_unknown')}
        store.event(conn, scope['job']['id'], 'QA_MODEL_SETTLED', json.dumps({'funding': 'SERVER_QA',
            'success': bool(success), 'provider': provider, 'model': model, 'usage': safe}), key+':settled', unread=False)
    return True


def run_project(job, step, data):
    from . import workspace_projects, workspace_files, workspace_artifact_transport as transport
    from . import workspace_execution_worker as worker, workspace_qa_execution as execution
    from .agent_workers import Result
    if _active.get() is None:return workspace_projects.run(job, step, data)
    from . import workspace_execution as base
    if not base.capability(job['user_id'])['available']:
        return Result('WAITING_CAPABILITY', 'Sandbox QA belum tersedia.', {'execution':'not_run','reason':'isolated_execution_not_configured'})
    # Reuse validated native authorship without its customer-funded execution stage.
    checkpoint = json.loads(job['checkpoint_json'])
    checkpoint['generate_outputs'] = False
    authored = workspace_projects.run({**job, 'checkpoint_json': json.dumps(checkpoint)}, step,
                                     {'request': 'Buat proyek Python kalkulator anggaran dalam ZIP.'})
    if authored.status != 'SUCCEEDED':return authored
    file = next(item['binary_file'] for item in authored.artifacts if item['binary_file']['filename']=='source-project.zip')
    sources = workspace_files.read_archive(file['content'])
    try:
        prepared, entry = transport.prepare(sources, 'main.py')
        outcome = execution.execute(job, step, prepared, entry)
        result = worker.result(outcome)
        exported = transport.collect(outcome['outputs'])
        valid = bool(exported and any(f['filename']=='hasil.txt' and f['content'].strip()==b'sisa=50000' for f in exported[0]))
        success = result.status == 'SUCCEEDED' and outcome['cleanup_confirmed'] and 'TEST_OK' in outcome['stdout'].splitlines() and valid
        metadata = {**result.output, 'funding': 'SERVER_QA', 'qa_rearm_of': PREVIOUS_JOB_ID}
        file['validation'] = metadata;file['extracted_text'] = json.dumps(metadata)
        result.artifacts = [authored.artifacts[0]] + result.artifacts
        result.status = 'SUCCEEDED' if success else 'FAILED'
        result.summary = 'File proyek tersimpan. Python selesai.' if success else 'File proyek tersimpan. Hasil QA belum terverifikasi.'
        result.output = {'project_ready': True, 'generated_file_count': 1 if valid else 0, 'validation': metadata}
        return result
    except Exception as error:
        return Result('FAILED', 'File proyek tersimpan. Hasil QA belum terverifikasi; permintaan tidak diulang.',
                      {'project_ready': True, 'execution': 'not_verified', 'reason': 'qa_execution_failed'}, [authored.artifacts[0]])
