"""Real one-chat projects with all mock flags off and external transport forbidden."""
import os
from pathlib import Path
import pytest
from test_content_projects_prototype import environment, post
from test_chat_content_demo import chat
from kilas_ai import chat_projects as store, content_projects as projects
import db


@pytest.fixture
def real(chat, monkeypatch):
    monkeypatch.setenv('KILAS_CHAT_CONTENT_DEMO_ENABLED', 'false')
    monkeypatch.setenv('KILAS_LISTENING_DEMO_ENABLED', 'false')
    return chat


def mutate(client, operation, cid=1, **values):
    return post(client, f'/kilas-ai/agent/conversations/{cid}/content-project/{operation}', **values)


def create(client, cid=1, key='real-project-key001', expected=0, title='Proyek nyata'):
    response = mutate(client, 'choose', cid, title=title, brief='Brief milik pengguna.', expected_project_id=expected, operation_key=key)
    assert response.status_code == 303
    return store.selected(1, cid)['id']


def save(client, ident, expected=0, text='Naskah yang sudah diperiksa.', key='real-script-key0001', cid=1, reviewed='yes'):
    return mutate(client, 'script', cid, project_id=ident, version=expected, script=text, operation_key=key, reviewed=reviewed)


def test_real_flag_independent_from_demo_and_no_mock_reads(real, monkeypatch):
    _, client = real
    original_one, original_all = db.query_one, db.query_all
    def guard(call):
        def query(sql, *args, **kwargs):
            assert not any(name in sql for name in ('kilas_chat_demo_recordings', 'kilas_chat_demo_transcripts', 'kilas_chat_demo_actions'))
            return call(sql, *args, **kwargs)
        return query
    monkeypatch.setattr(db, 'query_one', guard(original_one))
    monkeypatch.setattr(db, 'query_all', guard(original_all))
    body = client.get('/kilas-ai/agent?conversation=1').data
    assert b'data-chat-projects' in body and b'id="agent-chat-form"' in body
    assert b'data-chat-content' not in body and b'listening-demo' not in body and b'Simulasikan' not in body
    assert client.post('/kilas-ai/agent/conversations/1/content-demo/project', data={'csrf_token': 'synthetic-csrf'}).status_code == 404
    monkeypatch.setenv('KILAS_CONTENT_PROJECTS_ENABLED', 'false')
    assert b'data-chat-projects' not in client.get('/kilas-ai/agent?conversation=1').data
    assert mutate(client, 'choose', title='x', operation_key='flag-off-key00001', expected_project_id=0).status_code == 404


def test_every_mutation_requires_csrf_and_existing_roles(real):
    _, client = real
    for op in ('choose', 'script'):
        assert client.post(f'/kilas-ai/agent/conversations/1/content-project/{op}', data={}).status_code == 400
    for owner, role, status in ((2, 'CLIENT_OWNER', 404), (3, 'KILAS_ADMIN', 404)):
        with client.session_transaction() as sess:
            sess.update(user_id=owner, role=role)
        assert mutate(client, 'choose', title='x', operation_key='foreign-key00001', expected_project_id=0).status_code == status
    with client.session_transaction() as sess:
        sess.clear()
    assert client.get('/kilas-ai/agent?conversation=1').status_code == 302


def test_project_conversation_ownership_and_selector_choices(real):
    _, client = real
    foreign = projects.create(2, 'Other owner private title', '', 'foreign-project001')
    assert mutate(client, 'choose', project_id=foreign, expected_project_id=0, operation_key='foreign-choice001').status_code == 404
    assert mutate(client, 'choose', cid=2, title='x', expected_project_id=0, operation_key='foreign-chat-key1').status_code == 404
    ident = create(client)
    body = client.get('/kilas-ai/agent?conversation=1').get_data(as_text=True)
    assert 'Other owner private title' not in body
    assert store.selected(1, 3) is None
    assert save(client, ident, cid=3).status_code == 409
    assert save(client, foreign).status_code == 404


def test_atomic_create_link_retry_changed_payload_and_stale_selection(real):
    _, client = real
    ident = create(client)
    assert create(client) == ident
    assert len(projects.listing(1)) == 1 and len(projects.links(1, ident)) == 1
    assert mutate(client, 'choose', title='Changed', brief='Brief milik pengguna.', expected_project_id=0, operation_key='real-project-key001').status_code == 409
    other = create(client, key='real-project-key002', expected=ident, title='Proyek kedua')
    assert store.selected(1, 1)['id'] == other
    assert mutate(client, 'choose', title='Proyek nyata', brief='Brief milik pengguna.', expected_project_id=0, operation_key='real-project-key001').status_code == 409
    assert mutate(client, 'choose', title='Must roll back', expected_project_id=0, operation_key='stale-create-key01').status_code == 409
    assert len(projects.listing(1)) == 2
    assert save(client, ident).status_code == 409


