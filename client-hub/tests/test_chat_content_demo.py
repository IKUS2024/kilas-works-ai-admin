"""Owner-scoped mock flow in the actual chat shell, with provider/media hard blocks."""
import os
from pathlib import Path
import pytest
from flask import session
from test_content_projects_prototype import environment, post
from kilas_ai import chat_content_routes, chat_content as store, agent_routes
from kilas_ai import autonomous_runner, agent_attachments, automation_store, work_push
import db


@pytest.fixture
def chat(environment,monkeypatch):
    app,client=environment
    monkeypatch.setenv('KILAS_CHAT_CONTENT_DEMO_ENABLED','true')
    monkeypatch.setattr(autonomous_runner,'enabled',lambda:False)
    monkeypatch.setattr(agent_routes.agent_store,'current_conversation',lambda owner:session.get('agent_conversation_id',1))
    monkeypatch.setattr(agent_routes.agent_store,'messages',lambda *args,**kwargs:[])
    monkeypatch.setattr(agent_routes.agent_store,'recent_conversations',lambda owner:[{'id':1,'title':'Brief owner'}] if owner==1 else [])
    monkeypatch.setattr(agent_attachments,'listing',lambda *args:[])
    monkeypatch.setattr(automation_store,'setting',lambda owner:'Asia/Jakarta')
    monkeypatch.setattr(work_push,'configured',lambda:False)
    app.jinja_env.globals.update(ui_language=lambda:'id',ui_messages={},ui_languages={'id':'Indonesia','en':'English'},ui_language_return_path=lambda:'/kilas-ai/agent',kilas_video_enabled=lambda:True)
    for endpoint in ('products.product_start','auth.logout_page','auth.account_page','set_ui_language'):
        if endpoint not in app.view_functions:
            app.add_url_rule('/_synthetic/'+endpoint,endpoint=endpoint,view_func=lambda:'Synthetic stub')
    db.execute("INSERT INTO kilas_ai_conversations(id,user_id,title) VALUES (3,1,'Percakapan lain')")
    return app,client


def mutate(client,op,cid=1,**values):
    return post(client,f'/kilas-ai/agent/conversations/{cid}/content-demo/{op}',**values)


def recording(client,key='recording-operation001',fixture='intro',label='Rekaman A',cid=1):
    response=mutate(client,'recording',cid=cid,label=label,fixture=fixture,operation_key=key,consent='yes')
    assert response.status_code==303
    return db.query_one('SELECT id FROM kilas_chat_demo_recordings WHERE operation_key=?',(key,))['id']


def translate(client,ident,version=1,key='translate-operation001',cid=1,language='en'):
    response=mutate(client,'action',cid=cid,recording_id=ident,version=version,kind='translate',language=language,operation_key=key)
    assert response.status_code==303
    return db.query_one('SELECT id FROM kilas_chat_demo_actions WHERE operation_key=?',(key,))['id']


def test_default_off_preserves_general_chat_and_no_schema_boot(chat,monkeypatch):
    _,client=chat
    monkeypatch.delenv('KILAS_CHAT_CONTENT_DEMO_ENABLED')
    response=client.get('/kilas-ai/agent?conversation=1')
    assert response.status_code==200
    assert b'id="agent-chat-form"' in response.data and b'data-chat-content' not in response.data
    assert mutate(client,'recording').status_code==404
    assert 'if content_enabled() or chat_content_enabled():' in (Path(__file__).parents[1]/'app.py').read_text()


def test_actual_chat_shell_embed_and_injection_escaping(chat):
    _,client=chat
    label='</h3><script>window.injected=1</script>'
    ident=recording(client,label=label)
    text='</textarea><img src=x onerror="window.injected=2">'
    response=mutate(client,'transcript',recording_id=ident,version=1,transcript=text,operation_key='edit-operation0001')
    assert response.status_code==303
    translate(client,ident,version=2)
    body=client.get(f'/kilas-ai/agent?conversation=1&demo_recording={ident}').get_data(as_text=True)
    assert '&lt;script&gt;window.injected=1' in body and '<script>window.injected=1' not in body
    assert '&lt;img src=x' in body and '<img src=x' not in body
    assert 'data-chat-content' in body and 'id="agent-chat-form"' in body and 'id="listening-demo"' not in body
    assert 'Simulasikan' in body


