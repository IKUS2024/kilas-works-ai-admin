"""Real browser chat interaction, task continuity and responsive layouts on synthetic data."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.update(CLIENT_HUB_DB_PATH=tempfile.mktemp(suffix='.sqlite'),SECRET_KEY='chat-browser-qa',
                  KILAS_AI_ENABLED='true',KILAS_AI_AUTOMATION_ENABLED='true',KILAS_AI_AUTONOMOUS_ENABLED='true')
os.environ.pop('DATABASE_URL',None)
import app
import repo
import db
from kilas_ai import autonomous_store as jobs, providers, autonomous_planner
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server


def main():
    def reply(*args):
        time.sleep(.6)
        yield {'type':'delta','text':'Bitcoin adalah aset digital.'}
        yield {'type':'finish','reason':'stop'}
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.object(providers,'stream',side_effect=reply),sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            for width,height in [(1440,900),(820,900),(390,844),(320,700)]:
                owner=repo.create_user(f'chat-browser-{width}@example.test','hash')
                client=app.app.test_client()
                with client.session_transaction() as state: state.update(user_id=owner,role='CLIENT_OWNER',_csrf_token='chat-browser')
                cookie=client.get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':height},timezone_id='Asia/Jakarta',
                                            has_touch=width<681,reduced_motion='reduce')
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+'/kilas-ai/agent',wait_until='networkidle')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,'empty')
                assert not page.locator('.autonomous-options').evaluate('(el)=>el.open')
                assert not page.locator('.agent-main').inner_text().find('UTC')>=0
                composer=page.get_by_label('Pesan untuk Kilas')
                composer.fill('Apa itu Bitcoin?');composer.press('Enter')
                expect(page.locator('#agent-thinking')).to_be_visible()
                expect(page.get_by_role('button',name='Kirim',exact=True)).to_be_disabled()
                composer.press('Enter')
                expect(page.get_by_text('Bitcoin adalah aset digital.',exact=True)).to_be_visible()
                expect(page.locator('#agent-thinking')).to_be_hidden()
                assert db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_agent_messages WHERE user_id=? AND role='user'",(owner,))['n']==1
                assert jobs.list_jobs(owner)==[]
                composer.fill('Riset kompetitor ini sampai selesai');composer.press('Shift+Enter')
                assert '\n' in composer.input_value()
                composer.fill('Riset kompetitor ini sampai selesai');composer.press('Enter')
                expect(page.locator('[data-job-id]')).to_be_visible()
                job=jobs.list_jobs(owner)[0]
                assert job['origin_conversation_id'] is not None
                assert 'Menyiapkan rencana' in page.locator('[data-task-cards]').inner_text()
                expect(page.get_by_role('button',name='Kirim',exact=True)).to_be_enabled()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,'task')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'agent-chat-{width}.png'),full_page=True)
                if width<681:
                    page.get_by_role('button',name='Buka menu chat').tap()
                    expect(page.locator('#agent-sidebar')).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.locator('#agent-sidebar')).to_be_hidden()
                    page.get_by_role('button',name='Buka menu chat').tap()
                page.get_by_role('button',name='+ New Chat',exact=True).click()
                expect(page.get_by_role('heading',name='Apa yang ingin kamu kerjakan?',exact=True)).to_be_visible()
                assert page.locator('.agent-message').count()==0
                assert jobs.get(owner,job['id'])['status']=='PLANNING'
                if width<681:page.get_by_role('button',name='Buka menu chat').tap()
                page.get_by_role('link',name='Active Tasks',exact=True).click()
                expect(page.locator('[data-job-id]')).to_be_visible()
                page.get_by_role('button',name='Jeda',exact=True).click()
                expect(page.get_by_text('Dijeda',exact=True)).to_be_visible()
                page.get_by_role('button',name='Lanjutkan',exact=True).click()
                assert jobs.get(owner,job['id'])['status']=='PLANNING'
                page.get_by_role('link',name='Buka percakapan',exact=True).click()
                expect(page.get_by_text('Bitcoin adalah aset digital.',exact=True)).to_be_visible()
                assert page.locator('#agent-title').count()==0
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,'history')
                # Long title and verified output remain readable; detail keeps existing controls.
                db.execute('UPDATE kilas_agent_jobs SET title=? WHERE id=?',('VeryLongUnbrokenProjectName'*8,job['id']))
                page.goto(origin+f'/kilas-ai/agent/jobs/{job["id"]}')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),(width,'detail')
                page.screenshot(path=str(Path(tempfile.gettempdir())/f'agent-detail-{width}.png'),full_page=True)
                assert not errors,errors
                context.close()
            browser.close()
    finally:server.shutdown()
    print('PASS: streaming/Thinking/duplicate/Enter/New Chat/history/tasks/controls/links/mobile drawer and no overflow at 1440/820/390/320')


if __name__=='__main__':main()
