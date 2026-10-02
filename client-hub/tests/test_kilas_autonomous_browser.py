"""Batched desktop/tablet/mobile tasks, controls, long output and unread checks."""
import os
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['CLIENT_HUB_DB_PATH'] = tempfile.mktemp(suffix='.sqlite')
os.environ['SECRET_KEY'] = 'autonomous-browser-fixture'
os.environ['KILAS_AI_ENABLED'] = 'true'
os.environ['KILAS_AI_AUTOMATION_ENABLED'] = 'true'
os.environ['KILAS_AI_AUTONOMOUS_ENABLED'] = 'true'
os.environ.pop('DATABASE_URL', None)
import app
import db
import repo
from kilas_ai import autonomous_store as store, autonomous_planner as planner
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server


def main():
    server = make_server('127.0.0.1', 0, app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width, height in ((1440,900), (820,900), (390,844), (320,700)):
                owner = repo.create_user(f'autonomous-browser-{width}@example.test', 'hash')
                job = store.create(owner, 'Riset kompetitor ' + 'nama panjang ' * 40)
                client = app.app.test_client()
                with client.session_transaction() as state:
                    state.update(user_id=owner, role='CLIENT_OWNER', _csrf_token='autonomous-browser')
                cookie = client.get_cookie('session')
                context = browser.new_context(viewport={'width':width, 'height':height})
                context.add_cookies([{'name':cookie.key, 'value':cookie.value, 'url':origin}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(origin + '/kilas-ai/agent?view=tasks')
                assert page.get_by_role('heading', name='Sedang berjalan').is_visible()
                assert page.get_by_role('link', name='Detail', exact=True).is_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, 'tasks overflow')
                page.get_by_role('link', name='Detail', exact=True).click()
                page.get_by_text('Detail pekerjaan',exact=True).click()
                assert page.get_by_role('heading', name='Langkah pekerjaan').is_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, 'detail overflow')
                page.get_by_role('button', name='Jeda', exact=True).click()
                assert store.get(owner,job)['status'] == 'PAUSED'
                page.get_by_role('button', name='Lanjutkan', exact=True).click()
                assert store.get(owner,job)['status'] == 'PLANNING'
                page.get_by_label('Tambahkan instruksi').fill('Jangan deploy. Stop setelah test pass.')
                page.get_by_role('button', name='Simpan instruksi').click()
                assert 'Jangan deploy' in store.get(owner,job)['constraints_json']
                page.get_by_text('Detail pekerjaan',exact=True).click()
                page.get_by_role('button', name='Tandai sudah dibaca').click()
                assert db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_events WHERE job_id=? AND unread=1', (job,))['n'] == 0
                page.get_by_role('button', name='Hentikan', exact=True).click()
                assert store.get(owner,job)['status'] == 'STOPPED'
                assert not errors, errors
                page.screenshot(path=str(Path(tempfile.gettempdir()) / f'autonomous-{width}.png'), full_page=True)
                context.close()
            browser.close()
    finally:
        server.shutdown()
    print('PASS: task panel/detail, pause/resume/feedback/stop/unread and no overflow at 1440/820/390/320')


if __name__ == '__main__':
    main()
