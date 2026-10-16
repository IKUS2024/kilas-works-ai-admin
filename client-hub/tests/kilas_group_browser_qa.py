"""Run separately: real desktop/mobile Chromium, synthetic users/provider only."""
import os,sys,threading,uuid,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.update(CLIENT_HUB_DB_PATH=tempfile.mktemp(prefix='kilas-group-browser-',suffix='.sqlite'),SECRET_KEY='group-browser-qa-only',KILAS_AI_ENABLED='true')
os.environ.pop('DATABASE_URL',None)
import app,repo,security,customer_auth
from kilas_ai import group_chat as groups,providers
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright,expect
application=app.app
owner,member=[repo.create_user(uuid.uuid4().hex+'@example.test',security.hash_password('test-password'),full_name=name) for name in ('Owner QA','Member QA')]
ident=groups.create(owner,'Team discussion');token=groups.invitation(owner,ident);groups.join(member,token)
server=make_server('127.0.0.1',0,application,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
base='http://127.0.0.1:'+str(server.server_port)
def login(context,user):
 with application.test_request_context():
  auth=customer_auth.create(repo.get_user_by_id(user));value=application.session_interface.get_signing_serializer(application).dumps(dict(user_id=user,role='CLIENT_OWNER',_customer_session=auth,_csrf_token='browser-csrf'))
 context.add_cookies([{'name':'session','value':value,'url':base},{'name':'kilas_language','value':'en','url':base}])
def events(*a,**kw):
 yield from [{'type':'provider','provider':'openai','model':'gpt-6-luna'},{'type':'delta','text':'Decision: choose option A. Action: prepare the draft.'},{'type':'usage','input_tokens':100,'output_tokens':20},{'type':'finish','reason':'stop'}]
output=Path('/tmp/kilas-group-browser-evidence');output.mkdir(exist_ok=True)
try:
 with patch.object(providers,'stream',side_effect=events) as provider,patch('requests.sessions.Session.request',side_effect=AssertionError('No provider IO')),sync_playwright() as p:
  browser=p.chromium.launch(executable_path=os.environ.get('KILAS_GROUP_BROWSER','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
  errors=[]
  owner_context=browser.new_context(viewport={'width':1280,'height':900});member_context=browser.new_context(viewport={'width':375,'height':812},is_mobile=True,has_touch=True)
  login(owner_context,owner);login(member_context,member)
  a=owner_context.new_page();b=member_context.new_page()
  for page in (a,b):page.on('pageerror',lambda error:errors.append(str(error)))
  a.goto(base+f'/kilas-ai/groups/{ident}');b.goto(base+f'/kilas-ai/groups/{ident}')
  expect(a.locator('#group-members')).to_contain_text('Member QA')
  a.locator('#group-input').fill('We agree to use option A.');a.locator('#group-send').click()
  expect(b.locator('#group-messages')).to_contain_text('We agree to use option A.',timeout=10000)
  b.locator('#group-input').fill('@Kilas, list the action.');b.locator('#group-send').click()
  expect(b.locator('#group-messages')).to_contain_text('Decision: choose option A.',timeout=10000)
  expect(a.locator('#group-messages')).to_contain_text('Decision: choose option A.',timeout=10000)
  a.locator('#group-summary').click();expect(a.locator('#group-ai-count')).to_have_text('2',timeout=10000)
  a.locator('#group-details').evaluate('e=>e.open=true');a.locator('#group-ai-enabled').uncheck()
  expect(b.locator('#group-ask')).to_be_disabled(timeout=10000)
  a.locator('#group-invite').click();expect(a.locator('#group-invite-url')).not_to_have_value('');invite=a.locator('#group-invite-url').input_value()
  anonymous=browser.new_context();visitor=anonymous.new_page();visitor.goto(invite)
  expect(visitor.locator('body')).not_to_contain_text('We agree');expect(visitor.locator('body')).not_to_contain_text('Team discussion')
  a.locator('#group-details').evaluate('e=>e.open=false')
  for page,name in ((a,'desktop'),(b,'mobile')):
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),name
   page.screenshot(path=str(output/(name+'.png')),full_page=True)
  a.on('dialog',lambda dialog:dialog.accept());a.locator('#group-details').evaluate('e=>e.open=true');a.get_by_role('button',name='Remove member').click()
  expect(b.locator('#group-composer')).to_be_hidden(timeout=10000);expect(b.locator('#group-messages')).to_be_empty();expect(b.locator('#group-status')).to_contain_text('access was revoked')
  a.goto(base+'/kilas-ai');expect(a.locator('.group-chat-tabs')).to_be_visible();expect(a.locator('#ai-input')).to_be_visible()
  assert not errors,errors
  assert provider.call_count==2,provider.call_count
  browser.close();print('PASS browser: desktop/mobile text sync, explicit AI, summary, owner pause, invitation privacy, removal clears history, personal tabs/composer, no horizontal overflow or JS errors. Screenshots: '+str(output))
finally:server.shutdown()
