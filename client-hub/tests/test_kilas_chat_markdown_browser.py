"""Incremental/final math Markdown on real local chat pages; synthetic SSE, no providers."""
import sys,os,json,logging,threading,shutil
from pathlib import Path

def local_only(event,args):
 if event=='socket.connect' and isinstance(args[1],tuple) and args[1][0] not in ('127.0.0.1','::1','localhost'):raise AssertionError('External transport forbidden')
 if event=='socket.getaddrinfo' and args[0] not in ('127.0.0.1','::1','localhost',None):raise AssertionError('External DNS forbidden')
sys.addaudithook(local_only)
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_home as fixture
from kilas_ai import store,agent_store

TEXT=r'''## Synthetic reasoning

**Progressive bold** and *emphasis* with a [safe source](https://example.test/proof).

- Domain \(x\ge\frac{1}{2}\).
- Calculation $x_i^2+1=2$.

\[
\begin{aligned}
f(x)&=\sqrt{x+1}\\
P&=\frac{\binom{6}{2}}{\binom{9}{2}}
\end{aligned}
\]

```python
literal = "<img src=x onerror=alert(1)> and \\(x_1\\)"
print(literal)
```

| Expression | Literal |
|---|---|
| $|x|$ | `a|b` |

A price is $10 or $20. <img src=x onerror="window.qaInjected=1">
'''

TEXT=TEXT.replace('\\\\','\\')

MOCK=r'''({text,agent})=>{const original=fetch;window.qaFrames=[];window.fetch=(url,options)=>{
 if(options?.method==='POST'&&(String(url).endsWith('/send')||String(url).endsWith('/agent/chat'))){
  return Promise.resolve(new Response(new ReadableStream({start(controller){
   const encoder=new TextEncoder();window.qaPart=chunk=>controller.enqueue(encoder.encode(agent?'data: '+JSON.stringify({type:'delta',text:chunk})+'\n\n':'event: delta\ndata: '+JSON.stringify({text:chunk})+'\n\n'));
   window.qaReset=()=>controller.enqueue(encoder.encode(agent?'data: {"type":"reset"}\n\n':'event: reset\ndata: {}\n\n'));
   window.qaDone=()=>{controller.enqueue(encoder.encode(agent?'data: {"type":"done"}\n\n':'event: done\ndata: {}\n\n'));controller.close();};
   options.signal?.addEventListener('abort',()=>controller.error(new DOMException('Aborted','AbortError')));
  }}),{headers:{'Content-Type':'text/event-stream'}}));
 }return original(url,options);
};}'''


