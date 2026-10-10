"""Minimal Trading controls: loopback app, synthetic account, no broker or orders."""
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
import test_kilas_trading as f


def main():
    f.TradingTests.setUpClass();f.app.app.config.update(TESTING=False)
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(os.environ.get('TRADING_QA_OUTPUT','/tmp/kilas-trading-browser'));output.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as p:
            executable=os.environ.get('TRADING_CHROMIUM') or shutil.which('chromium')
            browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/login')
            page.locator('input[name=email]').fill('irvankarnavi@gmail.com');page.locator('input[name=password]').fill('paper-test-only')
            page.get_by_role('button',name='Login',exact=True).click();page.wait_for_url('**/products/start')
            page.goto(origin+'/products/services/trading')
            toggle=page.get_by_role('switch',name='ON/OFF robot DEMO')
            instrument=page.get_by_label('Instrumen',exact=True);lot=page.get_by_label('LOT',exact=True)
            def inactive():
                assert toggle.is_disabled() and toggle.get_attribute('aria-checked')=='false'
                assert 'OFF · Belum siap' in page.locator('#robot-status').inner_text()
                assert 'offline / belum terverifikasi' in page.locator('#robot-account').inner_text()
                assert 'XMGlobal-MT5 10' not in page.locator('#robot-account').inner_text()
                assert page.locator('.trading button').count()==1
                assert page.locator('.trading select').count()==1
                assert page.locator('.trading input').count()==1
                assert page.locator('.trading details,.trading form,.trading dl,.trading svg,.trading article,.trading script').count()==0
                assert page.locator('[data-new-position],#trading-bridge,#diagnostic-file,#paper-risk-form').count()==0
            inactive()
            assert instrument.input_value()=='BTC'
            assert instrument.locator('option').all_text_contents()==['GOLD','BTC']
            assert lot.input_value()=='0.01' and lot.get_attribute('min')=='0.01'
            assert lot.get_attribute('step')=='any'
            before=f.store.snapshot(f.TradingTests.user);posts=[]
            watch=lambda request:posts.append(request.url) if request.method=='POST' else None
            page.on('request',watch)
            lot.fill('0.001');assert not lot.evaluate('e=>e.checkValidity()')
            lot.fill('0.02');assert lot.evaluate('e=>e.checkValidity()')
            instrument.select_option('GOLD');inactive()
            assert not posts,posts
            assert f.store.snapshot(f.TradingTests.user)==before
            page.reload();assert lot.input_value()=='0.01' and instrument.input_value()=='BTC'
            for value,view in (('BTC','default'),('GOLD','gold')):
                instrument.select_option(value)
                for width in (1440,768,390,320):
                    page.set_viewport_size({'width':width,'height':1100});inactive()
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
                    assert lot.input_value()=='0.01'
                    page.screenshot(path=str(output/f'robot-{view}-{width}.png'),full_page=True)
            assert not posts,posts
            page.remove_listener('request',watch)
            # Unavailable storage cannot introduce an active control or expose exception text.
            with patch.object(f.store,'snapshot',side_effect=RuntimeError('synthetic-private-error')):
                response=page.reload();assert response.status==503;inactive()
                assert 'synthetic-private-error' not in page.locator('.trading').inner_text()
            assert f.app.app.view_functions['kilas_trading.home'].__globals__['analysis'].market_source is None
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown();thread.join(timeout=2);server.server_close()
    print('Browser PASS: only GOLD/BTC, LOT and disabled ON/OFF; no panels, POSTs or state mutation; draft reset, invalid lot, storage failure; 1440/768/390/320; no page errors.')

if __name__=='__main__':main()
