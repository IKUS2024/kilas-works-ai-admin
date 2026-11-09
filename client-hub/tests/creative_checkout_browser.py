"""Historical and current fixed-price checkout/payment journeys on isolated local data.

Real login, CSRF, invoice replay and proof upload; no paid transitions or external IO.
Unresolved current prices remain discussion-only.
"""
import io,json,logging,os,sys,threading,shutil
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from test_creative_checkout import CreativeCheckoutTests
import creative_orders as orders
import payment_service
import projects_repo


def verify_service_image(page, service):
    photo=page.locator('.selected-service img')
    filename='event-wedding-camera.webp' if service=='event' else 'social-product-phone.webp'
    expect(photo).to_have_attribute('src','/creative-services/assets/checkout/'+filename)
    expect(photo).to_have_attribute('alt',__import__('re').compile('^Ilustrasi '))
    photo.evaluate('(image)=>image.decode()')
    geometry=photo.evaluate('(image)=>({w:image.getBoundingClientRect().width,h:image.getBoundingClientRect().height,nw:image.naturalWidth,nh:image.naturalHeight,fit:getComputedStyle(image).objectFit})')
    assert (geometry['nw'],geometry['nh'])==(1859,846),geometry
    assert abs(geometry['w']/geometry['h']-1859/846)<0.02,geometry
    assert geometry['fit']=='contain',geometry


