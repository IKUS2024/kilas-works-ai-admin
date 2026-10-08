"""HTTPS virtual hosts fulfilled by local Flask; never contacts production or a broker."""
import sys,os,json,shutil
from pathlib import Path
from urllib.parse import urlsplit
project=Path(__file__).resolve().parents[3];sys.path[:0]=[str(project/'client-hub/tests'),str(project/'client-hub')]
import test_kilas_trading as f
from playwright.sync_api import sync_playwright
f.TradingTests.setUpClass();fixture=f.TradingTests('test_xauusd_contract_and_units');fixture.setUp()
f.app.app.config.update(TESTING=False,SESSION_COOKIE_SECURE=True)
out=Path(os.environ.get('TRADING_HOST_QA_OUTPUT','/tmp/trading-host-qa'));out.mkdir(parents=True,exist_ok=True)
checks=[]
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
  context=browser.new_context();client=f.app.app.test_client(use_cookies=False)
  def local(route):
   r=route.request;u=urlsplit(r.url)
   if u.hostname not in ('app.kilasworks.id','trading.kilasworks.id'):return route.abort()
   result=client.open(u.path+('?' +u.query if u.query else ''),base_url=u.scheme+'://'+u.netloc,method=r.method,headers=r.all_headers(),data=r.post_data_buffer)
   if result.status_code in (301,302,303,307,308):
    # Redirect hops otherwise bypass routing and hit the workspace HTTPS proxy.
    headers=dict(result.headers);target=headers.pop('Location')
    route.fulfill(status=200,headers=headers,body='<script>location.replace('+json.dumps(target)+')</script>')
   else:route.fulfill(status=result.status_code,headers=dict(result.headers),body=result.data)
  context.route('**/*',local);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('https://trading.kilasworks.id/');page.wait_for_url('**/login')
  for width in (1440,390):
   page.set_viewport_size(dict(width=width,height=1000));assert page.get_by_role('button',name='Login',exact=True).is_visible()
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
  page.locator('input[name=email]').fill('irvankarnavi@gmail.com');page.locator('input[name=password]').fill('paper-test-only')
  page.get_by_role('button',name='Login',exact=True).click();page.wait_for_url('**/products/services/trading')
  for width in (1440,390):
   page.set_viewport_size(dict(width=width,height=1000));page.reload()
   assert page.get_by_role('button',name='Hentikan trading',exact=True).is_visible()
   assert page.get_by_role('button',name='Mulai AI',exact=True).is_disabled()
   assert page.locator('#order-advanced').get_attribute('open') is None
   assert 'Kilas Services' not in page.locator('body').inner_text();assert 'Kilas Finance' not in page.locator('body').inner_text()
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
   page.screenshot(path=str(out/('desktop.png' if width==1440 else 'mobile.png')),full_page=True)
   checks.append(dict(width=width,authenticated=True,reload=True,no_overflow=True,stop_visible=True,ai_disabled=True))
  app_page=context.new_page();app_page.goto('https://app.kilasworks.id/products/start');app_page.wait_for_url('**/login')
  app_page.locator('input[name=email]').fill('irvankarnavi@gmail.com');app_page.locator('input[name=password]').fill('paper-test-only');app_page.get_by_role('button',name='Login',exact=True).click();app_page.wait_for_url('**/products/start')
  assert 'Kilas Trading' not in app_page.locator('body').inner_text();assert 'Kilas Services' in app_page.locator('body').inner_text()
  page.get_by_role('link',name='Keluar',exact=True).click();page.wait_for_url('**/login')
  app_page.reload();assert app_page.url.endswith('/products/start')
  assert not errors,errors
  assert f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n']==0
  browser.close()
finally:fixture.doCleanups()
(out/'browser-result.json').write_text(json.dumps(dict(checks=checks,host_only_sessions=True,app_services_restored=True,logout_isolated=True,all_requests_intercepted_locally=True,orders=0,paid_calls=0),indent=2)+'\n')
print('Virtual-host desktop/mobile auth, reload, Services and logout isolation PASS; no production network.')
