"""Synthetic responsive admin approval journey; never uses production accounts."""
import json
import os
from pathlib import Path
import shutil
import threading
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_platform_manual_payments as f


def main():
    fixture=f.ManualPaymentsTests('test_approve_once_activates_each_product_and_replay_never_grants_twice')
    fixture.setUp()
    for kind in ('subscription','capacity','translator','finance'):fixture.seed(kind)
    f.db.execute('UPDATE users SET full_name=?,email=? WHERE id=?',('Customer Contoh','customer@example.test',fixture.owner))
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    origin='http://127.0.0.1:'+str(server.server_port)
    out=Path('/tmp/platform-payments-browser');out.mkdir(exist_ok=True)
    errors=[];results=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox'])
            context=browser.new_context()
            cookie=fixture.client.get_cookie('session')
            context.add_cookies([{'name':'session','value':cookie.value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            for width in (320,393,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                for path in ('/platform/','/platform/payments','/platform/customers','/platform/translator',f'/platform/customers/{fixture.owner}'):
                    response=page.goto(origin+path,wait_until='networkidle')
                    assert response.status==200,(path,response.status)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),(width,path)
                    links=page.locator('nav[aria-label="Navigasi admin"] a');expect(links).to_have_count(4)
                    for link in links.all():
                        box=link.bounding_box();assert box['x']>=0 and box['x']+box['width']<=width+1
                    if path=='/platform/payments':
                        expect(page.locator('[data-payment-review]')).to_have_count(4)
                        expect(page.get_by_role('button',name='Approve',exact=True)).to_have_count(4)
                        expect(page.locator('[data-payment-kind="finance"] .console-amount')).to_have_text('Rp99.000')
                        page.screenshot(path=str(out/f'payments-{width}.png'),full_page=True)
                    if path=='/platform/':page.screenshot(path=str(out/f'overview-{width}.png'),full_page=True)
                    results.append({'width':width,'path':path,'ok':True})
            page.set_viewport_size({'width':393,'height':900})
            page.goto(origin+'/platform/payments',wait_until='networkidle')
            # Proof opens separately and leaves the pending queue intact.
            article=page.locator('[data-payment-kind="translator"]')
            with context.expect_page() as opened:article.get_by_role('link',name='Lihat bukti transfer').click()
            proof=opened.value;proof.wait_for_load_state();assert '/proof' in proof.url;proof.close()
            expect(article.get_by_role('button',name='Approve',exact=True)).to_be_visible()
            with page.expect_navigation():article.get_by_role('button',name='Approve',exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('Pembayaran disetujui')
            expect(page.locator('[data-payment-kind="translator"]')).to_have_count(0)
            assert fixture.entitlement('translator')['seconds']==60
            page.reload(wait_until='networkidle');assert fixture.entitlement('translator')['seconds']==60
            page.get_by_role('link',name='Riwayat',exact=True).click();expect(page.locator('[data-payment-kind="translator"]')).to_contain_text('Disetujui')
            expect(page.locator('[data-payment-kind="translator"] button')).to_have_count(0)
            page.go_back(wait_until='networkidle');assert fixture.entitlement('translator')['seconds']==60
            # Reject is a separate single submit, never an approve default.
            article=page.locator('[data-payment-kind="capacity"]')
            with page.expect_navigation():article.get_by_role('button',name='Tolak',exact=True).click()
            assert fixture.row('capacity')['status']=='REJECTED';assert not fixture.entitlement('capacity')
            # No inline confirmation dialog, no second payment action.
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown();fixture.doCleanups()
    print(json.dumps({'pages':len(results),'journey':'proof, approve, refresh, history, back, reject','javascript_errors':errors,'screenshots':str(out)}))


if __name__=='__main__':main()
