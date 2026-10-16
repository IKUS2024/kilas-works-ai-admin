// Real Flask HTML, synthetic session transport; no browser or media.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs?v=native-progressive-20261016';
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
   fetch:async(url,options={})=>{requests.push({url,...options});if(options.method==='POST'){assert.equal(url,'/kilas-translator/live/sessions/'+active.session_id+'/end');active=null;return {ok:true,redirected:false,json:async()=>({status:'ENDED'})};}assert.ok(url.endsWith('/live/sessions/active'));return {ok:true,redirected:false,json:async()=>({session:active})};}};
  const previous={};for(const [key,value] of Object.entries(values)){previous[key]=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});}
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}});
  await import('../static/kilas_live_gemini.mjs?dom-'+locale);await tick();
  const start=document.querySelector('#live-setup-form [type=submit]'),first=document.querySelector('[name=language_a]'),second=document.querySelector('[name=language_b]');
  assert.equal(start.disabled,true);assert.equal(document.querySelector('#live-recovery').hidden,false);
  assert.equal(document.querySelector('#live-recovery-status').textContent,locale==='en'?'The previous session is still active.':'Sesi sebelumnya masih aktif.');
  assert.equal(requests.length,1);assert.equal(microphones,0);assert.equal(contexts,0);
  assert.equal(document.querySelector('#live-recovery-check').hidden,true);document.querySelector('#live-recovery-end').click();await tick();assert.equal(start.disabled,false);
  first.value='en';first.dispatchEvent(new window.Event('change'));assert.notEqual(first.value,second.value);assert.equal(start.disabled,false);
  const paired=document.querySelector('[data-gemini-live]').dataset.geminiTranslationMode==='two_way';
  const progressive=paired&&document.querySelector('[name=output_order]')?.value==='progressive_stream_runs';
  const consent=paired?(progressive?'gemini-live-two-way-v2':'gemini-live-two-way-v1'):'gemini-live-v1';
  assert.equal(document.querySelector('[name=consent]').value,consent);
  assert.equal(document.querySelector('[name=translation_mode]')?.value||null,paired?'two_way':null);
  if(paired){
   assert.equal(document.querySelector('#gemini-pair-summary').textContent,first.selectedOptions[0].textContent+' ↔ '+second.selectedOptions[0].textContent);
   assert.ok(first.closest('label').textContent.includes(locale==='en'?'First language':'Bahasa pertama'));
   assert.ok(second.closest('label').textContent.includes(locale==='en'?'Second language':'Bahasa kedua'));
   assert.ok(document.querySelector('#live-setup-form').textContent.includes(locale==='en'?'The selected languages are translated automatically in both directions.':'Bahasa yang dipilih diterjemahkan otomatis dua arah.'));
   assert.equal(document.querySelector('#live-setup-form').textContent.includes(locale==='en'?'The source language is translated into the target language.':'Bahasa sumber diterjemahkan ke bahasa tujuan.'),false);
  }
  assert.equal(document.querySelector('[name=consent]').checked,false);
  assert.equal(document.querySelector('#live-active').hidden,true);assert.equal(microphones,0);assert.equal(contexts,0);
  assert.equal(document.documentElement.lang,locale);assert.equal(requests.length,3);
  // Drive the real DOM callbacks with synthetic engine states; never start media.
  const originalStart=GeminiSession.prototype.start;let submitted=false;
  GeminiSession.prototype.start=function(data){
   assert.equal(data.get('translation_mode'),paired?'two_way':null);assert.equal(data.get('consent'),consent);assert.equal(data.get('output_order'),progressive?'progressive_stream_runs':null);
   submitted=true;this.active=true;this.state('renewing');
   assert.equal(document.querySelector('#live-active').hidden,false);assert.equal(document.querySelector('#gemini-finish'),null);assert.equal(document.querySelector('#live-translation'),null);assert.deepEqual([...document.querySelectorAll('#live-active button')].map(node=>node.id),['live-end']);assert.equal(document.querySelector('#live-recovery-check').hidden,true);
   assert.equal(document.querySelector('#live-state').textContent,locale==='en'?'Processing':'Memproses');
   this.onWarning({code:'gemini_tail_unconfirmed',completion_kind:'bounded_drain',tail_confirmed:false});
   assert.equal(document.querySelector('#live-session-status').textContent,locale==='en'?'The end of the translation is not confirmed.':'Bagian akhir terjemahan belum terkonfirmasi.');
   this.onError({code:'budget_limit'});this.active=false;this.state('ended');
  };
  t.after(()=>{GeminiSession.prototype.start=originalStart;});
  document.querySelector('[name=consent]').checked=true;document.querySelector('#live-setup-form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));await tick();
  assert.equal(submitted,true);assert.equal(document.querySelector('#live-error').hidden,false);
  assert.equal(document.querySelector('#live-error').textContent,locale==='en'?'The spending limit was reached. The session has stopped.':'Batas biaya tercapai. Sesi dihentikan.');
  assert.equal(document.querySelector('#live-active').hidden,true);assert.equal(microphones,0);assert.equal(contexts,0);assert.equal(requests.length,3);
 });
}

