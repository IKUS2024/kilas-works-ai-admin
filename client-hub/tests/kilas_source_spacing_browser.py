"""Saved/stream-style citation rows preserve content/links and wrap with gaps."""
import json
import os
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
import test_kilas_home as home
from kilas_ai import store


def main():
    case=home.HomeTests('test_old_routes_still_render');case.id=lambda:'source-spacing-browser';case.setUp()
    ident=store.create_thread(case.owner)
    citations=[{'title':'example.test','url':'https://example.test/source-a'},{'title':'LongSourceTitleWithoutSpaces'+('synthetic'*18),'url':'https://example.test/source-b'},{'title':'Another source','url':'https://example.test/source-c'}]
    store.append_assistant(case.owner,ident,'Synthetic cited answer.','FAST','synthetic','gpt-6.1-sol','sources_fixture',{'citations':citations})
    client=case.client();html=client.get(f'/kilas-ai/threads/{ident}').text
    for entry in citations:assert entry['title'] in html and entry['url'] in html
    assert html.count('rel="noopener noreferrer nofollow"')>=3
    server=make_server('127.0.0.1',0,client.application,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
    output=Path(tempfile.gettempdir())/'kilas-source-spacing-browser';output.mkdir(exist_ok=True);report=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('KILAS_QA_CHROMIUM','/usr/bin/chromium'),args=['--no-sandbox'])
            for width in (320,360,768,1440):
                context=browser.new_context(viewport={'width':width,'height':900});cookie=client.get_cookie('session');context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':origin},{'name':'kilas_language','value':'en','url':origin}]);context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin) else r.abort())
                page=context.new_page();errors=[];posts=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
                page.goto(origin+f'/kilas-ai/threads/{ident}',wait_until='networkidle');page.evaluate('document.fonts.ready')
                for variant in ('saved','dynamic'):
                    row=page.locator('.ai-sources').last;expect(row.locator('strong')).to_have_text('Sources');expect(row.locator('a')).to_have_count(3)
                    for link,entry in zip(row.locator('a').all(),citations):
                        expect(link).to_have_text(entry['title']);expect(link).to_have_attribute('href',entry['url']);expect(link).to_have_attribute('target','_blank');expect(link).to_have_attribute('rel','noopener noreferrer nofollow')
                    metrics=row.evaluate('e=>{const l=e.querySelector("strong").getBoundingClientRect(),a=[...e.querySelectorAll("a")].map(n=>n.getBoundingClientRect());return {gap:a[0].left-l.right,rowGap:a[1].top-Math.max(l.bottom,a[0].bottom),width:e.getBoundingClientRect().width,overflow:e.scrollWidth>e.clientWidth}}')
                    assert abs(metrics['gap']-8)<=.1 and metrics['rowGap']>=3.9 and not metrics['overflow'],metrics
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    report.append({'width':width,'variant':variant,**metrics,'links_preserved':True})
                    if variant=='saved':
                        if width in (320,1440):row.screenshot(path=str(output/f'sources-{width}.png'))
                        page.evaluate('entries=>{const box=document.createElement("div");box.className="ai-sources";const label=document.createElement("strong");label.textContent="Sources";box.append(label);for(const entry of entries){const a=document.createElement("a");a.href=entry.url;a.textContent=entry.title;a.target="_blank";a.rel="noopener noreferrer nofollow";box.append(a)}document.querySelector(".ai-message.ai-assistant").append(box)}',citations)
                assert not errors and not posts,(errors,posts);print(f'PASS source gap/wrap/content/links saved+dynamic {width}',flush=True);context.close()
            browser.close()
        (output/'verification.json').write_text(json.dumps(report,indent=2))
    finally:server.shutdown();case.doCleanups()


if __name__=='__main__':main()
