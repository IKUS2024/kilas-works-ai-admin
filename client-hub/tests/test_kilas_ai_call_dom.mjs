// Actual Flask-rendered pages in jsdom; no browser or microphone capture.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const pages=JSON.parse(readFileSync(process.env.KILAS_AI_CALL_UI_FIXTURE_PATH,'utf8'));
const {JSDOM}=createRequire(pathToFileURL(join(process.env.KILAS_UI_DOM_TOOLS||'/tmp/kilas-gemini-dom','package.json')))('jsdom');
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
for(const locale of ['en','id','es','zh'])test(`Call ${locale} actual chat placement, import idle, explicit modal and background cleanup`,async t=>{
 const dom=new JSDOM(pages[locale],{url:'https://app.example.test/kilas-ai',runScripts:'outside-only',pretendToBeVisual:true});
 t.after(()=>dom.window.close());const {window}=dom,{document}=window;
 window.eval(readFileSync(new URL('../static/ui_i18n.js',import.meta.url),'utf8'));
 const button=document.querySelector('[data-ai-call-launch]'),dialog=document.querySelector('#ai-call-dialog'),end=document.querySelector('#ai-call-end');
 assert.equal(button.type,'button');assert.ok(button.nextElementSibling.matches('.ai-send[type=submit]'));assert.equal(button.closest('form').querySelector('[name=csrf_token]')?.value,'audio-csrf');
 assert.equal(dialog.getAttribute('aria-describedby'),'ai-call-privacy');assert.ok(end.getAttribute('aria-label'));assert.equal(document.querySelectorAll('#ai-call-dialog').length,1);
 assert.equal(dialog.querySelectorAll('audio,video').length,0);
 let microphones=0,contexts=0,requests=0;
 dialog.showModal=()=>{dialog.setAttribute('open','');};dialog.close=()=>{dialog.removeAttribute('open');dialog.dispatchEvent(new window.Event('close'));};
 const values={window,document,KilasUI:window.KilasUI,FormData:window.FormData,
  navigator:{mediaDevices:{getUserMedia(){microphones++;throw Error('Forbidden media QA');}},sendBeacon(){throw Error('No provider admission');}},
  fetch:async()=>{requests++;return {ok:true,redirected:false,json:async()=>({available:false,reason:'budget_limit'})};}};
 window.AudioContext=class{constructor(){contexts++;this.state='running';}resume(){return Promise.resolve();}close(){return Promise.resolve();}addEventListener(){}};
 const previous={};for(const [key,value] of Object.entries(values)){previous[key]=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});}
 t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}});
 await import('../static/kilas_ai_call.mjs?dom-'+locale);await tick();
 assert.equal(microphones,0);assert.equal(contexts,0);assert.equal(requests,0);assert.equal(dialog.open,false);
 button.click();await tick();assert.equal(dialog.open,true);assert.equal(document.activeElement,end);assert.equal(contexts,1);assert.equal(microphones,0);assert.equal(requests,1);
 assert.equal(dialog.querySelector('#ai-call-error').textContent,window.KilasUI.t('Batas biaya tercapai. Panggilan dihentikan.'));
 assert.equal(dialog.dataset.state,'ended');
 document.dispatchEvent(new window.Event('visibilitychange'));await tick();assert.equal(dialog.open,true);
 Object.defineProperty(document,'hidden',{value:true,configurable:true});document.dispatchEvent(new window.Event('visibilitychange'));assert.equal(dialog.open,false);assert.equal(document.body.classList.contains('kilas-ai-call-open'),false);
 button.click();await tick();window.dispatchEvent(new window.Event('pagehide'));assert.equal(dialog.open,false);assert.equal(microphones,0);
});
