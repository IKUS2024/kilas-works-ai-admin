"""Local-only responsive Assist QA using real routes and disposable test fixtures.

Run from the repo with client-hub and client-hub/tests on PYTHONPATH:
KILAS_ASSIST_UI_QA=1 python client-hub/tests/assist_ui_refresh_qa.py
Optional QA_BROWSER points to a locally installed Chromium browser.
No production DB, provider traffic, or application configuration is used.
"""
import os
import sys
import json
import tempfile
import threading
from pathlib import Path

if __name__ != '__main__' or os.environ.get('KILAS_ASSIST_UI_QA') != '1':
    raise SystemExit('Explicit local QA flag required')
if any(os.environ.get(k) for k in ('DATABASE_URL', 'RENDER_SERVICE_NAME', 'OPENAI_API_KEY',
                                   'ANTHROPIC_API_KEY', 'WHATSAPP_ACCESS_TOKEN')):
    raise SystemExit('Production configuration forbidden')
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import test_client_hub_v1 as fixture
original_reset = fixture.reset_db
def reset():
    fixture.db._discard_cached_connection()  # Windows cannot unlink an open SQLite file.
    original_reset()
fixture.reset_db = reset
from test_assist_crm_cleanup import CRMTests
from test_assist_master_journey import MasterJourneyTests
from kilas_core import operation_schema, jobs
import repo
import requests
from flask import session, redirect
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect

case = CRMTests()
case.setUp()
operation_schema.apply_schema()
os.environ['KILAS_OPERATIONS_V2_ENABLED'] = 'true'
os.environ['KILAS_CORE_V2_ENABLED'] = 'true'
case.business = repo.get_business(case.bid)
repo.upsert_business_profile(case.bid, dict(primary_language='id', owner_name='Pemilik',
    business_phone='628123000000', operating_hours='09.00–17.00', online_or_offline='online'))
MasterJourneyTests.complete_onboarding(case)
MasterJourneyTests.teach(case)
case.turn('Saya mau foto produk', dict(action='Siapkan foto produk untuk katalog',
                                      job_status='PERLU_TINDAKAN'), 'REQUEST', name='Nadia — Toko Bunga')
customer_id = case.customer['id']
job_id = jobs.list_jobs(case.bid)[0][0]['id']
for i in range(12):
    case.phone = '62812345' + str(1000 + i)
    case.turn('Berapa harga foto produk?', name='Pelanggan Uji ' + str(i + 1))
case.turn('Saya tertarik', dict(follow_up='Tanyakan kebutuhan yang ingin dibahas'))
lead_id = fixture.db.query_one('SELECT id FROM kw_core_customers WHERE business_id=? AND phone=?',
                               (case.bid,case.phone))['id']
import subscription_service
subscription_service.create_subscription(case.bid,'ai_admin',case.uid)
conversation_id = fixture.db.query_one('SELECT conversation_id FROM kw_core_wa_conversations WHERE business_id=? AND customer_phone=?',
                                      (case.bid,case.phone))['conversation_id']
# Legacy Inbox and canonical Inbox are separate supported renderers.
for role,text in [('user','Halo, saya ingin tahu harga foto produk untuk katalog toko saya.'),
                  ('assistant','Tentu, layanan foto produk tersedia. Ada berapa produk yang ingin difoto?')]:
    fixture.db.execute("INSERT INTO messages(number,mode,role,content) VALUES (?,'customer',?,?)",
                       (f'T{case.bid}:{case.phone}',role,text))
import wa_takeover_service
wa_takeover_service.start_human_takeover(case.bid,case.phone,case.uid)
requests.sessions.Session.request = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('External IO forbidden'))
app = fixture.FLASK_APP

@app.get('/qa/assist-ui-owner')
def qa_owner():
    session.clear()
    session.update(user_id=case.uid, role='CLIENT_OWNER', active_product='brain', _csrf_token='ui-qa')
    return redirect('/workspace/ai')

@app.get('/qa/assist-ui-anonymous')
def qa_anonymous():
    session.clear()
    return redirect('/login')

