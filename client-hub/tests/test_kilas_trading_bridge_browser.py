"""Foreground bridge UI against loopback Flask + synthetic collector, no MT5/network provider."""
import os
from pathlib import Path
import re
import shutil
import threading
import time
from unittest.mock import patch
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
import test_kilas_trading as f
from test_kilas_trading_bridge import collector, market
from kilas_trading import bridge_store

def main():
    f.TradingTests.setUpClass();bridge_store.apply_release()
    f.app.app.config.update(TESTING=False)
    output=Path(os.environ.get('TRADING_BRIDGE_QA_OUTPUT','/tmp/trading-bridge-browser'));output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    try:
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'true'}),patch.object(collector,'BASE',origin+'/products/services/trading/bridge'),sync_playwright() as p:
            executable=os.environ.get('TRADING_CHROMIUM') or shutil.which('chromium')
            browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/login');page.locator('input[name=email]').fill('irvankarnavi@gmail.com')
            page.locator('input[name=password]').fill('paper-test-only');page.get_by_role('button',name='Login',exact=True).click()
            page.wait_for_url('**/products/start');page.goto(origin+'/products/services/trading')
            page.locator('#bridge-details > summary').click()
            page.locator('#trading-bridge select').select_option('BTCUSD')
            page.get_by_role('button',name='Buat pairing sekali pakai').click()
            page.locator('[data-bridge-code]').wait_for(state='visible')
            code=re.search(r'Kode sekali pakai: ([a-f0-9]{32})',page.locator('[data-bridge-code]').inner_text())[1]
            session=collector.Session(collector.Transport(),'BTCUSD',code)
            session.send(market('BTCUSD'));page.wait_for_function("document.querySelector('[data-bridge-status]').textContent.includes('CONNECTED')")
            time.sleep(1.1);session.send(market('BTCUSD',1780000032))
            page.wait_for_function("document.querySelector('[data-bridge-status]').textContent.includes('UNVERIFIED_CLOCK_PROFILE')")
            assert 'BTCUSD' in page.locator('[data-bridge-market]').inner_text()
            assert page.get_by_role('button',name='Hubungkan',exact=True).is_disabled()
            pairing=page.get_by_role('button',name='Buat pairing sekali pakai')
            pairing.hover()
            assert pairing.evaluate("e=>getComputedStyle(e).backgroundColor")=='rgb(255, 240, 229)'
            assert pairing.evaluate("e=>getComputedStyle(e).color")=='rgb(32, 35, 41)'
            for width in (1440,768,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
                page.screenshot(path=str(output/f'bridge-{width}.png'),full_page=True)
            page.reload();page.locator('#bridge-details > summary').click()
            assert page.locator('[data-bridge-code]').inner_text()==''
            page.get_by_role('button',name='Cabut akses bridge').click()
            page.wait_for_function("document.querySelector('[data-bridge-status]').textContent.includes('dicabut')")
            assert page.locator('[data-bridge-market]').inner_text()==''
            session.clear();assert not errors,errors
            browser.close()
            print('Bridge browser PASS: real pairing/collector HTTP, BTCUSD read-only observation, unverified clock/profile, revoke, memory-only code, 1440/768/390/320, no page errors.')
    finally:
        server.shutdown();thread.join(timeout=2);server.server_close()

if __name__=='__main__':main()