def test_tenant_and_conversation_isolation(chat):
    _,client=chat
    ident=recording(client);action=translate(client,ident)
    for operation,values in (('transcript',dict(recording_id=ident,version=1,transcript='x',operation_key='cross-edit-key0001')),('action',dict(recording_id=ident,version=1,kind='translate',language='en',operation_key='cross-action-key01')),('cancel',dict(action_id=action))):
        assert mutate(client,operation,cid=3,**values).status_code==404
    assert client.get(f'/kilas-ai/agent?conversation=3&demo_recording={ident}').status_code==404
    with client.session_transaction() as sess:
        sess.update(user_id=2,role='CLIENT_OWNER')
    assert mutate(client,'recording',cid=1).status_code==404
    assert client.get('/kilas-ai/agent?conversation=1').status_code==404
    assert client.get(f'/kilas-ai/agent?conversation=2&demo_recording={ident}').status_code==404


def test_csrf_all_mutations_and_explicit_consent(chat):
    _,client=chat
    for op in ('recording','transcript','action','cancel','project'):
        assert client.post(f'/kilas-ai/agent/conversations/1/content-demo/{op}',data={}).status_code==400
    assert mutate(client,'recording',label='x',fixture='intro',operation_key='recording-operation001').status_code==400
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_chat_demo_recordings')['n']==0


def test_prior_artifact_selection_is_exact_not_latest(chat):
    _,client=chat
    first=recording(client)
    second=recording(client,key='recording-operation002',fixture='question',label='Rekaman B')
    response=client.get(f'/kilas-ai/agent?conversation=1&demo_recording={first}')
    assert response.status_code==200
    assert f'data-demo-recording="{first}"'.encode() in response.data
    assert 'Halo, ini contoh' in response.get_data(as_text=True)
    chosen=translate(client,first)
    assert store.action(1,1,chosen)['recording_id']==first and first!=second
    assert client.get('/kilas-ai/agent?conversation=1&demo_recording=bad').status_code==400


def test_transcript_versions_conflicts_and_exact_retries(chat):
    _,client=chat
    ident=recording(client)
    args=dict(recording_id=ident,version=1,transcript='Versi yang sudah diedit',operation_key='edit-operation0001')
    assert mutate(client,'transcript',**args).status_code==303
    assert mutate(client,'transcript',**args).status_code==303
    assert mutate(client,'transcript',**{**args,'transcript':'Changed'}).status_code==409
    assert mutate(client,'transcript',**{**args,'operation_key':'edit-operation0002'}).status_code==409
    assert store.transcript(1,1,ident,1)['content']==store.FIXTURES['intro']
    assert store.transcript(1,1,ident,2)['content']=='Versi yang sudah diedit'
    old=translate(client,ident,version=1)
    assert store.FIXTURES['intro'] in store.action(1,1,old)['output_text']


def test_opening_selecting_and_reloading_never_runs_actions(chat):
    _,client=chat
    ident=recording(client)
    for _ in range(3):
        assert client.get(f'/kilas-ai/agent?conversation=1&demo_recording={ident}&demo_version=1').status_code==200
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_chat_demo_actions')['n']==0


def test_recording_and_action_double_submit_and_cancel_are_idempotent(chat):
    _,client=chat
    ident=recording(client);assert recording(client)==ident
    action=translate(client,ident);assert translate(client,ident)==action
    assert mutate(client,'action',recording_id=ident,version=1,kind='translate',language='id',operation_key='translate-operation001').status_code==409
    for _ in range(2):
        assert mutate(client,'cancel',action_id=action,recording_id=ident).status_code==303
    assert translate(client,ident)==action
    assert store.action(1,1,action)['status']=='CANCELLED'
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_chat_demo_actions')['n']==1


