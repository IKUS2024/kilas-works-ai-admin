"""Owner-only one-use QA, offline transports and disposable databases only."""
import io
import json
import os
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from flask import Flask, abort, request
from jinja2 import ChoiceLoader, DictLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import db
import security
from kilas_ai import live_qa_budget as budget,live_qa_schema as schema,live_qa_provider as provider,live_assist as live,live_assist_routes
from kilas_ai.routes import ai_bp
from test_content_release_postgres import postgres
from test_live_assist import fixture_audio

TOKEN = 'synthetic-session-token-00000001'


@pytest.fixture
def qa(tmp_path,monkeypatch):
    monkeypatch.setenv('KILAS_AI_ENABLED','true')
    monkeypatch.setenv('KILAS_LIVE_ASSIST_QA_ENABLED','true')
    monkeypatch.setenv('KILAS_LIVE_ASSIST_ENABLED','false')
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-local-only')
    monkeypatch.setattr(db,'BACKEND','sqlite')
    monkeypatch.setattr(db,'SQLITE_PATH',str(tmp_path/'qa.db'))
    prior=getattr(db._local,'conn',None);db._local.conn=None
    conn=sqlite3.connect(db.SQLITE_PATH)
    conn.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT UNIQUE,role TEXT);INSERT INTO users VALUES(1,'irvankarnavi@gmail.com','CLIENT_OWNER'),(2,'synthetic-other@example.invalid','CLIENT_OWNER'),(3,'synthetic-admin@example.invalid','KILAS_ADMIN');CREATE TABLE protected_sentinel(id INTEGER PRIMARY KEY,value TEXT);INSERT INTO protected_sentinel VALUES(1,'unchanged');")
    conn.close();schema.apply()
    # Synthetic deterministic clock within the approved pricing day only.
    now=[budget.PRICE_START_MS+1000]
    monkeypatch.setattr(budget,'_now',lambda conn:now[0])
    import requests
    monkeypatch.setattr(requests.sessions.Session,'request',lambda *a,**kw:pytest.fail('Real provider transport forbidden'))
    yield now
    assert db.query_one('SELECT value FROM protected_sentinel WHERE id=1')['value']=='unchanged'
    assert not db.query_one("SELECT name FROM sqlite_master WHERE name IN ('kilas_ai_usage','kilas_audio_balances','kilas_ai_invoices')")
    if getattr(db._local,'conn',None):db._local.conn.close()
    db._local.conn=prior
    with live._lock:
        for value in live._sessions.values():value['timer'].cancel()
        live._sessions.clear()


def reserve(kind='STT',key='1',model=None):
    return budget.dispatch(1,TOKEN,kind,key,model or (budget.STT_MODEL if kind=='STT' else budget.TEXT_MODEL))


def test_default_off_owner_allowlist_and_separate_general_guard(qa,monkeypatch):
    assert budget.ready(1,for_start=True) and not budget.allowed(2) and not budget.allowed(3)
    assert not live.stt.budget_ready()
    assert not live.ready() and live.ready(1) and not live.ready(2)
    monkeypatch.setenv('KILAS_LIVE_ASSIST_ENABLED','true')
    assert not live.enabled(2)  # Global flag cannot widen owner QA.
    monkeypatch.delenv('KILAS_LIVE_ASSIST_QA_ENABLED')
    assert not budget.ready(1)
    with pytest.raises(budget.BudgetError):budget.claim(1,TOKEN)


def test_one_session_remains_consumed_after_stop_restart_and_second_worker(qa):
    budget.claim(1,TOKEN)
    assert not budget.ready(1,for_start=True)
    for token in (TOKEN,'synthetic-second-session-00000002'):
        with pytest.raises(budget.BudgetError,match='already_used'):budget.claim(1,token)
    budget.close(1,TOKEN)
    with pytest.raises(budget.BudgetError,match='expired'):reserve()
    with pytest.raises(budget.BudgetError,match='already_used'):budget.claim(1,TOKEN)
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_live_qa_grants')['n']==1