def verify_current_checkout(browser, origin, case, output, image, errors, external):
    current_catalog=json.loads(Path(__file__).resolve().parents[1].joinpath('creative_catalog.json').read_text())
    results=[]
    # The server and browser share this isolated process; restore the historical
    # fixture after these scenarios so neither suite can alter the other's facts.
    with patch.object(orders,'CATALOG',current_catalog):
        for width in (390,1024):
            context=browser.new_context(viewport={'width':width,'height':900})
            context.add_cookies([{'name':'kilas_language','value':'id','url':origin,'httpOnly':True}])
            def route(r):
                if r.request.url.startswith(origin):r.continue_()
                else:external.append(r.request.url);r.abort()
            context.route('**/*',route)
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            try:
                # Real anonymous selection and login must preserve a current offer.
                page.goto(origin+'/creative-services/checkout/creative_event_basic')
                expect(page.locator('.selected-service h2')).to_have_text(current_catalog['packages']['creative_event_basic']['name'])
                page.locator('.signin a').click()
                page.locator('#auth-email').fill(case.email);page.locator('#auth-password').fill(case.password)
                page.locator('.auth-form button[type=submit]').click()
                page.wait_for_url('**/checkout/creative_event_basic*')
                expect(page.locator('#name')).to_be_enabled()
                for key,spec in current_catalog['packages'].items():
                    path=origin+'/creative-services/checkout/'+key
                    page.goto(path)
                    if orders.offer(key)['quotation_required']:
                        expect(page.locator('[data-checkout-form]')).to_have_count(0)
                        expect(page.locator('body')).to_contain_text('quotation tertulis')
                        continue
                    expect(page.locator('[data-checkout-form]')).to_be_visible()
                    token=page.locator('input[name=order_token]').input_value()
                    csrf=page.locator('input[name=csrf_token]').input_value()
                    assert token and csrf
                    data={'order_token':token,'csrf_token':csrf,'name':'Synthetic Current Browser QA',
                          'whatsapp':'081234567890','event_date':'2099-12-01','location':'Synthetic venue',
                          'brand':'Synthetic brand','social_account':'@synthetic'}
                    before=case.db.query_one('SELECT COUNT(*) n FROM invoices')['n']
                    invalid=dict(data,csrf_token='invalid-synthetic-csrf')
                    denied=context.request.post(path,form=invalid,max_redirects=0)
                    assert denied.status in (400,403),denied.status
                    assert case.db.query_one('SELECT COUNT(*) n FROM invoices')['n']==before
                    page.locator('#name').fill(data['name']);page.locator('#whatsapp').fill(data['whatsapp'])
                    if spec['service']=='event':
                        page.locator('#event_date').fill(data['event_date']);page.locator('#location').fill(data['location'])
                    else:
                        page.locator('#brand').fill(data['brand'])
                        if spec['service']=='social':page.locator('#social_account').fill(data['social_account'])
                        else:
                            expect(page.locator('#social_account')).to_have_count(0)
                            data.pop('social_account')
                    verify_service_image(page,spec['service'])
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/f'current-{key}-{width}.png'),full_page=True)
                    # Original form POST automatically redirects to the invoice's payment screen.
                    page.locator('button.primary[type=submit]').click()
                    page.wait_for_url('**/creative-services/payment/*')
                    invoice_id=int(page.url.rsplit('/',1)[1])
                    invoice=payment_service.get_invoice(invoice_id)
                    snapshot=projects_repo.get_project(invoice['project_id'])['requirements']
                    assert invoice['amount']==spec['amount']==snapshot['total']
                    assert snapshot['key']==key and snapshot['features']==spec['features']
                    expect(page.locator('#account-number')).to_be_visible()
                    expect(page.locator('.invoice')).to_contain_text(orders.money(spec['amount']))
                    verify_service_image(page,spec['service'])
                    count=case.db.query_one('SELECT COUNT(*) n FROM invoices')['n']
                    replay=context.request.post(path,form=data,max_redirects=0)
                    assert replay.status==303,replay.status
                    assert replay.headers['location'].endswith('/payment/'+str(invoice_id))
                    assert case.db.query_one('SELECT COUNT(*) n FROM invoices')['n']==count
                    page.goto(path+'?draft='+token)
                    page.wait_for_url('**/payment/'+str(invoice_id))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/f'current-payment-{key}-{width}.png'),full_page=True)
                    page.locator('#proof').set_input_files({'name':'synthetic-current.png','mimeType':'image/png','buffer':image})
                    page.locator('button.primary[type=submit]').click()
                    expect(page.locator('.status')).to_contain_text('menunggu verifikasi')
                    assert payment_service.get_payment_for_invoice(invoice_id)['status']=='UNDER_REVIEW'
                    assert payment_service.get_invoice(invoice_id)['status']=='ISSUED'
                    results.append({'width':width,'package':key,'amount':spec['amount'],'csrf':'PASS',
                                    'nonce_replay':'PASS','status':'UNDER_REVIEW'})
            finally:context.close()
    return results


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    case=CreativeCheckoutTests('test_repeated_submit_and_persistence');case.id=lambda:'creative-browser-fixture';case.setUp()
    server=make_server('127.0.0.1',0,case.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    origin=f'http://127.0.0.1:{server.server_port}'
    output=Path('/tmp/creative-checkout-browser');output.mkdir(exist_ok=True)
    image=io.BytesIO();Image.new('RGB',(48,32),'white').save(image,'PNG')
    results=[];errors=[];external=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,executable_path=shutil.which('chromium'),args=['--no-sandbox'])
            for width in (390,1024):
                context=browser.new_context(viewport={'width':width,'height':900},permissions=['clipboard-read','clipboard-write'])
                # This journey asserts Indonesian offer/status copy explicitly.
                context.add_cookies([{'name':'kilas_language','value':'id','url':origin,'httpOnly':True}])
                def route(r):
                    if r.request.url.startswith(origin):r.continue_()
                    else:external.append(r.request.url);r.abort()
                context.route('**/*',route)
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                # Historical direct link, then real login and return to the selection.
                # Current public cards correctly lead to consultation, not checkout.
                page.goto(origin+'/creative-services/checkout/creative_event_standard')
                expect(page.locator('.selected-service h2')).to_have_text('Foto & Video Acara — Standard')
                page.locator('.signin a').click();page.locator('#auth-email').fill(case.email);page.locator('#auth-password').fill(case.password)
                page.locator('.auth-form button[type=submit]').click();page.wait_for_url('**/checkout/creative_event_standard*')
                expect(page.locator('#name')).to_be_enabled()
                for key,spec in orders.CATALOG['packages'].items():
                    service=spec['service'];tier=spec['tier'].lower()
                    addons=list(orders.CATALOG['addons']) if service=='social' else ['none']
                    for addon in addons:
                        page.goto(origin+'/creative-services/checkout/'+key)
                        page.wait_for_url('**/checkout/'+key+'*')
                        expect(page.locator('.selected-service h2')).to_have_text(spec['name'])
                        expect(page.locator('.price')).to_contain_text(orders.money(spec['amount']))
                        verify_service_image(page,service)
                        page.locator('#name').fill('Synthetic Browser QA');page.locator('#whatsapp').fill('081234567890')
                        if service=='event':
                            page.locator('#event_date').fill('2099-12-01');page.locator('#location').fill('Synthetic venue')
                        else:
                            page.locator('#brand').fill('Synthetic brand');page.locator('#social_account').fill('@synthetic');page.locator('#addon').select_option(addon)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        if tier=='basic' and addon=='none':page.screenshot(path=str(output/f'{service}-checkout-{width}.png'),full_page=True)
                        page.locator('.primary').click();page.wait_for_url('**/creative-services/payment/*')
                        invoice=int(page.url.rsplit('/',1)[1]);expected=orders.offer(key,addon)['total']
                        assert payment_service.get_invoice(invoice)['amount']==expected
                        verify_service_image(page,service)
                        expect(page.locator('#account-number')).to_have_text('010180016000684')
                        page.locator('.copy').click();assert page.evaluate('navigator.clipboard.readText()')=='010180016000684'
                        expect(page.locator('body')).not_to_contain_text('Pembayaran diperiksa secara manual')
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        if service=='event' and tier=='basic':
                            page.screenshot(path=str(output/f'payment-{width}.png'),full_page=True)
                            # Back + submit reuses the persisted snapshot/invoice.
                            page.go_back();page.wait_for_url('**/payment/'+str(invoice))
                            # Existing browser storage survives tab closure/reopen.
                            url=page.url;page.close();page=context.new_page();page.goto(url);expect(page.locator('#account-number')).to_be_visible()
                        page.locator('#proof').set_input_files({'name':'synthetic-test-image.png','mimeType':'image/png','buffer':image.getvalue()})
                        page.locator('.primary').click();expect(page.locator('.status')).to_contain_text('menunggu verifikasi')
                        assert payment_service.get_payment_for_invoice(invoice)['status']=='UNDER_REVIEW'
                        assert payment_service.get_invoice(invoice)['status']=='ISSUED'
                        page.reload();expect(page.locator('.status')).to_contain_text('menunggu verifikasi')
                        results.append({'width':width,'package':key,'addon':addon,'amount':expected,'status':'UNDER_REVIEW'})
                context.close()
            current_results=verify_current_checkout(browser,origin,case,output,image.getvalue(),errors,external)
            browser.close()
        assert not errors and not external,(errors,external)
        (output/'results.json').write_text(json.dumps({'scope':'historical and current fixed-price checkout','cases':results,'current_cases':current_results,'errors':errors,'external_requests':external,'paid_transitions':0},indent=2))
        print(f'PASS {len(results)} historical + {len(current_results)} current package journeys at 390/1024px; screenshots {output}')
    finally:server.shutdown();case.doCleanups()

if __name__=='__main__':main()
