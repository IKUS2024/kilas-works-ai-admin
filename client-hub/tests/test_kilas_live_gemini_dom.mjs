// Real Flask HTML, synthetic read-only session transport; no browser or media.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const pages=JSON.parse(readFileSync(process.env.KILAS_GEMINI_UI_FIXTURE_PATH,'utf8'));
const {JSDOM}=createRequire(pathToFileURL(join(process.env.KILAS_UI_DOM_TOOLS||'/tmp/kilas-gemini-dom','package.json')))('jsdom');
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
for(const locale of ['en','id']){
 test(`Native ${locale} entry respects owner recovery and valid directions without microphone/provider IO`,async t=>{
  const dom=new JSDOM(pages[locale],{url:'https://app.example.test/kilas-translator/live/gemini',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());const {window}=dom,{document}=window;
  window.eval(readFileSync(new URL('../static/ui_i18n.js',import.meta.url),'utf8'));
  let active={session_id:'c'.repeat(48),processing:true},microphones=0,contexts=0;const requests=[];
  const values={window,document,KilasUI:window.KilasUI,FormData:window.FormData,
   navigator:{mediaDevices:{getUserMedia(){microphones++;throw Error('No microphone QA');}}},
   AudioContext:class{constructor(){contexts++;throw Error('No audio-context QA');}},
   fetch:async(url,options={})=>{requests.push({url,...options});assert.equal(options.method||'GET','GET');assert.ok(url.endsWith('/live/sessions/active'));return {ok:true,redirected:false,json:async()=>({session:active})};}};
  const previous={};for(const [key,value] of Object.entries(values)){previous[key]=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});}
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}});
  await import('../static/kilas_live_gemini.mjs?dom-'+locale);await tick();
  const start=document.querySelector('#live-setup-form [type=submit]'),first=document.querySelector('[name=language_a]'),second=document.querySelector('[name=language_b]');
  assert.equal(start.disabled,true);assert.equal(document.querySelector('#live-recovery').hidden,false);
  assert.equal(document.querySelector('#live-recovery-status').textContent,locale==='en'?'The previous session is still active.':'Sesi sebelumnya masih aktif.');
  assert.equal(requests.length,1);assert.equal(microphones,0);assert.equal(contexts,0);
  active=null;document.querySelector('#live-recovery-check').click();await tick();assert.equal(start.disabled,false);
  first.value='en';first.dispatchEvent(new window.Event('change'));assert.notEqual(first.value,second.value);assert.equal(start.disabled,false);
  assert.equal(document.querySelector('[name=consent]').value,'gemini-live-v1');
  assert.equal(document.querySelector('[name=consent]').checked,false);
  assert.equal(document.querySelector('#live-active').hidden,true);assert.equal(microphones,0);assert.equal(contexts,0);
  assert.equal(document.documentElement.lang,locale);assert.equal(requests.length,2);
 });
}
