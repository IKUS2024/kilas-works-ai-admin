"""Real responsive checkout, focus and exhausted-capacity UI; synthetic local data."""
import threading
import logging
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_kilas_intelligence_capacity as fixture
from kilas_ai import providers, usage, store


def reply(*args,**kwargs):
    yield {'type':'provider','provider':'openai','model':'gpt-6-luna'}
    yield {'type':'delta','text':'Halo! Chat normal tetap dapat digunakan.'}
    yield {'type':'usage','input_tokens':100,'output_tokens':30}
    yield {'type':'finish','reason':'stop'}


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    fixture.fixture.app.app.config.update(TESTING=True,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
    server=make_server('127.0.0.1',0,fixture.fixture.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    captures=Path(__file__).resolve().parents[2]/'.impeccable/review'
    captures.mkdir(parents=True,exist_ok=True)
    try:
        with patch.object(providers,'stream',side_effect=reply),sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (320,360,390,430,768,1024,1440):
                test=fixture.CapacityTests('test_normal_chat_survives_exhaustion')
                test.id=lambda:f'capacity-browser-{width}'
                test.setUp()
                client=fixture.fixture.app.app.test_client()
                with client.session_transaction() as state:state.update(user_id=test.uid,role='CLIENT_OWNER',_csrf_token='capacity-browser')
                cookie=client.get_cookie('session')
                context=browser.new_context(viewport={'width':width,'height':900},has_touch=width<768)
                context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}])
                page=context.new_page();errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(origin+'/kilas-ai/usage',wait_until='networkidle')
                expect(page.get_by_role('heading',name='Langganan & Pembayaran')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                page.screenshot(path=str(captures/f'capacity-{width}.png'),full_page=True)
                opener=page.locator('[data-capacity-open]');opener.click()
                dialog=page.locator('#capacity-dialog');expect(dialog).to_be_visible()
                assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth'),width
                # Top-layer dialogs must be captured at the real viewport size.
                page.screenshot(path=str(captures/f'capacity-dialog-{width}.png'))
                assert dialog.locator('input[name=pack]').count()==3
                page.keyboard.press('Escape');expect(dialog).not_to_be_visible();expect(opener).to_be_focused()
                opener.click();page.locator('input[value=EXTRA]').check()
                page.get_by_role('button',name='Lanjut ke pembayaran').click()
                expect(page.get_by_text('Rp50.000',exact=True)).to_be_visible()
                expect(page.get_by_text('Berlaku 90 hari setelah pembayaran terverifikasi.',exact=False)).to_be_visible()
                assert not fixture.topups.balance(test.uid)['available']
                test.spent(100)
                page.goto(origin+f'/kilas-ai/threads/{test.thread}',wait_until='networkidle')
                expect(page.locator('[data-premium-capacity-notice]')).to_be_visible()
                page.locator('#ai-input').fill('halo');page.get_by_role('button',name='Kirim',exact=True).click()
                expect(page.get_by_text('Halo! Chat normal tetap dapat digunakan.',exact=True)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
                if width<768:assert page.locator('#ai-input').evaluate('e=>document.activeElement!==e')
                page.reload(wait_until='networkidle')
                expect(page.get_by_text('Halo! Chat normal tetap dapat digunakan.',exact=True)).to_be_visible()
                assert not errors,errors
                context.close()
                print(f'PASS capacity UI, dialog, checkout, normal Chat after exhaustion, persistence and focus: {width}px',flush=True)
            browser.close()
    finally:server.shutdown()


if __name__=='__main__':main()
