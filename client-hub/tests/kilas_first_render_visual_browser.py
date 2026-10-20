"""Capture reproduced baseline partial paint and the fixed pre-hydration UI; offline only."""
import json,subprocess,threading
from pathlib import Path
from unittest.mock import patch
from jinja2 import ChoiceLoader,DictLoader
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import live_translator as live,audio_branded_voices as branded,translator_languages as languages
case=home.HomeTests('test_old_routes_still_render');case.setUp();app=home.fixture.base.f.fixture.app.app
original=app.jinja_env.loader
paths=subprocess.check_output(['git','diff','--name-only','4c2166724d85a34868f1c37dfc6efb8593b085e8'],text=True).splitlines()
old={p.split('client-hub/templates/',1)[1]:subprocess.check_output(['git','show','4c2166724d85a34868f1c37dfc6efb8593b085e8:'+p],text=True) for p in paths if p.startswith('client-hub/templates/')}
server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}';output=Path('/tmp/kilas-first-render-browser');output.mkdir(exist_ok=True);results=[]
try:
 with patch.object(languages,'classic_names',return_value=languages.names(languages.CLASSIC)),patch.object(live,'ready',return_value=True),patch.object(branded,'public_choices',return_value=[{'alias':'kilas-male','name':'Kilas Male'}]),sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
  for name,asset in [('baseline-partial','kilas_home.css'),('fixed-before-hydration','kilas_translator_picker.js')]:
   app.jinja_env.loader=ChoiceLoader([DictLoader(old),original]) if name.startswith('baseline') else original;app.jinja_env.cache.clear()
   context=browser.new_context(viewport={'width':390,'height':844});cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);page=context.new_page();pending=[]
   def route(r):
    if not r.request.url.startswith(origin):r.abort();return
    if asset in r.request.url:pending.append(r);return
    r.continue_()
   page.route('**/*',route);page.goto(origin+'/kilas-translator/live',wait_until='commit')
   for _ in range(50):
    page.wait_for_timeout(20)
    if pending:break
   assert pending
   page.wait_for_timeout(100);page.screenshot(path=str(output/(name+'.png')))
   before=page.locator('#live-setup-form').bounding_box() if page.locator('#live-setup-form').count() else None
   for r in pending:r.fulfill(response=r.fetch())
   page.wait_for_load_state('networkidle');after=page.locator('#live-setup-form').bounding_box()
   page.screenshot(path=str(output/(name+'-ready.png')))
   if name.startswith('fixed'):assert before==after,(before,after)
   results.append({'case':name,'before':before,'after':after,'held_asset':asset});context.close()
  browser.close()
 (output/'visual-proof.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
finally:server.shutdown();case.doCleanups()