def test_voice_requires_exact_live_translation_reference_and_stock_mock(chat):
    _,client=chat
    first=recording(client);second=recording(client,key='recording-operation002')
    action=translate(client,first)
    args=dict(recording_id=first,version=1,kind='voice',language='en',source_action=action,voice='stock_demo',operation_key='voice-operation0001')
    for changed in ({'recording_id':second},{'version':2},{'language':'id'},{'voice':'personal'}):
        assert mutate(client,'action',**{**args,**changed}).status_code in (400,404)
    assert mutate(client,'action',**args).status_code==303
    assert mutate(client,'action',**args).status_code==303
    row=db.query_one("SELECT * FROM kilas_chat_demo_actions WHERE kind='voice'")
    assert row['source_action_id']==action and 'Tidak ada audio' in row['output_text']
    mutate(client,'cancel',action_id=action)
    assert mutate(client,'action',**{**args,'operation_key':'voice-operation0002'}).status_code==400


def test_project_snapshot_handoff_needs_explicit_click(chat):
    _,client=chat
    ident=recording(client)
    assert mutate(client,'project',title='Proyek chat',brief='Brief sintetis',operation_key='project-operation01',recording_id=ident).status_code==303
    project=store.linked_project(1,1)
    assert project['script_version']==0
    client.get('/kilas-ai/agent?conversation=1')
    assert store.linked_project(1,1)['script_version']==0
    args=dict(recording_id=ident,version=1,kind='project_script',language='id',project_version=0,operation_key='snapshot-operation01')
    assert mutate(client,'action',**args).status_code==303
    assert mutate(client,'action',**args).status_code==303
    from kilas_ai import content_projects
    assert content_projects.script(1,project['id'],1)['content']==store.FIXTURES['intro']
    row=db.query_one("SELECT * FROM kilas_chat_demo_actions WHERE kind='project_script'")
    assert row['recording_id']==ident and row['transcript_version']==1 and row['project_script_version']==1
    assert mutate(client,'project',project_id=999).status_code==404


def test_history_survives_relogin_and_flag_off(chat,monkeypatch):
    _,client=chat
    ident=recording(client);action=translate(client,ident)
    with client.session_transaction() as sess:
        sess.clear();sess.update(user_id=1,role='CLIENT_OWNER',_csrf_token='synthetic-csrf')
    body=client.get('/kilas-ai/agent?conversation=1').get_data(as_text=True)
    assert f'data-demo-action="{action}"' in body
    monkeypatch.setenv('KILAS_CHAT_CONTENT_DEMO_ENABLED','false')
    assert 'data-chat-content' not in client.get('/kilas-ai/agent?conversation=1').get_data(as_text=True)
    assert store.transcript(1,1,ident,1)['content']==store.FIXTURES['intro']


