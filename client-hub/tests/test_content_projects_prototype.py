"""Disposable content-only HTTP regression tests; all external transport is forbidden."""
import ast
import json
import os
import sys
from pathlib import Path

import pytest
from flask import Flask, abort, current_app, request, session
from jinja2 import ChoiceLoader, DictLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import db
import security
from kilas_ai import content_projects as projects, content_schema, content_routes
from kilas_ai import video_routes, audio_routes, agent_routes
from kilas_ai.routes import ai_bp


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv('KILAS_AI_ENABLED', 'true')
    monkeypatch.setenv('KILAS_CONTENT_PROJECTS_ENABLED', 'true')
    monkeypatch.setenv('KILAS_AI_AUTOMATION_ENABLED', 'true')
    monkeypatch.setattr(db, 'BACKEND', 'sqlite')
    monkeypatch.setattr(db, 'SQLITE_PATH', str(tmp_path / 'content-prototype.db'))
    if getattr(db._local, 'conn', None):
        db._local.conn.close()
    db._local.conn = None
    conn = db.get_connection()
    conn.executescript('''
        CREATE TABLE users(id INTEGER PRIMARY KEY, role TEXT NOT NULL);
        INSERT INTO users VALUES(1,'CLIENT_OWNER'),(2,'CLIENT_OWNER'),(3,'KILAS_ADMIN');
        CREATE TABLE kilas_ai_conversations(id INTEGER PRIMARY KEY,user_id INTEGER,title TEXT,archived_at TEXT);
        CREATE TABLE kilas_ai_threads(id INTEGER PRIMARY KEY,user_id INTEGER,title TEXT);
        INSERT INTO kilas_ai_conversations VALUES(1,1,'Brief owner',NULL),(2,2,'Other owner',NULL);
        INSERT INTO kilas_ai_threads VALUES(1,1,'Legacy brief'),(2,2,'Other legacy');
    ''')
    for name in ('0082_kilas_video_sqlite.sql', '0083_kilas_audio_sqlite.sql'):
        conn.executescript((ROOT / 'migrations' / name).read_text())
    for owner in (1,2):
        conn.execute("INSERT INTO kilas_video_projects(id,user_id,title,idea,version,spec_json,operation_key,created_at,updated_at) VALUES (?,?,?,'brief',1,?,?,'2026-01-01','2026-01-01')", (owner,owner,'Plan '+str(owner),json.dumps({'voice_over':'Naskah dari plan'}),'video-key-'+str(owner)))
    for ident, owner, language, mode, raw in ((1,1,'en','translate',b'0000ftypSYNTHETIC'),(2,1,'id','voiceover',b'ID3SYNTHETIC'),(3,2,'ja','translate',b'ID3SYNTHETIC')):
        conn.execute("INSERT INTO kilas_audio_jobs(id,user_id,operation_key,fingerprint,mode,title,source_language,target_language,estimated_seconds,reserved_seconds,status,result_content,created_at,updated_at) VALUES (?,?,?,'synthetic',?,'Synthetic result','id',?,40,0,'COMPLETED',?,'2026-01-01','2026-01-01')", (ident,owner,'audio-key-'+str(ident),mode,language,raw))
    conn.commit()
    content_schema.apply_disposable_sqlite(tmp_path)
    before = dict(conn.execute('SELECT name,sql FROM sqlite_master WHERE type=\'table\'').fetchall())
    import requests
    def forbidden(*args, **kwargs):
        pytest.fail('External transport attempted')
    monkeypatch.setattr(requests.sessions.Session, 'request', forbidden)
    monkeypatch.setattr(audio_routes.service, 'submit', forbidden)
    monkeypatch.setattr(video_routes.director, 'generate', forbidden)
    monkeypatch.setattr(video_routes.video_entitlement, 'state', lambda owner: {'allowed':True})
    monkeypatch.setattr(audio_routes.store, 'balance', lambda owner: {'exempt':False,'available':0,'reserved':0})
    monkeypatch.setattr(audio_routes.personal, 'saved_voices', lambda owner: [])
    monkeypatch.setattr(audio_routes.personal, 'get', lambda owner: None)
    monkeypatch.setattr(audio_routes.personal, 'has_preview', lambda owner: False)
    monkeypatch.setattr(audio_routes.provider, 'configured', lambda: False)
    app = Flask('content-prototype', template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
    app.secret_key = 'synthetic-local-test-only'
    app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
    app.jinja_loader = ChoiceLoader([DictLoader({'base.html':'<!doctype html><html><head><title>{% block title %}{% endblock %}</title></head><body>{% block content %}{% endblock %}</body></html>'}),app.jinja_loader])
    app.jinja_env.globals.update(csrf_token=security.get_csrf_token,ui_t=lambda value, **kwargs:value.format(**kwargs),kilas_content_enabled=projects.enabled)
    app.jinja_env.filters['ui_text'] = lambda value:value
    # Exercise the unchanged application's actual CSRF hook without booting other products.
    tree = ast.parse((ROOT / 'app.py').read_text())
    hook = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name=='_csrf_protect')
    hook.decorator_list = []
    scope = {'request':request,'current_app':current_app,'security':security,'abort':abort}
    exec(compile(ast.Module(body=[hook],type_ignores=[]),'original-app-csrf','exec'),scope)
    app.before_request(scope['_csrf_protect'])
    app.add_url_rule('/login', endpoint='auth.login_page', view_func=lambda:'Login')
    app.register_blueprint(ai_bp)
    app.register_blueprint(audio_routes.audio_bp)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update(user_id=1,role='CLIENT_OWNER',_csrf_token='synthetic-csrf')
    yield app,client
    # Existing schema definitions and seeded outputs must never be rewritten.
    after = dict(conn.execute('SELECT name,sql FROM sqlite_master WHERE type=\'table\'').fetchall())
    assert before == after
    assert bytes(conn.execute('SELECT result_content FROM kilas_audio_jobs WHERE id=1').fetchone()[0]) == b'0000ftypSYNTHETIC'
    conn.close()
    db._local.conn = None


