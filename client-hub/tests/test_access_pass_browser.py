"""Synthetic customer -> admin -> customer, responsive/payment recovery QA."""
import json, shutil, threading
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
import test_access_pass as f

def main():
    # Synthetic invoice destination keeps public QA screenshots free of real account details.
    from kilas_ai import billing_routes
    billing_routes.SUBSCRIPTION_BANK={'bank_name':'Test Bank','account_number':'0000000000','account_holder':'Synthetic QA'}
    fix=f.AccessPassTests();fix.setUp()
    server=make_server('127.0.0.1',0,f.app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    out=Path('/tmp/access-pass-browser');out.mkdir(exist_ok=True)
    errors=[]
    def context(browser,client):
        ctx=browser.new_context(locale='id-ID')
        ctx.add_cookies([{'name':'session','value':client.get_cookie('session').value,'url':origin},{'name':'kilas_language','value':'id','url':origin}])
        return ctx
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=shutil.which('chromium') or None,headless=True,args=['--no-sandbox'])
            ctx=context(browser,fix.client);page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            for width in (320,393,768,1440):
                page.set_viewport_size({'width':width,'height':900});response=page.goto(origin+'/kilas-ai/usage',wait_until='networkidle')
                assert response.status==200
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                expect(page.get_by_role('button',name='Aktifkan Rp99.000 / 30 hari')).to_be_visible()
                page.screenshot(path=str(out/f'usage-{width}.png'),full_page=True)
            page.set_viewport_size({'width':393,'height':900})
            page.get_by_role('button',name='Aktifkan Rp99.000 / 30 hari').click();page.wait_for_url('**/invoices/*')
            invoice=int(page.url.split('/')[-1]);invoice_url=page.url
            assert f.billing.invoice(fix.user,invoice)['amount_idr']==99000
            page.reload();assert not f.access_pass.active(fix.user)
            for width in (320,393,768,1440):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(out/f'invoice-{width}.png'),full_page=True)
            page.locator('#proof').set_input_files({'name':'bad.png','mimeType':'image/png','buffer':b'bad'})
            page.get_by_role('button',name='Kirim bukti transfer').click();expect(page.get_by_role('alert')).to_be_visible()
            expect(page.get_by_role('button',name='Kirim bukti transfer')).to_be_enabled()
            page.locator('#proof').set_input_files({'name':'proof.png','mimeType':'image/png','buffer':fix.proof})
            page.get_by_role('button',name='Kirim bukti transfer').click();expect(page.get_by_role('status')).to_have_text('Menunggu persetujuan admin')
            assert not f.access_pass.active(fix.user)
            admin=f.app.app.test_client();f.authenticate(admin,f.repo.get_user_by_id(fix.admin),_csrf_token='admin-pass')
            actx=context(browser,admin);apage=actx.new_page();apage.goto(origin+'/platform/payments')
            payment=f.billing.proof_status(fix.user,invoice)['id']
            article=apage.locator('[data-payment-kind="subscription"]');expect(article).to_have_count(1)
            with actx.expect_page() as proof:article.get_by_role('link',name='Lihat bukti transfer').click()
            proof.value.wait_for_load_state();proof.value.close()
            article.get_by_role('button',name='Approve',exact=True).click();expect(apage.get_by_role('status')).to_contain_text('Pembayaran disetujui')
            before=f.usage.effective_plan(fix.user);apage.reload();assert before==f.usage.effective_plan(fix.user)
            page.goto(invoice_url);expect(page.get_by_role('status')).to_have_text('Disetujui')
            page.get_by_role('link',name='Lihat masa aktif').click();expect(page.locator('.subscription-current')).to_contain_text('Kilas Pro aktif')
            expect(page.get_by_role('button',name='Perpanjang 30 hari')).to_be_enabled()
            page.set_viewport_size({'width':393,'height':900})
            page.screenshot(path=str(out/'active-393.png'),full_page=True)
            page.go_back();page.go_forward();expect(page.get_by_role('button',name='Perpanjang 30 hari')).to_be_enabled()
            assert before==f.usage.effective_plan(fix.user)
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
    print(json.dumps({'screenshots':str(out),'responsive_widths':[320,393,768,1440],'errors':errors,'journey':'checkout,invalid-proof,retry,upload,admin-proof,approve,reload,active,back-forward'}))

if __name__=='__main__':main()