@pytest.mark.parametrize('values', ({'project_id': 'invalid'}, {'project_id': -1}, {'expected_project_id': -1}, {'expected_project_id': 'invalid'}))
def test_invalid_selection_fails_without_mutation(real, values):
    _, client = real
    assert mutate(client, 'choose', title='x', operation_key='invalid-choice001', expected_project_id=values.get('expected_project_id', 0), **{k: v for k, v in values.items() if k != 'expected_project_id'}).status_code == 400
    assert not projects.listing(1)


def test_review_cas_immutable_versions_and_duplicates(real):
    _, client = real
    ident = create(client)
    assert save(client, ident, reviewed='').status_code == 400
    assert projects.get(1, ident)['script_version'] == 0
    assert save(client, ident).status_code == 303
    assert save(client, ident).status_code == 303
    assert save(client, ident, text='Changed same operation').status_code == 409
    assert save(client, ident, expected=0, key='stale-script-key01').status_code == 409
    assert save(client, ident, expected=1, text='Versi kedua', key='real-script-key0002').status_code == 303
    assert projects.script(1, ident, 1)['content'] == 'Naskah yang sudah diperiksa.'
    assert projects.script(1, ident, 2)['content'] == 'Versi kedua'


def test_get_reload_old_version_and_handoff_never_generate(real):
    _, client = real
    ident = create(client)
    save(client, ident)
    save(client, ident, expected=1, text='Versi terbaru', key='real-script-key0002')
    url = '/kilas-ai/agent?conversation=1&chat_script_version=1'
    for _ in range(3):
        body = client.get(url).get_data(as_text=True)
        assert 'Naskah yang sudah diperiksa.' in body and '>Versi terbaru</textarea>' not in body
        assert f'content_project={ident}&amp;script_version=1' in body
    translator = client.get(f'/kilas-translator?content_project={ident}&script_version=1&content_mode=voiceover').get_data(as_text=True)
    assert 'Naskah yang sudah diperiksa.' in translator and '>Versi terbaru</textarea>' not in translator
    assert projects.get(1, ident)['script_version'] == 2
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'] == 3
    assert db.query_one('SELECT COUNT(*) AS n FROM kilas_video_projects')['n'] == 2
    for name in ('kilas_chat_demo_recordings', 'kilas_chat_demo_transcripts', 'kilas_chat_demo_actions'):
        assert db.query_one('SELECT COUNT(*) AS n FROM ' + name)['n'] == 0
    for version in ('0', '-1', 'invalid', '99'):
        assert client.get('/kilas-ai/agent?conversation=1&chat_script_version=' + version).status_code in (400, 404)


def test_download_version_is_owner_and_conversation_scoped(real):
    _, client = real
    ident = create(client)
    save(client, ident, text='</textarea><script>unsafe text</script>')
    url = f'/kilas-ai/agent/conversations/1/content-project/{ident}/scripts/1.txt'
    response = client.get(url)
    assert response.status_code == 200 and response.mimetype == 'text/plain'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert client.get(url.replace('/1/content-project/', '/3/content-project/')).status_code == 404
    body = client.get('/kilas-ai/agent?conversation=1').get_data(as_text=True)
    assert '<script>unsafe text</script>' not in body and '&lt;script&gt;unsafe text&lt;/script&gt;' in body
    with client.session_transaction() as sess:
        sess.update(user_id=2, role='CLIENT_OWNER')
    assert client.get(url).status_code == 404


def test_reload_relogin_flag_rollback_preserves_real_metadata(real, monkeypatch):
    _, client = real
    ident = create(client)
    save(client, ident)
    with client.session_transaction() as sess:
        sess.clear(); sess.update(user_id=1, role='CLIENT_OWNER', _csrf_token='synthetic-csrf')
    assert str(ident).encode() in client.get('/kilas-ai/agent?conversation=1').data
    monkeypatch.setenv('KILAS_CONTENT_PROJECTS_ENABLED', 'false')
    assert b'data-chat-projects' not in client.get('/kilas-ai/agent?conversation=1').data
    monkeypatch.setenv('KILAS_CONTENT_PROJECTS_ENABLED', 'true')
    assert store.selected(1, 1)['id'] == ident
    assert projects.script(1, ident, 1)['content'] == 'Naskah yang sudah diperiksa.'