def main():
 logging.getLogger('werkzeug').setLevel(logging.ERROR)
 case=fixture.HomeTests('test_old_routes_still_render');case.id=lambda:'stream-math-browser';case.setUp()
 app=fixture.fixture.base.f.fixture.app.app
 thread=store.create_thread(case.owner);store.append_user_once(case.owner,thread,'Synthetic question','SMART','markdown-fixture')
 agent_store.append(case.owner,'user','Synthetic question',case.conversation)
 server=make_server('127.0.0.1',0,app,threaded=True);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();origin=f'http://127.0.0.1:{server.server_port}'
 output=Path(os.environ.get('KILAS_MARKDOWN_QA_DIR','/tmp/kilas-markdown-qa'));output.mkdir(parents=True,exist_ok=True);results=[]
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox','--disable-background-networking'])
   cookie=case.client().get_cookie('session')
   for width,height in ((390,844),(820,1024),(1440,900)):
    for agent in (False,True):
     context=browser.new_context(viewport={'width':width,'height':height},has_touch=width<761,reduced_motion='reduce');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=context.new_page();errors=[];external=[]
     page.on('pageerror',lambda error:errors.append(str(error)))
     def route(r):
      if r.request.url.startswith(origin):r.continue_()
      else:external.append(r.request.url);r.abort()
     page.route('**/*',route)
     url=origin+('/kilas-ai/agent?conversation='+str(case.conversation) if agent else '/kilas-ai/threads/'+str(thread))
     page.goto(url,wait_until='networkidle');page.evaluate(MOCK,{'text':TEXT,'agent':agent})
     field=page.locator('#agent-message' if agent else '#ai-input');field.fill('Synthetic formatting test')
     page.locator('#agent-chat-form button[type=submit]' if agent else '#ai-send').click();page.wait_for_function('Boolean(window.qaPart)')
     selector=('.agent-message-assistant .agent-message-text' if agent else '.ai-assistant .ai-message-text');body=page.locator(selector).last
     prefix='## Synthetic reasoning\n\n**Progressive bold**\n\n';page.evaluate('text=>qaPart(text)',prefix)
     expect(body.locator('strong')).to_have_text('Progressive bold');expect(body.locator('h3')).to_have_text('Synthetic reasoning')
     # Same buffered answer resets safely, then arrives across delimiter/code chunk boundaries.
     page.evaluate('qaReset()');page.wait_for_timeout(30)
     chunks=[TEXT[i:i+7] for i in range(0,len(TEXT),7)]
     for chunk in chunks:page.evaluate('text=>qaPart(text)',chunk)
     expect(body.locator('.katex')).to_have_count(4,timeout=10000)
     assert body.locator('[data-math-error]').count()==0
     expect(body.locator('pre code')).to_have_text('literal = "<img src=x onerror=alert(1)> and \\(x_1\\)"\nprint(literal)')
     assert body.locator('table tr').last.locator('td').count()==2
     assert page.evaluate('window.qaInjected===undefined') and body.locator('img,script,iframe').count()==0
     assert 'A price is $10 or $20.' in body.inner_text()
     page.wait_for_timeout(60)
     before=body.inner_html();source=body.evaluate('e=>KilasMarkdown.source(e)');assert source==TEXT
     # Real server reload projection for the Agent path contains the same synthetic final answer.
     if agent:agent_store.append(case.owner,'assistant',TEXT,case.conversation)
     page.evaluate('qaDone()');expect(page.locator('#agent-chat-form button[type=submit]' if agent else '#ai-send')).to_be_enabled(timeout=10000)
     body=page.locator(selector).last;expect(body.locator('.katex')).to_have_count(4);assert body.evaluate('e=>KilasMarkdown.source(e)')==TEXT.rstrip() if agent else body.evaluate('e=>KilasMarkdown.source(e)')==TEXT
     assert body.inner_html()==before
     page.evaluate('document.fonts.ready');page.screenshot(path=str(output/f'{"agent" if agent else "legacy"}-{width}.png'))
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,agent)
     assert not errors and not external,(errors,external)
     # Renderer malformed/failure safety and coalescing, independent of provider behavior.
     data=page.evaluate(r'''async()=>{const e=document.createElement('div');e.className='ai-message-text';document.querySelector('main').append(e);
      KilasMarkdown.render(e,'\\[broken');const bounded=e.textContent.includes('broken')&&!e.querySelector('[data-math-incomplete]');
      KilasMarkdown.render(e,'\\(\\href{javascript:alert(1)}{bad}\\) <script>window.qaInjected=2</script>');const safe=!e.querySelector('a,script,img,iframe');
      let renders=0;e.addEventListener('kilas:rendered',()=>renders++);KilasMarkdown.render(e,'');renders=0;
      for(let i=0;i<200;i++)KilasMarkdown.stream(e,'word ');await new Promise(requestAnimationFrame);const coalesced=renders===1;
      const stable=e.firstChild;KilasMarkdown.finish(e);const finalStable=e.firstChild===stable;
      e.remove();return {bounded,safe,coalesced,finalStable};}''')
     assert all(data.values()),data
     results.append({'width':width,'shell':'agent' if agent else 'legacy','formatted_before_done':True,'math_code_table_safe':True,'final_dom_consistent':True,'source_preserved':True,**data});context.close()
   # A failed local math asset cannot leave the answer pending indefinitely.
   context=browser.new_context(viewport={'width':390,'height':844});context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin}]);page=context.new_page()
   page.route('**/*',lambda route:route.abort() if '/vendor/katex-0.19.0/katex.min.js' in route.request.url or not route.request.url.startswith(origin) else route.continue_())
   page.goto(origin+'/kilas-ai/threads/'+str(thread),wait_until='networkidle')
   page.evaluate(r"""()=>{const e=document.createElement('div');e.id='math-asset-failure';e.className='ai-markdown';document.querySelector('main').append(e);KilasMarkdown.render(e,'\\(x^2+1\\)');}""")
   expect(page.locator('#math-asset-failure [data-math-error]')).to_have_count(1)
   assert page.locator('#math-asset-failure [data-math-pending]').count()==0
   assert 'x^2+1' in page.locator('#math-asset-failure').inner_text()
   context.close()
   browser.close()
  report={'result':'PASS','cases':results,'paid_provider_calls':0,'production_mutations':0,'physical_android':False};(output/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
 finally:server.shutdown();worker.join(3);case.doCleanups()

if __name__=='__main__':main()
