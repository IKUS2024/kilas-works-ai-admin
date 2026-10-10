"""Retained read-only bridge APIs behind a minimal dashboard, synthetic loopback only."""
import os
from pathlib import Path
import shutil
import threading
from unittest.mock import patch
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
import test_kilas_trading as f
from test_kilas_trading_bridge import collector, market
from kilas_trading import bridge_store


def main():
    f.TradingTests.setUpClass();bridge_store.apply_release();f.app.app.config.update(TESTING=False)
    output=Path(os.environ.get('TRADING_BRIDGE_QA_OUTPUT','/tmp/trading-bridge-browser'));output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin=f'http://127.0.0.1:{server.server_port}';path=origin+'/products/services/trading/bridge'
    owner=f.TradingTests('test_xauusd_contract_and_units').login(f.TradingTests.user)
    try:
        with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'true'}),patch.object(collector,'BASE',path),sync_playwright() as p:
            executable=os.environ.get('TRADING_CHROMIUM') or shutil.which('chromium')
            browser=p.chromium.launch(**({'executable_path':executable} if executable else {}),args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_cookies([dict(name='session',value=owner.get_cookie('session').value,url=origin)])
            page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            pair=context.request.post(path+'/pair',data=dict(symbol='BTCUSD',server='XMGlobal-MT5 10'),headers={'X-CSRF-Token':'paper-csrf'})
            assert pair.status==200
            session=collector.Session(collector.Transport(),'BTCUSD',pair.json()['pair_code'])
            session.send(market('BTCUSD'))
            assert context.request.get(path+'/status').json()['last_confirmed_stage']=='TELEMETRY_ACCEPTED'
            page.goto(origin+'/products/services/trading')
            assert page.locator('#trading-bridge').count()==0
            assert page.get_by_role('switch',name='ON/OFF robot DEMO').is_disabled()
            assert 'OFF · Belum siap' in page.locator('#robot-status').inner_text()
            with patch.dict(os.environ,{'KILAS_TRADING_BRIDGE_ENABLED':'false'}):
                view=context.request.get(path+'/status');assert view.status==200
                data=view.json();assert data['last_confirmed_stage']=='TELEMETRY_ACCEPTED'
                assert data['outcome']=='DISABLED' and data['transport']=='DISCONNECTED' and 'market' not in data
                assert context.request.post(path+'/revoke',data={}).status==400
                revoked=context.request.post(path+'/revoke',data={},headers={'X-CSRF-Token':'paper-csrf'})
                assert revoked.status==200 and revoked.json()['outcome']=='REVOKED'
                assert context.request.get(path+'/status').json()['revoked'] is True
                assert context.request.post(path+'/pair',data=dict(symbol='BTCUSD',server='XMGlobal-MT5 10'),headers={'X-CSRF-Token':'paper-csrf'}).status==404
                page.reload()
                for width in (1440,768,390,320):
                    page.set_viewport_size({'width':width,'height':1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),width
                    assert page.locator('.trading details,.trading form').count()==0
                    assert page.get_by_role('switch',name='ON/OFF robot DEMO').is_disabled()
                page.screenshot(path=str(output/'bridge-off-revoked.png'),full_page=True)
            session.clear();assert not errors,errors;browser.close()
            print('Bridge browser PASS: synthetic loopback API pair/exchange/telemetry, OFF status and CSRF revoke preserved; dashboard exposes only inactive controls; four widths, no page errors.')
    finally:
        server.shutdown();thread.join(timeout=2);server.server_close()

if __name__=='__main__':main()
