"""Real Send -> durable user media -> reload; synthetic providers and private fixtures."""
import io,json,threading,time,re
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_model_preferences as f
from kilas_ai import providers,store,agent_store,agent_attachments,usage


def main():
 case=f.PreferenceTests('test_unsent_home_choice_survives_new_authenticated_sessions_and_reopening');case.setUp()
 app=f.fixture.fixture.fixture.base.f.fixture.app.app
 server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
 output=Path('/tmp/kilas-sent-attachments-browser');output.mkdir(exist_ok=True);report=[]
 raw=io.BytesIO();Image.new('RGB',(480,320),'#dfb990').save(raw,'PNG');image=raw.getvalue()
 failure={'on':False}
 files=[{'name':'12345.jpg.png','mimeType':'image/png','buffer':image},{'name':'second-67890.png','mimeType':'image/png','buffer':image},{'name':'notes.txt','mimeType':'text/plain','buffer':b'Synthetic attachment note.'}]
 def answer(*args,**kwargs):
  time.sleep(.2)
  if failure['on']:raise providers.ProviderError('synthetic_failure')
  yield {'type':'provider','provider':'openai','model':'gpt-6-luna'}
  yield {'type':'delta','text':'Synthetic attachment reply.'}
  yield {'type':'finish','reason':'stop'}
 try:
  with patch.object(usage,'attachment_plan',return_value='PRO'),patch.object(providers,'stream',side_effect=answer),sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
   for width in (320,820,1440):
    for agent in (False,True):
     kind='agent' if agent else 'thread'
     # New owned chats avoid carrying prior browser fixture attachment quotas.
     thread=store.create_thread(case.owner);conversation=agent_store.new_conversation(case.owner)
     path=f'/kilas-ai/agent?conversation={conversation}' if agent else '/products/start' if width==1440 else f'/kilas-ai/threads/{thread}'
     case.choose('chat','gpt-6-luna',surface='conversation' if agent else 'thread',conversation_id=conversation if agent else thread)
     context=browser.new_context(viewport={'width':width,'height':900});cookie=case.client().get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);page=context.new_page();errors=[];posts=[];reject={'on':True};uncertain={'on':False};keys=[]
     page.on('pageerror',lambda e:errors.append(str(e)))
     def route(r):
      if not r.request.url.startswith(origin):r.abort();return
      if r.request.method=='POST' and (r.request.url.endswith('/send') or r.request.url.endswith('/agent/chat')):
       posts.append(r.request.url)
       found=re.search(rb'name="operation_key"\r\n\r\n([^\r]+)',r.request.post_data_buffer or b'')
       if found:keys.append(found[1].decode())
       if reject['on']:r.fulfill(status=400,content_type='application/json',body='{"error":"Synthetic send rejected"}');return
       if uncertain['on']:uncertain['on']=False;r.abort('failed');return
      r.continue_()
     page.route('**/*',route);page.goto(origin+path,wait_until='networkidle')
     field=page.locator('#agent-message' if agent else '#ai-input');picker=page.locator('#work-source-files' if agent else '#ai-files');send=page.locator('#agent-chat-form button[type=submit]' if agent else '#ai-send');timeline=page.locator('#agent-conversation' if agent else '#ai-messages');pending=page.locator('#work-pending-files' if agent else '#ai-pending')
     # Both fixtures use PLUS capacity (up to three files); UI removal is checked first.
     picker.set_input_files(files[:2]);expect(pending.locator('.chat-upload-image')).to_have_count(2)
     assert '12345' not in pending.inner_text() and '.png' not in pending.inner_text()
     pending.locator('button').first.click();expect(pending.locator('.chat-upload-image')).to_have_count(1)
     picker.set_input_files([files[0],files[2]])
     expect(pending.locator('button')).to_have_count(3)
     field.fill('Keep this exact user caption.');send.click()
     expect(send).to_be_enabled();expect(pending.locator('button')).to_have_count(3);expect(field).to_have_value('Keep this exact user caption.')
     expect(timeline.locator('.chat-user-attachments')).to_have_count(0)
     reject['on']=False
     if not agent:
      uncertain['on']=True;send.click();expect(send).to_be_enabled();expect(pending.locator('button')).to_have_count(3)
     send.click();expect(pending.locator('button')).to_have_count(0)
     user=timeline.locator('.agent-message-user' if agent else '.ai-user').last
     expect(user.locator('.chat-user-attachments .chat-upload-image')).to_have_count(2)
     expect(user.locator('.ai-file-card')).to_have_count(1)
     expect(user.locator('.ai-file-card')).to_contain_text('notes.txt')
     expect(user.locator('.agent-message-text' if agent else '.ai-message-text')).to_have_text('Keep this exact user caption.')
     expect(send).to_be_enabled();page.wait_for_timeout(150)
     if not agent:thread=int(page.locator('.ai-shell').get_attribute('data-thread-id'))
     expect(user.locator('.chat-upload-image').first).to_have_attribute('href',__import__('re').compile(r'^/kilas-ai/threads/\d+/attachments/\d+\?inline=1$'))
     for picture in user.locator('.chat-upload-image').all():
      assert not picture.inner_text().strip()
      assert picture.locator('img').evaluate('e=>e.complete&&e.naturalWidth>0')
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
     page.screenshot(path=str(output/f'{kind}-{width}-sent.png'))
     urls=user.locator('.chat-upload-image').evaluate_all('nodes=>nodes.map(e=>e.getAttribute("href"))')
     for url in urls:
      response=context.request.get(origin+url);assert response.status==200 and response.headers['cache-control']=='private, no-store'
      assert case.client(case.other).get(url).status_code==404
     page.reload(wait_until='networkidle');user=page.locator('.agent-message-user' if agent else '.ai-user').last
     expect(user.locator('.chat-upload-image')).to_have_count(2);expect(user.locator('.ai-file-card')).to_have_count(1)
     assert urls==user.locator('.chat-upload-image').evaluate_all('nodes=>nodes.map(e=>e.getAttribute("href"))')
     expect(user.locator('.ai-file-card a')).to_have_count(1)
     if agent:
      messages=agent_store.messages(case.owner,conversation_id=conversation);saved=agent_attachments.listing(case.owner,conversation,[m['id'] for m in messages]);count=sum(len(a) for a in saved.values())
     else:count=len(store.attachment_list(case.owner,thread))
     assert count==3,count
     assert len(keys)==len(posts) and len(set(keys))==1,keys
     if width==1440 and not agent:
      failure['on']=True;picker.set_input_files([files[0]]);field.fill('Accepted upload despite failed reply.');send.click()
      expect(send).to_be_enabled();expect(pending.locator('button')).to_have_count(0);expect(field).to_have_value('')
      accepted=timeline.locator('.ai-user').last
      expect(accepted.locator('.chat-upload-image')).to_have_count(1)
      expect(accepted.locator('.ai-message-text')).to_have_text('Accepted upload despite failed reply.')
      page.reload(wait_until='networkidle');expect(page.locator('.ai-user').last.locator('.chat-upload-image')).to_have_count(1)
      assert len(store.attachment_list(case.owner,thread))==4
      failure['on']=False
     assert not errors,errors
     report.append({'surface':kind,'width':width,'send_reload_private_urls':'PASS','images_only':'PASS','caption':'PASS','reject_preserves_pending':'PASS','remove_before_send':'PASS','stored_attachments':count,'send_posts':len(posts),'accepted_provider_error_checked':width==1440 and not agent,'page_errors':errors})
     context.close()
   browser.close()
  (output/'verification.json').write_text(json.dumps({'checks':report,'paid_inference':False},indent=2));print(json.dumps(report))
 finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
