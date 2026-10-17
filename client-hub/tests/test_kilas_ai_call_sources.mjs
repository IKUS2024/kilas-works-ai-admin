import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {join} from 'node:path';
import {renderCallSources} from '../static/kilas_ai_call_sources.mjs';
const {JSDOM}=createRequire(pathToFileURL(join(process.env.KILAS_UI_DOM_TOOLS||'/tmp/kilas-call-tools','package.json')))('jsdom');
test('Public citation display uses safe external links and plain text; clear removes prior sources',()=>{
 const dom=new JSDOM('<html lang="en"><div id="sources" hidden></div></html>'),container=dom.window.document.querySelector('#sources');
 renderCallSources(container,[{url:'https://example.org/news',title:'<img src=x onerror=alert(1)>'}], '2026-10-17');
 assert.equal(container.hidden,false);assert.equal(container.querySelectorAll('img,script').length,0);
 const link=container.querySelector('a');assert.equal(link.href,'https://example.org/news');assert.equal(link.textContent,'example.org');
 assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.referrerPolicy,'no-referrer');
 assert.ok(container.textContent.includes('Sources checked · 2026-10-17'));
 renderCallSources(container,[]);assert.equal(container.hidden,true);assert.equal(container.childNodes.length,0);dom.window.close();
});
test('Unsafe URLs, embedded credentials and invalid dates cannot become actionable sources',()=>{
 const dom=new JSDOM('<html lang="id"><div id="sources"></div></html>'),container=dom.window.document.querySelector('#sources');
 renderCallSources(container,[{url:'javascript:alert(1)',title:'unsafe'},{url:'data:text/html,bad',title:'unsafe'},
  {url:'https://private:credential@example.org',title:'unsafe'}]);
 assert.equal(container.hidden,true);assert.equal(container.querySelectorAll('a').length,0);
 renderCallSources(container,[{url:'https://example.org',title:'source'}],'not-a-date');
 assert.ok(container.textContent.includes('Sumber diperiksa'));assert.ok(!container.textContent.includes('not-a-date'));dom.window.close();
});
test('Source metadata is limited to three visible links in supported UI languages',()=>{
 for(const [lang,label] of [['en','Sources checked'],['id','Sumber diperiksa'],['es','Fuentes consultadas'],['zh','已查阅来源']]){
  const dom=new JSDOM(`<html lang="${lang}"><div id="sources"></div></html>`),container=dom.window.document.querySelector('#sources');
  renderCallSources(container,Array.from({length:8},(_,i)=>({url:`https://example.org/${i}`,title:'source'})),'2026-10-17');
  assert.equal(container.querySelectorAll('a').length,3);assert.ok(container.textContent.includes(label));dom.window.close();
 }
});
