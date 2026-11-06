"""Activated wallet layout in an isolated app DB; zero real payments/provider IO."""
import json
import logging
import os
from pathlib import Path
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from credit_browser_tools import launch
from werkzeug.serving import make_server
import test_kilas_credit_routes as fixture
from kilas_ai import credit_wallet as wallet, audio_provider, audio_service, audio_store
from werkzeug.datastructures import FileStorage
import io
from test_kilas_credit_adapters import TARIFFS


def main():
    fixture.CreditRoutesTests.setUpClass()
    case=fixture.CreditRoutesTests('test_localized_payment_routes_keep_active_plan')
    case.setUp()
    app=case.app;client=case.client_for(case.owner)
    mocks=[patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps(TARIFFS)}),
        patch.object(audio_provider,'configured',return_value=True),
        patch.object(audio_provider,'voices',return_value=[{'id':'syntheticVoice123','name':'Synthetic'}]),
        patch.object(audio_service,'estimate',return_value=(30,90)),patch.object(audio_service,'submit')]
    for mock in mocks:mock.start()
    dispatch=audio_service.submit
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    dest=Path('/tmp/kilas-credit-active-browser');dest.mkdir(exist_ok=True)
    report=[]
    try:
        with sync_playwright() as p:
            browser=launch(p)
            for lang in ('en','id','es','zh'):
                for width in (393,1440):
                    user=fixture.fixture.repo.create_user(f'credit-browser-{lang}-{width}@example.test','hash')
                    client=case.client_for(user)
                    invoice=wallet.create_purchase(user,'browser-local-only')
                    funded=wallet.create_purchase(user,'browser-synthetic-funding')
                    with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):
                        wallet.submit_proof(user,funded,FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
                    wallet.review(funded,case.admin,'VERIFIED',transfer_reference=f'SYNTHETIC-BROWSER-{lang}-{width}')
                    context=browser.new_context(viewport={'width':width,'height':900})
                    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
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
                    assert page.evaluate('window.kilasCreditConsentInstalled===true')
                    form={'csrf_token':'console-csrf','operation_key':f'browser-approved-{lang}-{width}','mode':'voiceover','language':'en','voice':'syntheticVoice123','script':'Synthetic browser speech'}
                    before=dispatch.call_count
                    page.evaluate("""form=>{window.creditResult=null;window.creditPending=fetch('/kilas-translator/jobs',{method:'POST',body:new URLSearchParams(form)}).then(async r=>window.creditResult={status:r.status,...await r.json()});}""",form)
                    dialog=page.locator('dialog');expect(dialog).to_be_visible()
                    with page.expect_popup() as event:dialog.locator('button').first.click()
                    popup=event.value;popup.set_viewport_size({'width':min(width,520),'height':800});popup.wait_for_load_state('networkidle')
                    assert popup.locator('html').get_attribute('lang')==lang
                    assert popup.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    popup.screenshot(path=str(dest/f'consent-{lang}-{width}.png'),full_page=True)
                    popup.locator('button[value=approve]').click()
                    page.wait_for_function('window.creditResult!==null')
                    result=page.evaluate('window.creditResult')
                    assert result['status']==201,result
                    assert dispatch.call_count==before+1
                    popup.close()
                    # Same operation can be retrieved; it must not dispatch again.
                    repeat=page.evaluate("""async form=>{let r=await fetch('/kilas-translator/jobs',{method:'POST',body:new URLSearchParams(form)});return r.status;}""",form)
                    assert repeat==200 and dispatch.call_count==before+1
                    audio_store.fail(user,result['id'],'synthetic_pre_dispatch')
                    form['operation_key']=f'browser-declined-{lang}-{width}'
                    page.evaluate("""form=>{window.creditResult=null;window.creditPending=fetch('/kilas-translator/jobs',{method:'POST',body:new URLSearchParams(form)}).then(async r=>window.creditResult={status:r.status,...await r.json()});}""",form)
                    expect(page.locator('dialog')).to_be_visible();page.locator('dialog button').last.click()
                    page.wait_for_function('window.creditResult!==null')
                    assert page.evaluate('window.creditResult.status')==402
                    assert dispatch.call_count==before+1
                    form['operation_key']=f'browser-aborted-{lang}-{width}'
                    page.evaluate("""form=>{window.abortCredit=new AbortController();window.abortResult=null;fetch('/kilas-translator/jobs',{method:'POST',body:new URLSearchParams(form),signal:abortCredit.signal}).then(r=>window.abortResult=r.status).catch(e=>window.abortResult=e.name);}""",form)
                    expect(page.locator('dialog')).to_be_visible();page.evaluate('abortCredit.abort()')
                    expect(page.locator('dialog')).to_have_count(0)
                    assert dispatch.call_count==before+1
                    assert not errors,errors
                    report.append({'language':lang,'width':width,'overflow':False,'consent_approved_once':True,'decline_no_dispatch':True,'abort_no_dispatch':True,'consent_width':min(width,520),'synthetic_writes':len(writes),'errors':errors})
                    context.close()
            browser.close()
    finally:
        server.shutdown();case.tearDown()
        for mock in reversed(mocks):mock.stop()
    (dest/'report.json').write_text(json.dumps(report,indent=2))
    print('PASS 8 wallet/invoice/consent language/viewport cases; approve once, decline/abort no dispatch, back, no supplier IO')

if __name__=='__main__':main()