def post(client, path, **values):
    return client.post(path,data={'csrf_token':'synthetic-csrf',**values})


def project(client):
    response = post(client,'/kilas-ai/content-projects',title='Proyek demo',brief='Brief & <script>contoh</script>',operation_key='create-project-001')
    assert response.status_code == 303
    return int(response.location.rsplit('/',1)[1])


def save(client, ident, version=0, text='Naskah <script>aman</script>', operation='script-operation-001'):
    return post(client,f'/kilas-ai/content-projects/{ident}/script',version=version,script=text,operation_key=operation)


def test_default_off_and_no_schema_boot(environment, monkeypatch):
    _,client = environment
    monkeypatch.delenv('KILAS_CONTENT_PROJECTS_ENABLED')
    assert client.get('/kilas-ai/content-projects').status_code == 404
    assert post(client,'/kilas-ai/content-projects',title='x').status_code == 404
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_content_projects')['n']==0
    assert 'if content_enabled() or chat_content_enabled():' in (ROOT/'app.py').read_text()
    assert client.get('/kilas-translator?content_project=999&script_version=1').status_code==200


def test_csrf_for_every_mutation(environment):
    _,client = environment
    ident=project(client)
    for path in ('/kilas-ai/content-projects',f'/kilas-ai/content-projects/{ident}/script',f'/kilas-ai/content-projects/{ident}/links'):
        assert client.post(path,data={}).status_code==400
        assert client.post(path,json={},headers={'X-CSRF-Token':'wrong'}).status_code==400


def test_create_idempotency_and_changed_payload(environment):
    _,client=environment
    ident=project(client)
    assert project(client)==ident
    assert post(client,'/kilas-ai/content-projects',title='Different',brief='',operation_key='create-project-001').status_code==409
    assert len(projects.listing(1))==1


def test_owner_isolation_and_roles(environment):
    _,client=environment
    ident=project(client)
    with client.session_transaction() as sess:
        sess.update(user_id=2,role='CLIENT_OWNER')
    for path in (f'/kilas-ai/content-projects/{ident}',f'/kilas-translator?content_project={ident}&script_version=0',f'/kilas-ai/video?content_project={ident}&script_version=0'):
        assert client.get(path).status_code==404
    assert save(client,ident).status_code==404
    assert post(client,f'/kilas-ai/content-projects/{ident}/links',target='audio:1',script_version=0).status_code==404
    with client.session_transaction() as sess:
        sess.update(user_id=3,role='KILAS_ADMIN')
    assert client.get('/kilas-ai/content-projects').status_code==404
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get('/kilas-ai/content-projects').status_code==302


@pytest.mark.parametrize('target',['video:2','audio:3','conversation:2','thread:2'])
def test_cross_owner_targets_denied(environment,target):
    _,client=environment
    ident=project(client)
    assert post(client,f'/kilas-ai/content-projects/{ident}/links',target=target,script_version=0).status_code==404
    assert projects.links(1,ident)==[]


def test_script_versions_conflicts_and_retry(environment):
    _,client=environment
    ident=project(client)
    assert save(client,ident).status_code==303
    assert save(client,ident).status_code==303
    assert save(client,ident,text='changed').status_code==409
    assert save(client,ident,text='new version',operation='script-operation-002').status_code==409
    assert save(client,ident,version=1,text='new version',operation='script-operation-002').status_code==303
    assert projects.get(1,ident)['script_version']==2
    assert projects.script(1,ident,1)['content']=='Naskah <script>aman</script>'
    assert projects.script(1,ident,2)['content']=='new version'