@pytest.mark.skipif(not os.environ.get('KILAS_CHAT_BROWSER_QA_DIR'),reason='Optional local Chromium chat QA')
def test_chat_browser_end_to_end_mock_and_visuals(chat):
    from threading import Thread
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright,expect
    app,client=chat
    output=Path(os.environ['KILAS_CHAT_BROWSER_QA_DIR']);output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,app);worker=Thread(target=server.serve_forever,daemon=True);worker.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None),headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_init_script('''window.realCalls=0;const denied=()=>{window.realCalls++;throw Error('Forbidden real media');};Object.defineProperty(navigator,'mediaDevices',{value:{getDisplayMedia:denied,getUserMedia:denied}});window.MediaRecorder=denied;''')
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
            context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin}])
            page=context.new_page();page.goto(origin+'/kilas-ai/agent?conversation=1')
            requests=[]
            page.on('request',lambda req:requests.append(req.url) if '/content-demo/action' in req.url else None)
            expect(page.locator('#agent-chat-form')).to_be_visible()
            page.locator('.chat-content-workspace > summary').click()
            page.locator('.chat-record-create > summary').click()
            page.get_by_label('Nama rekaman contoh').fill('Rekaman pertama')
            page.get_by_label('Simpan contoh sintetis dalam percakapan ini.',exact=False).check()
            page.get_by_role('button',name='Tambahkan rekaman contoh',exact=True).click()
            expect(page.locator('[data-demo-recording]')).to_have_attribute('data-demo-recording','1')
            page.get_by_label('Transkrip yang bisa diedit',exact=False).fill('Naskah yang sudah saya periksa.')
            page.get_by_role('button',name='Simpan versi transkrip',exact=True).click()
            expect(page.get_by_label('Transkrip yang bisa diedit',exact=False)).to_have_value('Naskah yang sudah saya periksa.')
            page.locator('#agent-message').fill('Pesan biasa tetap tersimpan di composer.')
            page.get_by_role('button',name='Simulasikan terjemahan transkrip v2',exact=True).evaluate("button=>{const form=button.closest('form');form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));}")
            expect(page.locator('[data-demo-action]')).to_have_count(1)
            assert len(requests)==1
            expect(page.locator('#agent-message')).to_have_value('Pesan biasa tetap tersimpan di composer.')
            page.get_by_role('button',name='Simulasikan suara dari terjemahan #1',exact=True).click()
            expect(page.locator('[data-demo-action]')).to_have_count(2)
            page.reload();expect(page.locator('[data-demo-action]')).to_have_count(2)
            with page.expect_download() as info:
                page.get_by_role('link',name='Unduh transkrip v2 · TXT',exact=True).click()
            assert Path(info.value.path()).read_text()=='Naskah yang sudah saya periksa.'
            page.get_by_role('button',name='Batalkan hasil mock #2',exact=True).click()
            expect(page.locator('[data-demo-action="2"]')).to_contain_text('Dibatalkan')
            for name,width in (('desktop',1440),('mobile',390)):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(output/(name+'.png')),full_page=True)
            assert page.evaluate('window.realCalls')==0
            assert page.locator('#agent-chat-form').count()==1
            browser.close()
    finally:
        server.shutdown();worker.join(timeout=5)


def test_transcript_download_exact_version_and_owner(chat):
    _,client=chat
    ident=recording(client)
    mutate(client,'transcript',recording_id=ident,version=1,transcript='Reviewed',operation_key='download-edit-001')
    url=f'/kilas-ai/agent/conversations/1/content-demo/recordings/{ident}/transcript/1.txt'
    response=client.get(url)
    assert response.status_code==200 and b'Reviewed' not in response.data
    assert response.headers['Cache-Control']=='private, no-store'
    assert response.headers['X-Content-Type-Options']=='nosniff'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert client.get(url.replace('/1.txt','/99.txt')).status_code==404
    with client.session_transaction() as sess:
        sess.update(user_id=2,role='CLIENT_OWNER')
    assert client.get(url).status_code==404


def test_action_preserves_explicit_prior_transcript_selection(chat):
    _,client=chat
    ident=recording(client)
    mutate(client,'transcript',recording_id=ident,version=1,transcript='Newer text',operation_key='prior-version-edit1')
    response=mutate(client,'action',recording_id=ident,version=1,kind='translate',language='en',operation_key='prior-version-act01')
    assert 'demo_version=1' in response.headers['Location']
    body=client.get(response.headers['Location']).get_data(as_text=True)
    assert '<option value="1" selected>' in body


def test_listening_inline_has_independent_default_off_flag(chat,monkeypatch):
    _,client=chat
    monkeypatch.delenv('KILAS_LISTENING_DEMO_ENABLED',raising=False)
    assert b'listen-start' not in client.get('/kilas-ai/agent?conversation=1').data
    monkeypatch.setenv('KILAS_LISTENING_DEMO_ENABLED','true')
    assert b'listen-start' in client.get('/kilas-ai/agent?conversation=1').data