def test_worst_case_cap_no_refunds_no_replay_and_unknown_model(qa):
    budget.claim(1,TOKEN)
    with pytest.raises(budget.BudgetError,match='unknown_pricing'):reserve(model='unpriced-model')
    with pytest.raises(budget.BudgetError,match='source_required'):reserve('TRANSLATE')
    for seq in range(1,4):
        reserve(key=str(seq));budget.finish(1,TOKEN,'STT',str(seq),True)
        reserve('TRANSLATE',str(seq));budget.finish(1,TOKEN,'TRANSLATE',str(seq),True)
    row=db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')
    assert row['reserved_microusd']==3*(budget.STT_RESERVE+budget.TEXT_RESERVE)==98268
    with pytest.raises(budget.BudgetError,match='budget_exhausted'):reserve(key='4')
    with pytest.raises(budget.BudgetError,match='budget_exhausted'):reserve('REPLY','explicit-draft-000001')
    with pytest.raises(budget.BudgetError,match='no_replay'):reserve()
    budget.finish(1,TOKEN,'STT','1',False)
    assert db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==98268


@pytest.mark.parametrize('offset',[120000,120001,100000000])
def test_absolute_server_expiry_and_price_manifest_expiry(qa,offset):
    budget.claim(1,TOKEN);qa[0]+=offset
    with pytest.raises(budget.BudgetError,match='expired'):reserve()
    assert db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==0


def test_cross_owner_session_and_store_fail_closed(qa,monkeypatch):
    budget.claim(1,TOKEN)
    with pytest.raises(budget.BudgetError,match='authorized'):budget.dispatch(2,TOKEN,'STT','1',budget.STT_MODEL)
    with pytest.raises(budget.BudgetError,match='authorized'):budget.close(2,TOKEN)
    with pytest.raises(budget.BudgetError,match='authorized'):budget.dispatch(1,'synthetic-wrong-session-0000001','STT','1',budget.STT_MODEL)
    monkeypatch.setattr(budget.usage,'_connect',lambda:(_ for _ in ()).throw(RuntimeError('synthetic unavailable')))
    assert not budget.ready(1)
    with pytest.raises(budget.BudgetError,match='store_unavailable'):reserve()


def test_parallel_sqlite_requests_share_cap_and_duplicate_fence(qa):
    budget.claim(1,TOKEN);barrier=threading.Barrier(8)
    def call(seq):
        barrier.wait()
        try:reserve(key=str(seq));return 'ok'
        except budget.BudgetError as error:return str(error)
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(call,range(1,9)))
    assert results.count('ok')==3
    assert db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==90000


class Response:
    status_code=200
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield json.dumps(self.data).encode()


def test_provider_reserves_before_network_bounds_models_and_no_retry(qa,monkeypatch):
    budget.claim(1,TOKEN);calls=[]
    def send(url,**kwargs):
        calls.append((url,kwargs))
        # Database marker and full cost must have committed before any dispatch.
        row=db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')
        assert row['reserved_microusd']>=budget.STT_RESERVE
        if url.endswith('/transcriptions'):return Response({'text':'Non-sensitive example question.'})
        return Response({'choices':[{'finish_reason':'stop','message':{'content':'{"text":"Contoh terjemahan."}'}}],'service_tier':'default'})
    monkeypatch.setattr(provider.requests,'post',send)
    original=provider.transcribe(1,TOKEN,1,fixture_audio())
    assert provider.text(1,TOKEN,'TRANSLATE','1','Translate faithfully. Return JSON with text.',original)=='Contoh terjemahan.'
    payload=calls[-1][1]['json']
    assert payload['model']=='gpt-6-luna' and payload['service_tier']=='default' and payload['max_completion_tokens']==512 and not payload['store']
    assert calls[0][1]['data']['model']=='gpt-4o-mini-transcribe'
    for _,options in calls:assert options['allow_redirects'] is False and options['timeout']==(5,15)
    with pytest.raises(budget.BudgetError):provider.transcribe(1,TOKEN,1,fixture_audio())
    with pytest.raises(budget.BudgetError,match='input_limit'):provider.text(1,TOKEN,'REPLY','reply-key-000001','Return JSON with text.','😀'*5000)
    assert len(calls)==2


def test_timeout_keeps_full_reservation_and_stop_blocks_followup(qa,monkeypatch):
    import requests
    budget.claim(1,TOKEN);calls=[]
    def fail(*args,**kw):calls.append(1);raise requests.Timeout()
    monkeypatch.setattr(provider.requests,'post',fail)
    with pytest.raises(budget.BudgetError,match='provider_failed'):provider.transcribe(1,TOKEN,1,fixture_audio())
    assert db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==30000
    assert db.query_one('SELECT status FROM kilas_live_qa_operations')['status']=='UNCERTAIN'
    with pytest.raises(budget.BudgetError,match='no_replay'):provider.transcribe(1,TOKEN,1,fixture_audio())
    budget.close(1,TOKEN)
    with pytest.raises(budget.BudgetError,match='expired'):provider.transcribe(1,TOKEN,2,fixture_audio())
    assert calls==[1]


