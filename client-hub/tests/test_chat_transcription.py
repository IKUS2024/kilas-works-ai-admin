"""Offline real STT path. Provider/microphone transport is always synthetic or forbidden."""
import io
import json
import os
from pathlib import Path
import wave
from datetime import datetime, timezone, timedelta
import pytest
from werkzeug.datastructures import FileStorage
from test_chat_projects import real, create, save
from test_chat_content_demo import chat
from test_content_projects_prototype import environment
from test_content_release_postgres import postgres
from kilas_ai import transcription as stt, transcription_schema as schema
from kilas_ai import transcription_provider as provider, chat_projects, content_projects
import db


def wav(seconds=1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\0\0' * int(16000 * seconds))
    return out.getvalue()


@pytest.fixture
def audio(real, monkeypatch):
    app, client = real
    monkeypatch.setenv('KILAS_CHAT_TRANSCRIPTION_ENABLED', 'true')
    db.execute('CREATE TABLE kilas_content_releases(name TEXT PRIMARY KEY,checksum TEXT NOT NULL)')
    schema.apply()
    ident = create(client)
    calls = []
    monkeypatch.setattr(provider, 'budget_ready', lambda: True)
    monkeypatch.setattr(provider, 'configured', lambda: True)
    monkeypatch.setattr(provider, 'transcribe', lambda pcm: (calls.append(pcm) or 'Halo, ini teks audio asli.', {'type':'tokens','total_tokens':12}))
    try:
        yield app, client, ident, calls
    finally:
        db.execute('DROP TABLE kilas_chat_transcriptions')
        db.execute('DROP TABLE kilas_content_releases')


def path(pid, key='audio-operation-001', cid=1):
    return f'/kilas-ai/agent/conversations/{cid}/projects/{pid}/transcription/{key}'


def upload(client, pid, key='audio-operation-001', raw=None, mime='audio/wav', consent='yes', cid=1):
    return client.post(path(pid, key, cid), data={'csrf_token':'synthetic-csrf', 'consent':consent, 'audio':(io.BytesIO(wav() if raw is None else raw),'recording.wav',mime)})


def test_default_off_and_budget_lock_prevent_paid_transport(audio, monkeypatch):
    _, client, pid, calls = audio
    monkeypatch.delenv('KILAS_CHAT_TRANSCRIPTION_ENABLED')
    assert upload(client,pid).status_code == 404
    assert b'data-transcription' not in client.get('/kilas-ai/agent?conversation=1').data
    monkeypatch.setenv('KILAS_CHAT_TRANSCRIPTION_ENABLED','true')
    monkeypatch.setattr(provider,'budget_ready',lambda:False)
    response=upload(client,pid)
    assert response.status_code == 503 and response.json['code']=='transcription_budget_unavailable'
    assert not calls and db.query_one('SELECT COUNT(*) AS n FROM kilas_chat_transcriptions')['n']==0
    assert b'data-ready="false"' in client.get('/kilas-ai/agent?conversation=1').data
    assert client.post(path(pid),data={'csrf_token':'synthetic-csrf','action':'cancel'}).status_code==503


def test_real_transcript_review_revision_reload_and_exact_retry(audio):
    _, client, pid, calls = audio
    response = upload(client,pid)
    assert response.status_code==200 and response.json['status']=='COMPLETED'
    assert response.json['text']=='Halo, ini teks audio asli.'
    assert response.headers['Cache-Control']=='private, no-store'
    assert upload(client,pid).json==response.json and len(calls)==1
    assert upload(client,pid,raw=wav(2)).status_code==409
    assert save(client,pid,text='Teks audio yang sudah diedit.').status_code==303
    assert content_projects.script(1,pid,1)['content']=='Teks audio yang sudah diedit.'
    assert b'Halo, ini teks audio asli.' in client.get('/kilas-ai/agent?conversation=1').data
    for name in ('kilas_chat_demo_recordings','kilas_chat_demo_transcripts','kilas_chat_demo_actions'):
        assert db.query_one('SELECT COUNT(*) AS n FROM '+name)['n']==0
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n']==3
    columns=[r['name'] for r in db.query_all('PRAGMA table_info(kilas_chat_transcriptions)')]
    assert not any('audio' in v or 'pcm' in v or 'content' in v for v in columns)


@pytest.mark.parametrize('raw,mime,consent',[(b'not audio','audio/wav','yes'),(wav(),'text/plain','yes'),(wav(),'audio/wav',''),(b'x'*(10*1024*1024+1),'audio/webm','yes'),(wav(181),'audio/wav','yes'),(wav(0),'audio/wav','yes')], ids=['magic','mime','consent','size','duration','empty'])
def test_audio_validation_before_provider(audio, raw, mime, consent):
    _, client, pid, calls=audio
    assert upload(client,pid,raw=raw,mime=mime,consent=consent).status_code in (400,413)
    assert not calls


def test_compressed_mp3_longer_than_pcm_upload_cap_is_validated_locally(audio):
    import subprocess
    from kilas_ai import audio_media
    _,client,pid,calls=audio
    result=subprocess.run([audio_media.imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-f','wav','-i','pipe:0','-f','mp3','pipe:1'],input=wav(130),capture_output=True,timeout=15)
    assert result.returncode==0 and len(result.stdout)<stt.MAX_BYTES
    assert upload(client,pid,raw=result.stdout,mime='audio/mpeg').json['status']=='COMPLETED'
    assert len(calls)==1


def test_csrf_roles_conversation_project_isolation_and_stale_selection(audio):
    _,client,pid,calls=audio
    assert client.post(path(pid),data={}).status_code==400
    foreign=content_projects.create(2,'Foreign','','foreign-project-01')
    assert upload(client,foreign).status_code==404
    assert upload(client,pid,cid=2).status_code==404
    other=create(client,key='next-project-0001',expected=pid,title='Other')
    assert upload(client,pid).status_code==409
    with client.session_transaction() as session: session.update(user_id=2,role='CLIENT_OWNER')
    assert client.get(path(other)).status_code==404
    assert upload(client,other).status_code==404
    with client.session_transaction() as session: session.update(user_id=3,role='KILAS_ADMIN')
    assert upload(client,other).status_code==404
    assert not calls


def test_cancellation_before_start_and_late_result_never_restores_text(audio, monkeypatch):
    _,client,pid,calls=audio
    assert client.post(path(pid),data={'csrf_token':'synthetic-csrf','action':'cancel'}).json['status']=='CANCELLED'
    assert upload(client,pid).json['status']=='CANCELLED' and not calls
    def late(pcm):
        stt.cancel(1,1,pid,'audio-operation-002')
        return 'Late result must be discarded.',{}
    monkeypatch.setattr(provider,'transcribe',late)
    response=upload(client,pid,key='audio-operation-002')
    assert response.json['status']=='CANCELLED' and response.json['text']==''


def test_failure_retry_no_paid_replay_and_attempt_bound(audio, monkeypatch):
    _,client,pid,calls=audio
    def fail(pcm):
        calls.append(pcm);raise provider.TranscriptionError('transcription_failed')
    monkeypatch.setattr(provider,'transcribe',fail)
    assert upload(client,pid).json['status']=='FAILED'
    assert upload(client,pid).json['status']=='FAILED' and len(calls)==1
    assert upload(client,pid,key='audio-operation-002').json['status']=='FAILED'
    assert upload(client,pid,key='audio-operation-003').status_code==429 and len(calls)==2


def test_abandoned_processing_expires_without_replay(audio):
    _,client,pid,calls=audio
    stt.claim(1,1,pid,'audio-operation-001','synthetic',1000)
    db.execute('UPDATE kilas_chat_transcriptions SET created_at=?',((datetime.now(timezone.utc)-timedelta(seconds=91)).isoformat(),))
    assert client.get(path(pid)).json['status']=='FAILED' and not calls


def test_independent_schema_is_idempotent_and_rejects_checksum_change(audio):
    schema.apply();schema.apply()
    db.execute('UPDATE kilas_content_releases SET checksum=? WHERE name=?',('invalid',schema.NAME))
    with pytest.raises(RuntimeError,match='checksum_mismatch'):schema.apply()


def test_provider_adapter_verified_model_bounded_json_no_retry(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-not-a-secret')
    monkeypatch.setattr(provider,'budget_ready',lambda:True)
    calls=[]
    class Response:
        status_code=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield json.dumps({'text':'Synthetic result','usage':{'type':'tokens','total_tokens':1}}).encode()
    def fake(url,**options):calls.append((url,options));return Response()
    monkeypatch.setattr(provider.requests,'post',fake)
    assert provider.transcribe(wav())[0]=='Synthetic result'
    url,options=calls[0]
    assert url=='https://api.openai.com/v1/audio/transcriptions'
    assert options['data']=={'model':'gpt-4o-mini-transcribe','response_format':'json'}
    assert options['files']['file'][0]=='recording.wav' and options['allow_redirects'] is False
    Response.status_code=503
    with pytest.raises(provider.TranscriptionError):provider.transcribe(wav())
    assert len(calls)==2
    Response.status_code=200
    Response.iter_content=lambda self,size:iter([b'x'*65537])
    with pytest.raises(provider.TranscriptionError):provider.transcribe(wav())


def test_real_budget_guard_has_no_runtime_override(monkeypatch):
    monkeypatch.setenv('KILAS_CHAT_TRANSCRIPTION_ENABLED','true')
    monkeypatch.setenv('KILAS_CHAT_TRANSCRIPTION_BUDGET_READY','true')
    # Read actual module source rather than undoing other fixtures' monkeypatches.
    import ast
    tree=ast.parse(open(provider.__file__).read())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='budget_ready')
    scope={};exec(compile(ast.Module(body=[function],type_ignores=[]),provider.__file__,'exec'),scope)
    assert scope['budget_ready']() is False


@pytest.mark.skipif(not os.environ.get('KILAS_CONTENT_POSTGRES_QA_URL'),reason='Disposable loopback PostgreSQL required')
def test_postgres_concurrent_claim_is_single_owner_request_and_cancel(postgres,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    pid=content_projects.create(1,'Synthetic','','stt-pg-project-001')
    chat_projects.choose(1,1,pid,0,'stt-pg-selection-01')
    schema.apply();schema.apply()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:stt.claim(1,1,pid,'stt-pg-operation-01','synthetic-digest',1000),range(4)))
    assert len({r[0] for r in results})==1 and sum(r[1] for r in results)==1
    assert stt.cancel(1,1,pid,'stt-pg-operation-01')['status']=='CANCELLED'
    with pytest.raises(LookupError):stt.owned(2,1,pid,'stt-pg-operation-01')
    assert not postgres.query_one('SELECT consent_at FROM kilas_chat_transcriptions')['consent_at'] is None


@pytest.mark.skipif(not os.environ.get('KILAS_TRANSCRIPTION_BROWSER_QA_DIR'),reason='Optional bounded Chromium QA')
def test_browser_upload_edit_save_reload_and_default_locked_controls(audio,monkeypatch):
    from threading import Thread
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright,expect
    app,client,pid,calls=audio
    from kilas_ai import automation_store
    monkeypatch.setattr(automation_store,'set_timezone',lambda *args:None)
    output=Path(os.environ['KILAS_TRANSCRIPTION_BROWSER_QA_DIR']);output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,app,threaded=True);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or None,headless=True)
            for label,width in [('desktop',1440),('mobile',390)]:
                context=browser.new_context(viewport={'width':width,'height':1000})
                context.add_init_script("window.mediaCalls=0;const deny=()=>{window.mediaCalls++;throw Error('Capture forbidden');};Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:deny,getDisplayMedia:deny}});window.MediaRecorder=deny;")
                context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
                page=context.new_page();page.on('dialog',lambda dialog:dialog.accept());page.goto(origin+'/kilas-ai/agent?conversation=1')
                page.locator('#agent-message').fill('Pesan umum tetap di chat.')
                page.locator('[data-transcription] > summary').click()
                expect(page.locator('[data-stt-send]')).to_be_disabled()
                page.locator('[data-stt-file]').set_input_files({'name':'synthetic.wav','mimeType':'audio/wav','buffer':wav()})
                expect(page.locator('[data-stt-send]')).to_be_disabled()
                page.locator('[data-stt-consent]').check()
                page.locator('[data-stt-send]').click()
                expect(page.locator('[data-stt-text]')).to_have_value('Halo, ini teks audio asli.')
                page.locator('[data-stt-text]').fill('Naskah diperiksa '+label)
                page.locator('[data-stt-use]').click()
                expect(page.get_by_label('Naskah proyek',exact=True)).to_have_value('Naskah diperiksa '+label)
                expect(page.locator('[name=reviewed]')).not_to_be_checked()
                page.locator('[name=reviewed]').check()
                page.get_by_role('button',name='Simpan sebagai versi baru',exact=True).click()
                expect(page.locator('#agent-message')).to_have_value('Pesan umum tetap di chat.')
                page.reload()
                assert page.evaluate('window.mediaCalls')==0
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('[data-transcription] > summary').click()
                page.screenshot(path=str(output/(label+'.png')))
                context.close()
            monkeypatch.setattr(provider,'budget_ready',lambda:False)
            context=browser.new_context(viewport={'width':390,'height':1000})
            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
            page=context.new_page();page.goto(origin+'/kilas-ai/agent?conversation=1')
            expect(page.locator('[data-stt-record]')).to_be_disabled()
            expect(page.locator('[data-stt-file]')).to_be_disabled()
            expect(page.locator('[data-stt-send]')).to_be_disabled()
            context.close();browser.close()
    finally:
        server.shutdown();thread.join(timeout=2)