server = make_server('127.0.0.1', 0, app)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = 'http://127.0.0.1:' + str(server.server_port)
out = Path(os.environ.get('QA_OUTPUT', str(Path(tempfile.gettempdir()) / 'kilas-assist-ui-review')))
out.mkdir(parents=True, exist_ok=True)
results, issues = [], []
bid = case.bid
routes = [
    ('home', '/workspace/ai'), ('products', '/products/start'),
    ('entry', '/products/assist'), ('business-create', '/products/assist?step=business'),
    ('onboarding', f'/business/{bid}/wizard/basics'),
    ('training', f'/business/{bid}/train'), ('leads', f'/business/{bid}/customers?stage=LEAD'),
    ('customers', f'/business/{bid}/customers?stage=CUSTOMER'),
    ('customer-detail', f'/business/{bid}/customers/{customer_id}'),
    ('lead-detail', f'/business/{bid}/customers/{lead_id}'),
    ('jobs', f'/business/{bid}/jobs'), ('job-detail', f'/business/{bid}/jobs/{job_id}'),
    ('inbox', f'/business/{bid}/inbox'),
    ('conversation', f'/business/{bid}/inbox?customer={case.phone}'),
    ('canonical-inbox', f'/business/{bid}/inbox?channel=web'),
    ('canonical-conversation', f'/business/{bid}/inbox?channel=web&conversation={conversation_id}'),
    ('empty-search', f'/business/{bid}/customers?q=does-not-exist&stage=LEAD'),
    ('whatsapp', f'/workspace/go/review?business_id={bid}'),
    ('usage', f'/workspace/usage/{bid}'), ('checkout', f'/business/{bid}/ai-admin/checkout'),
    ('more', '/workspace/more'), ('settings', f'/workspace/go/settings?business_id={bid}'),
    ('followup', f'/workspace/go/automations?business_id={bid}'), ('account', '/account'),
]
try:
    with sync_playwright() as p:
        launch = dict(headless=True)
        if os.environ.get('QA_BROWSER'):
            launch['executable_path'] = os.environ['QA_BROWSER']
        browser = p.chromium.launch(**launch)
        for width, height in [(360,800),(820,1180),(1440,1000)]:
            context = browser.new_context(viewport=dict(width=width,height=height), reduced_motion='reduce')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            # Only this fixture server and its assets can be reached by the browser.
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            def visit(name,path):
                response = page.goto(base + path, wait_until='domcontentloaded')
                page.wait_for_timeout(120)
                layout = page.evaluate('''() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
                    unnamed:[...document.querySelectorAll('input:not([type=hidden]),select,textarea')]
                    .filter(e=>!e.labels?.length&&!e.getAttribute('aria-label')&&!e.getAttribute('aria-labelledby'))
                    .map(e=>e.name),
                    small:[...document.querySelectorAll('.client-status,.client-page-btn,.kw-business-status')]
                    .filter(e=>e.getClientRects().length&&parseFloat(getComputedStyle(e).fontSize)<12).length})''')
                result = dict(page=name,status=response.status,url=page.url.replace(base,''),**layout)
                results.append(result)
                if response.status != 200 or layout['scroll'] > width or layout['unnamed'] or layout['small']:
                    issues.append(result)
                page.screenshot(path=str(out / f'{width}-{name}.png'), full_page=True)
            page.goto(base+'/qa/assist-ui-anonymous')
            for name,path in [('login','/login'),('signup','/register'),('forgot-password','/forgot-password'),('landing','/')]:
                visit(name,path)
            page.goto(base+'/qa/assist-ui-owner')
            for name,path in routes:
                visit(name,path)
            # Real form/disclosure paths and refresh resilience, without outbound messages.
            page.goto(base+f'/business/{bid}/customers/{lead_id}')
            page.locator('[data-followup-editor] > summary').click()
            page.locator('#followup-draft').fill('Draft uji yang belum dikirim')
            page.clock.install()
            page.clock.run_for(21000)
            assert page.locator('#followup-draft').input_value() == 'Draft uji yang belum dikirim'
            assert page.locator('#followup-draft').evaluate('(e)=>e===document.activeElement')
            page.screenshot(path=str(out/f'{width}-followup-editor.png'),full_page=True)
            page.locator('details.card > summary').click()
            page.locator('label[for=contact-name]').click()
            assert page.locator('#contact-name').evaluate('(e)=>e===document.activeElement')
            page.goto(base+f'/business/{bid}/inbox?customer={case.phone}')
            page.locator('#inbox-reply').fill('Balasan uji yang belum dikirim')
            page.clock.run_for(11000)
            assert page.locator('#inbox-reply').input_value() == 'Balasan uji yang belum dikirim'
            assert page.locator('#inbox-reply').evaluate('(e)=>e===document.activeElement')
            page.route('**/inbox?**', lambda route: route.abort() if route.request.headers.get('x-requested-with') else route.continue_())
            page.clock.run_for(11000)
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(page.locator('#kw-live-state')).to_have_text('Koneksi ulang')
            page.screenshot(path=str(out/f'{width}-inbox-offline.png'),full_page=True)
            page.unroute('**/inbox?**')
            page.goto(base+f'/business/{bid}/customers?stage=LEAD')
            for button in page.locator('.client-page-btn').all():
                box=button.bounding_box()
                assert box['width']>=44 and box['height']>=44
            assert page.locator('.client-toolbar [aria-current=true]').inner_text()=='Lead'
            page.clock.resume()
            page.goto(base+f'/business/{bid}/train')
            page.locator('#teach-message').fill('Informasi uji; tidak disimpan oleh browser QA')
            # Cancel navigation AFTER the application submit listeners have set feedback.
            # This preserves the real DOM state without sending or saving the synthetic input.
            page.evaluate("document.addEventListener('submit',event=>event.preventDefault(),{once:true})")
            page.locator('#ajari-kilas button').click()
            assert page.locator('#ajari-kilas [data-assist-submit-status]').inner_text()=='Sedang diproses…'
            page.screenshot(path=str(out/f'{width}-training-loading.png'),full_page=True)
            if errors:
                issues.append(dict(width=width,javascript_errors=errors))
            context.close()
        browser.close()
except Exception as error:
    issues.append(dict(interaction_error=str(error)))
    raise
finally:
    server.shutdown()
    case.doCleanups()
    fixture.db._discard_cached_connection()
    (out/'results.json').write_text(json.dumps(dict(results=results,issues=issues),indent=2),encoding='utf-8')
print(json.dumps(dict(pages=len(results), issues=issues, output=str(out)), indent=2))
raise SystemExit(bool(issues))
