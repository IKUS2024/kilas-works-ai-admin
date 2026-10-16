// Actual Flask sidebar HTML, native details and desktop/mobile drawer logic.
// jsdom only: no browser, real layout, microphone or paid provider requests.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const pages=JSON.parse(readFileSync(process.env.KILAS_SIDEBAR_PRODUCTS_FIXTURE_PATH,'utf8'));
const {JSDOM}=createRequire(pathToFileURL(join(process.env.KILAS_UI_DOM_TOOLS||'/tmp/kilas-gemini-dom','package.json')))('jsdom');
for(const width of [390,1280])for(const locale of ['en','id','es','zh'])test(`Products ${locale},${width}px drawer keeps Finance nested, draft-safe and keyboard reachable`,t=>{
 const dom=new JSDOM(pages['home_'+locale],{url:'https://app.example.test/products/start',runScripts:'outside-only',pretendToBeVisual:true});t.after(()=>dom.window.close());
 const {window}=dom,{document}=window;window.innerWidth=width;
 for(const file of ['kilas_chat_sidebar.css','kilas_revision_shell.css']){const style=document.createElement('style');style.textContent=readFileSync(new URL('../static/'+file,import.meta.url),'utf8');document.head.append(style);}
 window.matchMedia=()=>({matches:width>=761,addEventListener(){}});window.fetch=()=>{throw Error('Navigation must not fetch on load/toggle');};
 const rail=document.querySelector('[data-chat-sidebar]'),library=rail.querySelector('.chat-library-entry'),products=rail.querySelector('.chat-products'),form=products.querySelector('form'),summary=products.querySelector('summary');
 assert.equal(library.nextElementSibling,products);assert.equal(products.nextElementSibling.tagName,'H2');assert.equal(summary.textContent.trim(),{en:'Products',id:'Produk',es:'Productos',zh:'产品'}[locale]);
 assert.equal(products.open,true);assert.equal(form.method,'post');assert.equal(new URL(form.action).pathname,'/products/start');assert.equal(form.querySelector('[name=product]').value,'finance');assert.equal(form.querySelector('[name=csrf_token]').value,'work-csrf');assert.equal(form.querySelector('button').textContent.trim(),'Finance');
 assert.equal(document.querySelector('.home-task-choices [name=product][value=finance]'),null);
 assert.deepEqual([...document.querySelectorAll('.home-task-choices > * > span')].map(x=>x.textContent.trim()).filter(Boolean),['AI Chat','Translator','Voice Over']);
 assert.equal(window.getComputedStyle(form.querySelector('button')).minHeight,'44px');
 window.eval(readFileSync(new URL('../static/kilas_premium.js',import.meta.url),'utf8'));
 window.eval(readFileSync(new URL('../static/kilas_chat_sidebar.js',import.meta.url),'utf8'));
 const sidebar=rail.closest('#premium-sidebar'),trigger=document.querySelector('[data-premium-menu]');assert.equal(sidebar.inert,width<761);
 if(width<761){trigger.click();assert.equal(sidebar.inert,false);assert.equal(trigger.getAttribute('aria-expanded'),'true');}
 const input=document.querySelector('#ai-input');input.value='Unsent draft';let confirmations=0;window.confirm=()=>{confirmations++;return false;};
 summary.click();assert.equal(products.open,false);assert.equal(window.getComputedStyle(form).display,'none');summary.click();assert.equal(products.open,true);assert.equal(confirmations,0);
 const cancelled=new window.Event('submit',{bubbles:true,cancelable:true});assert.equal(form.dispatchEvent(cancelled),false);assert.equal(confirmations,1);assert.equal(input.value,'Unsent draft');
 window.confirm=()=>true;const allowed=new window.Event('submit',{bubbles:true,cancelable:true});assert.equal(form.dispatchEvent(allowed),true);
 const unload=new window.Event('beforeunload',{cancelable:true});window.dispatchEvent(unload);assert.equal(unload.defaultPrevented,false);
 if(width<761){document.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(sidebar.inert,true);assert.equal(trigger.getAttribute('aria-expanded'),'false');assert.equal(document.activeElement,trigger);}else assert.equal(sidebar.inert,false);
});
