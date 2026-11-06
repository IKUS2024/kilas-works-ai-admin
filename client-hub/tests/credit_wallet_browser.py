"""Activated wallet layout in an isolated app DB; zero real payments/provider IO."""
import json
import logging
import os
from pathlib import Path
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_credit_routes as fixture
from kilas_ai import credit_wallet as wallet


def main():
    fixture.CreditRoutesTests.setUpClass()
    case=fixture.CreditRoutesTests('test_localized_payment_routes_keep_active_plan')
    case.setUp()
    app=case.app;client=case.client_for(case.owner)
    invoice=wallet.create_purchase(case.owner,'browser-local-only')
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    dest=Path('/tmp/kilas-credit-active-browser');dest.mkdir(exist_ok=True)
    report=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/usr/bin/chromium')
            for lang in ('en','id','es','zh'):
                for width in (393,1440):
                    context=browser.new_context(viewport={'width':width,'height':900})
                    context.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin},{'name':'kilas_language','value':lang,'url':origin}])
                    page=context.new_page();errors=[];writes=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
                    for suffix,name in (('/kilas-ai/usage','wallet'),('/kilas-ai/credits/orders/'+invoice,'invoice')):
                        page.goto(origin+suffix,wait_until='networkidle')
                        expect(page.locator('main h1')).to_have_text({'en':'Credit & Usage','id':'Kredit & Penggunaan','es':'Créditos y uso','zh':'积分与用量'}[lang])
                        assert page.locator('html').get_attribute('lang')==lang
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        assert not page.locator('main input[type=hidden][name=csrf_token]').first.get_attribute('value')==''
                        assert 'Preview only' not in page.locator('main').inner_text()
                        page.screenshot(path=str(dest/f'{name}-{lang}-{width}.png'),full_page=True)
                    page.locator('.subscription-back').click()
                    assert page.url.endswith('/kilas-ai/usage')
                    page.go_back()
                    assert '/credits/orders/' in page.url
                    assert not writes,writes
                    assert not errors,errors
                    report.append({'language':lang,'width':width,'overflow':False,'writes':writes,'errors':errors})
                    context.close()
            browser.close()
    finally:server.shutdown();case.tearDown()
    (dest/'report.json').write_text(json.dumps(report,indent=2))
    print('PASS 8 wallet/invoice language/viewport cases; local-only GET, back navigation, no writes/provider calls')

if __name__=='__main__':main()
