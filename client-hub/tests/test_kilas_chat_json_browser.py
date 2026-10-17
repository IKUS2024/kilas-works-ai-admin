"""Chat JSON/source/copy safety in real Chromium. Static fixture, no provider IO."""
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
SOURCE=json.dumps({'remaining_units':264,'full_packs':37,'loose_units':5,'invoice_id':'QA-017','due_date':'2026-10-31','currency':'USD','total':38.00,'bank_account':None,
 'python':'def pack_count(cartons,per_carton,sold,reserved,pack_size):\n    remaining = cartons * per_carton - sold - reserved\n    return divmod(remaining, pack_size)',
 'unsafe':'<img src=x onerror="window.injected=1"> <script>window.injected=1</script> $x_i$ [bad](javascript:alert(1))'},separators=(',',':'))
HTML='''<!doctype html><meta charset=utf-8><div class="ai-shell"><main class="ai-main"><div id="ai-messages" class="ai-messages"><article class="ai-message ai-assistant"><div class="ai-message-text" id="answer"></div><button class="ai-copy">Copy</button></article></div></main><form id="ai-composer"><textarea id="ai-input"></textarea><input id="ai-files" type=file><div id="ai-pending"></div><button id="ai-send"></button><button id="ai-stop" hidden></button></form><div id="ai-notice"></div><div id="ai-title"></div><div id="ai-thread-menu"></div><div class="ai-empty"></div><template id="ai-copy-icon"><svg><path></path></svg></template></div><script src="/kilas_ai_markdown.js"></script><script src="/kilas_ai.js"></script>'''
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path=='/':body=HTML.encode();typ='text/html'
  elif self.path in ('/kilas_ai_markdown.js','/kilas_ai.js'):body=(ROOT/'static'/self.path[1:]).read_bytes();typ='text/javascript'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',typ);self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass

def main():
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 origin=f'http://127.0.0.1:{server.server_port}';results=[]
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
   for width in (390,1440):
    ctx=browser.new_context(viewport={'width':width,'height':900},permissions=['clipboard-read','clipboard-write']);page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort());page.goto(origin,wait_until='networkidle')
    data=page.evaluate('''async source=>{const e=document.querySelector('#answer');KilasMarkdown.render(e,'');
     for(let i=0;i<source.length;i+=7){KilasMarkdown.stream(e,source.slice(i,i+7));await new Promise(requestAnimationFrame);if(e.querySelector('em,strong,a,img,script,.katex'))throw Error('JSON interpreted as markup while streaming');}
     KilasMarkdown.finish(e);if(e.querySelector('pre code').textContent!==source||KilasMarkdown.source(e)!==source)throw Error('literal/source mismatch');
     const stable=e.firstChild;KilasMarkdown.finish(e);if(e.firstChild!==stable)throw Error('unstable final JSON');
     KilasMarkdown.render(e,source);if(e.querySelector('pre code').textContent!==source)throw Error('reload projection mismatch');
     return {sourceExact:KilasMarkdown.source(e)===source,noInjectedHTML:!e.querySelector('em,a,img,script,.katex'),safe:window.injected===undefined};}''',SOURCE)
    page.locator('.ai-copy').click();copied=page.evaluate('navigator.clipboard.readText()');assert copied==SOURCE
    # Other Chat formatting and fenced code remain available.
    checks=page.evaluate('''()=>{const e=document.createElement('div');e.className='agent-message-text';document.body.append(e);KilasMarkdown.render(e,'**bold** and *emphasis*');const prose=Boolean(e.querySelector('strong')&&e.querySelector('em'));KilasMarkdown.render(e,'```python\\ndef pack_count(per_carton):\\n    return per_carton\\n```');const fenced=e.querySelector('pre code').textContent==='def pack_count(per_carton):\\n    return per_carton';KilasMarkdown.render(e,'[{"full_packs":37,"loose_units":5}]');const array=e.querySelector('pre code').textContent==='[{"full_packs":37,"loose_units":5}]';return {prose,fenced,array};}''')
    assert all(data.values()) and all(checks.values()) and not errors,(data,checks,errors)
    results.append({'width':width,**data,**checks,'realClipboardExact':True});ctx.close()
   browser.close()
  print(json.dumps({'result':'PASS','cases':results,'paid_provider_calls':0}))
 finally:server.shutdown()
if __name__=='__main__':main()