def test_video_source_snapshot(environment):
    _,client=environment
    ident=project(client)
    response=post(client,f'/kilas-ai/content-projects/{ident}/script',source='video',source_id=1,version=0,operation_key='video-source-key001')
    assert response.status_code==303
    db.execute('UPDATE kilas_video_projects SET version=2,spec_json=? WHERE id=1',(json.dumps({'voice_over':'Changed later'}),))
    saved=projects.script(1,ident,1)
    assert saved['content']=='Naskah dari plan' and saved['source_version']==1
    assert post(client,f'/kilas-ai/content-projects/{ident}/script',source='video',source_id=1,version=0,operation_key='video-source-key001').status_code==303
    assert post(client,f'/kilas-ai/content-projects/{ident}/script',source='video',source_id=2,version=1,operation_key='video-source-key002').status_code==404


def test_manual_links_multiple_languages_and_honest_labels(environment):
    _,client=environment
    ident=project(client);save(client,ident)
    for target in ('video:1','audio:1','audio:2','conversation:1','thread:1'):
        for _ in range(2):
            assert post(client,f'/kilas-ai/content-projects/{ident}/links',target=target,script_version=1).status_code==303
    assert len(projects.links(1,ident))==5
    body=client.get(f'/kilas-ai/content-projects/{ident}').get_data(as_text=True)
    assert 'MP4 hasil dubbing' in body and 'audio MP3' in body
    assert 'Storyboard dan prompt siap' in body and 'tool eksternal' in body
    assert '&lt;script&gt;' in body and '<script>aman</script>' not in body
    assert 'script_version=1' in body and 'Naskah' not in body.split('content_project=')[1].split('"')[0]
    for ident_audio,marker in ((1,b'ftyp'),(2,b'ID3')):
        downloaded=client.get(f'/kilas-translator/jobs/{ident_audio}/result?download=1')
        assert downloaded.status_code==200 and marker in downloaded.data


def test_handoff_actual_forms_no_generation_and_old_version(environment):
    _,client=environment
    ident=project(client);save(client,ident)
    save(client,ident,version=1,text='Newest script',operation='script-operation-002')
    query=f'content_project={ident}&script_version=1'
    body=client.get('/kilas-translator?'+query).get_data(as_text=True)
    assert 'data-active-mode="voiceover"' in body
    assert 'Naskah &lt;script&gt;aman&lt;/script&gt;' in body and 'Newest script' not in body
    assert '<title>Kilas Translator · Kilas Works' in body
    assert '<title>Kilas Translator · Kilas Works<script' not in body
    translation=client.get('/kilas-translator?'+query+'&content_mode=translate').get_data(as_text=True)
    assert 'data-active-mode="translate"' in translation
    video=client.get('/kilas-ai/video?'+query).get_data(as_text=True)
    assert 'Brief &amp; &lt;script&gt;contoh&lt;/script&gt;' in video
    assert 'Kembali ke Proyek demo' in video
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n']==3
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_video_projects')['n']==2
    assert client.get('/kilas-translator?content_project=999&script_version=1').status_code==404
    assert client.get(f'/kilas-translator?content_project={ident}&script_version=999').status_code==404
    assert client.get(f'/kilas-translator?content_project={ident}&script_version=-1').status_code==400


def test_deleted_source_does_not_delete_script_or_link(environment):
    _,client=environment
    ident=project(client)
    post(client,f'/kilas-ai/content-projects/{ident}/script',source='video',source_id=1,version=0,operation_key='video-source-key001')
    post(client,f'/kilas-ai/content-projects/{ident}/links',target='video:1',script_version=1)
    db.execute("UPDATE kilas_video_projects SET deleted_at='2026-01-01' WHERE id=1")
    assert 'Bahan tidak tersedia lagi' in client.get(f'/kilas-ai/content-projects/{ident}').get_data(as_text=True)
    assert projects.script(1,ident,1)['content']=='Naskah dari plan'


def test_schema_disposable_guard(environment):
    with pytest.raises(RuntimeError):
        content_schema.apply_disposable_sqlite(ROOT)