def test_actual_qa_adapter_pipeline_editable_reply_and_stop_no_general_unlock(qa,monkeypatch):
    from werkzeug.datastructures import FileStorage
    calls=[]
    def send(url,**kwargs):
        calls.append(url)
        if url.endswith('/transcriptions'):return Response({'text':'Tell me about your real experience.'})
        instruction=kwargs['json']['messages'][0]['content']
        text='Ceritakan pengalaman nyata Anda.' if instruction.startswith('Translate') else 'Saya belajar desain selama enam bulan.'
        return Response({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'text':text})}}],'service_tier':'default'})
    monkeypatch.setattr(provider.requests,'post',send)
    token=live.create(1,'call','id',True,True)
    row=live.chunk(1,token,1,FileStorage(stream=io.BytesIO(fixture_audio()),filename='synthetic.wav',content_type='audio/wav'))
    assert row['original']=='Tell me about your real experience.' and row['translated']=='Ceritakan pengalaman nyata Anda.'
    assert live.reply(1,token,'explicit-reply-key-00001','Saya belajar desain selama enam bulan.')=='Saya belajar desain selama enam bulan.'
    assert len(calls)==3
    assert db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==35512
    assert not live.stt.budget_ready()
    live.stop(1,token)
    assert not live._sessions
    with pytest.raises(live.LiveError):live.create(1,'call','id',True,True)


def test_other_worker_stop_fences_late_stt_and_prevents_translation(qa,monkeypatch):
    budget.claim(1,TOKEN);calls=[]
    def send(url,**kwargs):
        calls.append(url);budget.close(1,TOKEN)
        return Response({'text':'Late private text must not escape.'})
    monkeypatch.setattr(provider.requests,'post',send)
    with pytest.raises(budget.BudgetError):provider.transcribe(1,TOKEN,1,fixture_audio())
    assert len(calls)==1
    assert db.query_one('SELECT status FROM kilas_live_qa_operations')['status']=='UNCERTAIN'
    with pytest.raises(budget.BudgetError,match='expired'):provider.text(1,TOKEN,'TRANSLATE','1','Return JSON with text.','Synthetic')
    assert len(calls)==1


def test_missing_key_bad_audio_and_three_explicit_reply_limit(qa,monkeypatch):
    budget.claim(1,TOKEN)
    with pytest.raises(budget.BudgetError):provider.transcribe(1,TOKEN,1,b'bad')
    monkeypatch.delenv('OPENAI_API_KEY')
    with pytest.raises(budget.BudgetError,match='unavailable'):provider.transcribe(1,TOKEN,1,fixture_audio())
    assert db.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==0
    reserve();budget.finish(1,TOKEN,'STT','1',True)
    reserve('TRANSLATE');budget.finish(1,TOKEN,'TRANSLATE','1',True)
    for seq in range(3):reserve('REPLY','explicit-reply-key-'+str(seq))
    with pytest.raises(budget.BudgetError,match='operation_limit'):reserve('REPLY','explicit-reply-key-4')


def test_schema_checksum_idempotent_isolated_and_no_audio_text_fields(qa):
    schema.apply()
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_live_qa_releases')['n']==1
    columns={row['name'] for row in db.query_all('PRAGMA table_info(kilas_live_qa_operations)')}
    assert not {'audio','text','caption','facts','reply','api_key'} & columns
    db.execute("UPDATE kilas_live_qa_releases SET checksum='synthetic-wrong'")
    with pytest.raises(RuntimeError,match='checksum_mismatch'):schema.apply()