@pytest.mark.skipif(not os.environ.get('KILAS_REAL_PROJECT_BROWSER_QA_DIR'), reason='Optional local Chromium QA')
def test_browser_real_project_with_demo_off_desktop_mobile(real):
    from threading import Thread
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright, expect
    app, client = real
    output = Path(os.environ['KILAS_REAL_PROJECT_BROWSER_QA_DIR']); output.mkdir(parents=True, exist_ok=True)
    server = make_server('127.0.0.1', 0, app); worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None), headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_init_script("window.realCalls=0;const denied=()=>{window.realCalls++;throw Error('Forbidden real media');};Object.defineProperty(navigator,'mediaDevices',{value:{getDisplayMedia:denied,getUserMedia:denied}});window.MediaRecorder=denied;")
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
            context.add_cookies([{'name': 'session', 'value': client.get_cookie('session').value, 'url': origin}])
            page = context.new_page(); page.goto(origin + '/kilas-ai/agent?conversation=1')
            expect(page.locator('[data-chat-content],#listening-demo')).to_have_count(0)
            page.locator('#agent-message').fill('Pesan biasa tetap di composer.')
            page.locator('.chat-project-workspace > summary').click()
            page.get_by_label('Nama proyek baru', exact=True).fill('Proyek dari percakapan')
            page.get_by_label('Brief proyek baru', exact=True).fill('Brief yang saya tulis.')
            calls = []; page.on('request', lambda req: calls.append(req.url) if '/content-project/choose' in req.url else None)
            page.get_by_role('button', name='Tautkan proyek ke percakapan', exact=True).evaluate("button=>{const form=button.closest('form');form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));}")
            expect(page.locator('.chat-project-workspace > summary')).to_contain_text('Proyek dari percakapan')
            assert len(calls) == 1
            expect(page.locator('#agent-message')).to_have_value('Pesan biasa tetap di composer.')
            page.locator('.chat-project-script > summary').click()
            page.get_by_label('Naskah proyek', exact=True).fill('Versi satu yang sudah saya periksa.')
            page.get_by_label('Saya sudah memeriksa naskah ini.', exact=True).check()
            page.get_by_role('button', name='Simpan sebagai versi baru', exact=True).click()
            expect(page.get_by_role('link', name='Buka draft VoiceOver · v1', exact=True)).to_be_attached()
            expect(page.locator('#agent-message')).to_have_value('Pesan biasa tetap di composer.')
            page.locator('.chat-project-script > summary').click()
            page.get_by_label('Naskah proyek', exact=True).fill('Versi dua yang sudah saya periksa.')
            page.get_by_label('Saya sudah memeriksa naskah ini.', exact=True).check()
            page.get_by_role('button', name='Simpan sebagai versi baru', exact=True).click()
            expect(page.get_by_role('link', name='Buka draft VoiceOver · v2', exact=True)).to_be_attached()
            page.reload()
            page.get_by_label('Versi naskah yang dibuka', exact=True).select_option('1')
            page.get_by_role('button', name='Buka versi naskah', exact=True).click()
            expect(page.get_by_role('link', name='Buka draft VoiceOver · v1', exact=True)).to_be_attached()
            with page.expect_download() as info:
                page.get_by_role('link', name='Unduh naskah v1 · TXT', exact=True).click()
            assert Path(info.value.path()).read_text() == 'Versi satu yang sudah saya periksa.'
            page.get_by_role('link', name='Buka draft VoiceOver · v1', exact=True).click()
            expect(page.locator('#audio-script')).to_have_value('Versi satu yang sudah saya periksa.')
            page.go_back(); page.locator('.chat-project-script > summary').click()
            for name, width in (('desktop', 1440), ('mobile', 390)):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.locator('[data-chat-projects]').evaluate('root=>{root.scrollTop=root.querySelector(".chat-project-script").offsetTop-root.offsetTop;}')
                page.screenshot(path=str(output / (name + '.png')), full_page=True)
            assert page.evaluate('window.realCalls') == 0
            assert page.locator('#agent-chat-form').count() == 1
            browser.close()
    finally:
        server.shutdown(); worker.join(timeout=5)
