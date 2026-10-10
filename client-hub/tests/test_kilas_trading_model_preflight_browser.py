"""Loopback diagnostic page with fake GET response; no production/provider IO."""
import os
import shutil
import threading
from pathlib import Path
from unittest.mock import patch
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
import test_kilas_trading as f
from test_kilas_trading_model_preflight import Reply
from kilas_trading import analysis

def main():
    f.TradingTests.setUpClass();f.app.app.config.update(TESTING=False)
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path('/tmp/trading-model-preflight-browser');out.mkdir(exist_ok=True)
    try:
        with patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-private-key'}),patch.object(analysis.requests,'request',return_value=Reply()) as provider,sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('TRADING_CHROMIUM') or shutil.which('chromium'),args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(origin+'/login');page.locator('input[name=email]').fill('irvankarnavi@gmail.com');page.locator('input[name=password]').fill('paper-test-only')
            page.get_by_role('button',name='Login',exact=True).click();page.wait_for_url('**/products/start')
            page.goto(origin+'/products/services/trading/model/diagnostics')
            self_status=page.locator('#model-preflight-status')
            assert 'Not checked' in self_status.inner_text();assert provider.call_count==0
            assert page.locator('#model-preflight-result').is_hidden()
            for width in (1440,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(out/f'not-checked-{width}.png'),full_page=True)
            page.get_by_role('button',name='Check model access',exact=True).click()
            page.wait_for_function("document.querySelector('#model-preflight-status').textContent.includes('complete')")
            assert provider.call_count==1;assert provider.call_args.args[0]=='GET'
            assert page.locator('#model-credential').inner_text()=='PRESENT'
            assert page.locator('#model-http').inner_text()=='200';assert page.locator('#model-match').inner_text()=='Yes'
            assert 'synthetic-private' not in page.locator('body').inner_text()
            page.screenshot(path=str(out/'result-320.png'),full_page=True)
            with patch.object(analysis.requests,'request',side_effect=RuntimeError('private-provider-failure')):
                page.get_by_role('button',name='Check model access',exact=True).click()
                page.wait_for_function("document.querySelector('#model-http').textContent==='Unavailable'")
                assert page.locator('#model-match').inner_text()=='No'
                assert 'private-provider' not in page.locator('body').inner_text()
            page.reload();assert 'Not checked' in self_status.inner_text();assert provider.call_count==1
            page.goto(origin+'/products/services/trading')
            assert page.get_by_role('switch').is_disabled()
            assert page.get_by_role('button',name='Check model access').count()==0
            assert not errors,errors;browser.close()
    finally:server.shutdown();thread.join(timeout=2);server.server_close()
    print('Browser PASS: explicit click only; fixed provider GET; sanitized success/unavailable; reload never checks; no dashboard card; disabled robot; desktop/mobile320; no errors.')

if __name__=='__main__':main()