for(const locale of ['en','id']){
 test(`Native ${locale} recovery-only entry can end its owned session while Start remains blocked`,async t=>{
  const dom=new JSDOM(pages[locale+'_recovery']||pages[locale],{url:'https://app.example.test/kilas-translator/live/gemini',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());const {window}=dom,{document}=window;
  // A rendered recovery fixture is preferred; the same admission attribute is
  // injected when the focused route suite did not export a recovery fixture.
  const root=document.querySelector('[data-gemini-live]');assert.ok(root);root.dataset.geminiReady='false';
  window.eval(readFileSync(new URL('../static/ui_i18n.js',import.meta.url),'utf8'));
  const id='d'.repeat(48),requests=[];let active={session_id:id,processing:true},microphones=0,contexts=0;
  const values={window,document,KilasUI:window.KilasUI,FormData:window.FormData,
   navigator:{mediaDevices:{getUserMedia(){microphones++;throw Error('No microphone QA');}}},
   AudioContext:class{constructor(){contexts++;throw Error('No audio-context QA');}},
   fetch:async(url,options={})=>{
    requests.push({url,...options});
    if(url.endsWith('/live/sessions/active')){assert.equal(options.method||'GET','GET');return {ok:true,redirected:false,json:async()=>({session:active})};}
    assert.equal(url,'/kilas-translator/live/sessions/'+id+'/end');assert.equal(options.method,'POST');active=null;
    return {ok:true,redirected:false,json:async()=>({status:'ENDED'})};
   }};
  const previous={};for(const [key,value] of Object.entries(values)){previous[key]=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});}
  t.after(()=>{for(const [key,value] of Object.entries(previous)){if(value)Object.defineProperty(globalThis,key,value);else delete globalThis[key];}});
  await import('../static/kilas_live_gemini.mjs?dom-recovery-'+locale);await tick();
  const form=document.querySelector('#live-setup-form'),start=form.querySelector('[type=submit]');
  assert.equal(start.disabled,true);assert.equal(document.querySelector('#live-recovery').hidden,false);assert.equal(requests.length,1);
  document.querySelector('[name=consent]').checked=true;
  const submit=()=>form.dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));
  submit();await tick();assert.equal(requests.length,1);assert.equal(microphones,0);assert.equal(contexts,0);
  document.querySelector('#live-recovery-end').click();await tick();
  assert.equal(requests.filter(request=>request.method==='POST').length,1);assert.equal(requests.length,3);
  assert.equal(document.querySelector('#live-recovery').hidden,true);assert.equal(start.disabled,true);
  const first=document.querySelector('[name=language_a]');first.value='en';first.dispatchEvent(new window.Event('change'));assert.equal(start.disabled,true);
  submit();await tick();assert.equal(requests.length,3);assert.equal(microphones,0);assert.equal(contexts,0);
  // Even script-driven removal of disabled cannot bypass the server-rendered
  // admission state. Explicitly ending the old session never authorizes Start.
  start.disabled=false;submit();await tick();assert.equal(requests.length,3);assert.equal(microphones,0);assert.equal(contexts,0);
  document.querySelector('#live-recovery-check').click();await tick();assert.equal(start.disabled,true);assert.equal(requests.length,4);
  assert.equal(requests.some(request=>request.url==='/kilas-translator/live/gemini/sessions'),false);
 });
}
