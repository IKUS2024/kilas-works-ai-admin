"""Real Chromium profile close/reopen and selected-route behavior; isolated local server."""
import sys,os,json,logging,threading,tempfile,shutil
from pathlib import Path

def local_only(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):raise AssertionError('External network forbidden')
 if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',None):raise AssertionError('External DNS forbidden')
sys.addaudithook(local_only)
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from unittest.mock import patch
from test_customer_auth_sessions import CustomerAuthTests
import finance_service


def main():
 logging.getLogger('werkzeug').setLevel(logging.ERROR)
 case=CustomerAuthTests('test_cross_module_continuity_home_launch_and_deep_link_refresh');case.setUp()
 business=case.repo.create_business(case.owner,'Disposable Finance');finance_service.ensure_finance_defaults(business)
 app=case.app;server=make_server('127.0.0.1',0,app,threaded=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();origin=f'http://127.0.0.1:{server.server_port}'
 results=[];errors=[];paid=[]
 try:
  with tempfile.TemporaryDirectory(prefix='customer-auth-browser-') as profile,patch.dict(os.environ,{'KILAS_FINANCE_BETA':'on'}),sync_playwright() as pw:
   def launch():
    c=pw.chromium.launch_persistent_context(profile,executable_path=shutil.which('chromium'),headless=True,viewport={'width':390,'height':844},args=['--no-sandbox','--disable-background-networking'])
    c.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin) else route.abort())
    page=c.pages[0];page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:paid.append(request.url) if request.method=='POST' and request.url not in (origin+'/login',origin+'/kilas-ai/work/preferences') else None)
    return c,page
   c,page=launch();page.goto(origin+'/login');page.locator('#auth-email').fill(case.email);page.locator('#auth-password').fill(case.password)
   with page.expect_navigation():page.locator('.auth-form button[type=submit]').click()
   assert page.url==origin+'/products/start'
   cookies=c.cookies();stored=next(x for x in cookies if x['name']=='session');assert stored['expires']>0 and stored['httpOnly'] and stored['sameSite']=='Lax'
   for path in ('/kilas-translator?mode=voiceover',f'/business/{business}/finance'):
    page.goto(origin+path,wait_until='networkidle');assert '/login' not in page.url
    assert page.url.startswith(origin+path.split('?')[0]);c.close()
    c,page=launch();page.goto(origin+'/',wait_until='networkidle');assert page.url==origin+'/products/start'
    expect(page.locator('.kilas-new-chat-logo')).to_be_visible()
    page.goto(origin+'/kilas-translator?mode=voiceover',wait_until='networkidle');page.reload(wait_until='networkidle')
    assert page.url==origin+'/kilas-translator?mode=voiceover';expect(page.locator('#voiceover-panel')).to_be_visible();expect(page.locator('#translate-panel')).to_be_hidden()
    results.append({'closed_from':path,'actual_chromium_profile_reopen':'PASS','main_url_home':'PASS','voiceover_refresh_preserved':'PASS'})
   page.goto(origin+'/logout');assert page.url==origin+'/login';c.close();c,page=launch();page.goto(origin+'/');assert page.url==origin+'/login';c.close()
   assert not errors and not paid,(errors,paid)
  result={'result':'PASS','cases':results,'logout_stays_logged_out_after_reopen':True,'paid_calls':0,'production_mutations':0,'physical_android':False}
  output=Path(os.environ.get('CUSTOMER_AUTH_QA_DIR','/tmp/customer-auth-qa'));output.mkdir(parents=True,exist_ok=True);(output/'browser.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 finally:server.shutdown();worker.join(3);case.doCleanups()

if __name__=='__main__':main()