def test_http_owner_only_consent_general_transcription_locked_and_shared_stop(qa,monkeypatch):
    app=Flask('owner-qa',template_folder=str(ROOT/'templates'),static_folder=str(ROOT/'static'))
    app.secret_key='synthetic-local-only'
    app.jinja_loader=ChoiceLoader([DictLoader({'base.html':'{% block content %}{% endblock %}'}),app.jinja_loader])
    app.jinja_env.globals.update(csrf_token=security.get_csrf_token)
    @app.before_request
    def csrf():
        if request.method=='POST' and not security.validate_csrf_token(request.form.get('csrf_token')):abort(400)
    app.add_url_rule('/login',endpoint='auth.login_page',view_func=lambda:'Login')
    app.register_blueprint(ai_bp)
    client=app.test_client()
    def owner(ident):
        with client.session_transaction() as sess:sess.update(user_id=ident,_csrf_token='synthetic-csrf')
    def post(op,**values):return client.post('/kilas-ai/live-assist/'+op,data={'csrf_token':'synthetic-csrf',**values})
    owner(2);assert client.get('/kilas-ai/live-assist').status_code==404
    owner(3);assert client.get('/kilas-ai/live-assist').status_code==404
    owner(1);body=client.get('/kilas-ai/live-assist');assert body.status_code==200 and b'live-sample-consent' in body.data
    assert b'data-provider-ready="true"' in body.data
    assert client.post('/kilas-ai/live-assist/start',data={}).status_code==400
    assert post('start',mode='call',target='id',consent='yes').status_code==409
    token=post('start',mode='call',target='id',consent='yes',sample_consent='yes').json['session_id']
    # Worker restart/affinity failure never enables a second session.
    with live._lock:
        live._sessions[token]['timer'].cancel();live._sessions.clear()
    assert post('start',mode='call',target='id',consent='yes',sample_consent='yes').status_code==409
    assert post('stop',session_id=token).status_code==200
    assert db.query_one('SELECT status FROM kilas_live_qa_grants')['status']=='CLOSED'
    assert not live.stt.budget_ready()


@pytest.mark.skipif(not os.environ.get('KILAS_CONTENT_POSTGRES_QA_URL'),reason='Disposable loopback PostgreSQL required')
def test_postgres_cross_worker_claim_cost_races_and_stop(postgres,monkeypatch):
    postgres.execute('ALTER TABLE users ADD COLUMN email TEXT')
    postgres.execute('UPDATE users SET email=? WHERE id=1',(budget.OWNER_EMAIL,))
    postgres.execute('UPDATE users SET email=? WHERE id=2',('synthetic-other@example.invalid',))
    monkeypatch.setenv('KILAS_LIVE_ASSIST_QA_ENABLED','true')
    monkeypatch.setattr(budget,'_now',lambda conn:budget.PRICE_START_MS+1000)
    schema.apply();schema.apply()
    barrier=threading.Barrier(4)
    def claim(seq):
        barrier.wait()
        try:budget.claim(1,TOKEN+str(seq));return seq
        except budget.BudgetError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(claim,range(4)))
    winners=[r for r in results if r is not None];assert len(winners)==1
    token=TOKEN+str(winners[0]);barrier=threading.Barrier(8)
    def dispatch(seq):
        barrier.wait()
        try:budget.dispatch(1,token,'STT',str(seq),budget.STT_MODEL);return 'ok'
        except budget.BudgetError:return 'blocked'
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(dispatch,range(1,9)))
    assert results.count('ok')==3
    assert postgres.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==90000
    assert postgres.query_one('SELECT COUNT(*) AS n FROM kilas_live_qa_operations')['n']==3
    budget.close(1,token)
    with pytest.raises(budget.BudgetError,match='expired'):budget.dispatch(1,token,'STT','9',budget.STT_MODEL)


@pytest.mark.skipif(not os.environ.get('KILAS_CONTENT_POSTGRES_QA_URL'),reason='Disposable loopback PostgreSQL required')
def test_postgres_concurrent_same_operation_is_never_dispatched_twice(postgres,monkeypatch):
    postgres.execute('ALTER TABLE users ADD COLUMN email TEXT')
    postgres.execute('UPDATE users SET email=? WHERE id=1',(budget.OWNER_EMAIL,))
    monkeypatch.setenv('KILAS_LIVE_ASSIST_QA_ENABLED','true')
    monkeypatch.setattr(budget,'_now',lambda conn:budget.PRICE_START_MS+1000)
    schema.apply();budget.claim(1,TOKEN);barrier=threading.Barrier(8)
    def dispatch(_):
        barrier.wait()
        try:reserve();return 'ok'
        except budget.BudgetError as error:return str(error)
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(dispatch,range(8)))
    assert results.count('ok')==1 and results.count('qa_no_replay')==7
    assert postgres.query_one('SELECT reserved_microusd FROM kilas_live_qa_grants')['reserved_microusd']==30000