def test_chat_handoff_real_views_and_legacy_fallback(environment, monkeypatch):
    from flask import jsonify
    from kilas_ai import autonomous_runner, agent_attachments, automation_store, work_push, routes
    _,client=environment
    ident=project(client)
    monkeypatch.setattr(autonomous_runner,'enabled',lambda:False)
    monkeypatch.setattr(agent_routes.agent_store,'current_conversation',lambda owner:1)
    monkeypatch.setattr(agent_routes.agent_store,'messages',lambda *args,**kwargs:[])
    monkeypatch.setattr(agent_routes.agent_store,'recent_conversations',lambda owner:[])
    monkeypatch.setattr(agent_attachments,'listing',lambda *args:[])
    monkeypatch.setattr(automation_store,'setting',lambda owner:'Asia/Jakarta')
    monkeypatch.setattr(work_push,'configured',lambda:False)
    monkeypatch.setattr(agent_routes,'render_template',lambda name,**context:jsonify(prefill=context['prefill'],version=context['content_draft']['version'] if context['content_draft'] else None))
    query=f'content_project={ident}&script_version=0'
    response=client.get('/kilas-ai/agent?'+query)
    assert response.status_code==200 and response.json['prefill']=='Brief & <script>contoh</script>'
    assert client.get('/kilas-ai/agent?message=Original').json['prefill']=='Original'
    monkeypatch.setenv('KILAS_AI_AUTOMATION_ENABLED','false')
    monkeypatch.setattr(routes.usage if hasattr(routes,'usage') else projects.usage,'effective_plan',lambda owner:{'plan':'FREE'})
    from kilas_ai import store, attachments
    monkeypatch.setattr(store,'list_threads',lambda owner:[])
    monkeypatch.setattr(projects.usage,'attachment_plan',lambda owner:'FREE')
    monkeypatch.setattr(routes,'render_template',lambda name,**context:jsonify(prefill=context['prefill']))
    response=client.get('/kilas-ai?'+query)
    assert response.status_code==200 and response.json['prefill']=='Brief & <script>contoh</script>'
    body=client.get(f'/kilas-ai/content-projects/{ident}').get_data(as_text=True)
    assert '/kilas-ai?content_project=' in body


def test_relogin_and_flag_rollback_preserve_project(environment, monkeypatch):
    _,client=environment
    ident=project(client);save(client,ident)
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get(f'/kilas-ai/content-projects/{ident}').status_code==302
    with client.session_transaction() as sess:
        sess.update(user_id=1,role='CLIENT_OWNER',_csrf_token='synthetic-csrf')
    assert client.get(f'/kilas-ai/content-projects/{ident}').status_code==200
    monkeypatch.setenv('KILAS_CONTENT_PROJECTS_ENABLED','false')
    assert client.get(f'/kilas-ai/content-projects/{ident}').status_code==404
    assert projects.script(1,ident,1)['content']=='Naskah <script>aman</script>'
    assert client.get('/kilas-translator').status_code==200


def test_incomplete_outputs_and_invalid_versions_not_linked(environment):
    _,client=environment
    ident=project(client)
    db.execute("UPDATE kilas_audio_jobs SET status='PROCESSING' WHERE id=1")
    db.execute('UPDATE kilas_video_projects SET version=0 WHERE id=1')
    for target,version in (('audio:1',0),('video:1',0),('audio:2',999),('audio:2',-1),('unknown:1',0)):
        assert post(client,f'/kilas-ai/content-projects/{ident}/links',target=target,script_version=version).status_code==400
    assert projects.links(1,ident)==[]


@pytest.mark.skipif(not os.environ.get('KILAS_CONTENT_BROWSER_QA_DIR'), reason='Optional local Chromium verification')
def test_browser_project_flow_desktop_mobile(environment):
    from threading import Thread
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright, expect
    app,client=environment
    output=Path(os.environ['KILAS_CONTENT_BROWSER_QA_DIR'])
    output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,app)
    worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None),headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
            page=context.new_page()
            page.goto(origin+'/kilas-ai/content-projects')
            page.get_by_label('Nama proyek').fill('Iklan kopi · contoh lokal')
            page.get_by_label('Brief',exact=True).fill('Video produk kopi untuk Reels, dengan voice-over bahasa Indonesia.')
            page.get_by_role('button',name='Buat proyek',exact=True).click()
            page.get_by_label('Periksa atau tulis naskah').fill('Mulai pagi dengan kopi pilihanmu. Nikmati aroma dan rasa yang hangat.')
            page.get_by_role('button',name='Simpan versi naskah').click()
            page.get_by_label('Bahan tersimpan').select_option('audio:2')
            page.get_by_label('Tautkan ke naskah versi').select_option('1')
            page.get_by_role('button',name='Tautkan bahan').click()
            project_url=page.url
            for name,width in (('desktop',1440),('mobile',390)):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.locator('h1').inner_text()=='Iklan kopi · contoh lokal'
                assert page.get_by_role('link',name='Unduh audio MP3').count()==1
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                page.screenshot(path=str(output/(name+'.png')),full_page=True)
            page.get_by_role('link',name='Buka draft VoiceOver',exact=True).click()
            assert page.get_by_label('Naskah',exact=True).input_value().startswith('Mulai pagi')
            expect(page.locator('#voiceover-panel')).to_be_visible()
            page.get_by_role('link',name='Kembali ke Iklan kopi · contoh lokal').click()
            assert page.url==project_url
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n']==3
            browser.close()
    finally:
        server.shutdown();worker.join(timeout=5)
