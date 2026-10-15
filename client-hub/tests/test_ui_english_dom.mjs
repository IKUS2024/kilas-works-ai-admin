// Real Flask markup + mocked DOM/network only. Does not launch a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';

const fixturePath=process.env.KILAS_ENGLISH_UI_FIXTURE_PATH;
if(!fixturePath)throw Error('Render test_ui_english_consistency.py with KILAS_ENGLISH_UI_FIXTURE_PATH before this DOM suite.');
const pages=JSON.parse(readFileSync(fixturePath,'utf8'));
const directory=process.env.KILAS_UI_DOM_TOOLS||join(tmpdir(),'kilas-learning-dom');
const {JSDOM}=createRequire(pathToFileURL(join(directory,'package.json')))('jsdom');
const code=name=>readFileSync(new URL('../static/'+name,import.meta.url),'utf8');
const tick=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};

for(const width of [390,1440]){
 test(`English history at ${width} preserves user draft and audio form through paging`,async t=>{
  const dom=new JSDOM(pages['history-first'],{url:'https://app.example.test/kilas-translator?mode=voiceover',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());const {window}=dom,{document}=window;
  Object.defineProperty(window,'innerWidth',{value:width});
  window.eval(code('ui_i18n.js'));
  const script=document.querySelector('#audio-script');script.value='Jangan ubah naskah ini';
  const voice=document.querySelector('#selected-voice');voice.value='kilas-male';
  let requests=0;
  window.fetch=async()=>{requests++;return {ok:true,redirected:false,json:async()=>pages['history-second']};};
  window.eval(code('kilas_audio_history.js'));
  const next=document.querySelector('[data-audio-history-page="2"]');assert.ok(next);next.click();
  assert.equal(document.querySelector('[data-audio-history-message]').textContent,'Loading history…');
  await tick();assert.equal(requests,1);
  assert.equal(document.querySelector('[data-audio-history-message]').textContent,'Page 2 of 2.');
  assert.equal(document.querySelector('#audio-script'),script);assert.equal(script.value,'Jangan ubah naskah ini');
  assert.equal(voice.value,'kilas-male');assert.equal(document.documentElement.lang,'en');
  assert.ok(document.querySelector('[data-audio-history-content]').textContent.includes('Edit naskah'));
  assert.equal(document.querySelector('[data-audio-history-content]').getAttribute('aria-busy'),null);
 });

 test(`English Translator recovery at ${width} shows checking/error without capturing audio`,async t=>{
  const dom=new JSDOM(pages['/kilas-translator/live'],{url:'https://app.example.test/kilas-translator/live',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());const {window}=dom,{document}=window;
  Object.defineProperty(window,'innerWidth',{value:width});window.eval(code('ui_i18n.js'));
  const previous={};
  for(const [key,value] of Object.entries({window,document,KilasUI:window.KilasUI})){
   previous[key]=Object.getOwnPropertyDescriptor(globalThis,key);
   Object.defineProperty(globalThis,key,{value,writable:true,configurable:true});
  }
  t.after(()=>{for(const [key,descriptor] of Object.entries(previous)){if(descriptor)Object.defineProperty(globalThis,key,descriptor);else delete globalThis[key];}});
  const oldFetch=globalThis.fetch;t.after(()=>{globalThis.fetch=oldFetch;});
  let release,calls=0;
  globalThis.fetch=async()=>{calls++;return new Promise(resolve=>{release=resolve;});};
  await import('../static/kilas_live_translator.mjs?english-dom-'+width);
  assert.equal(document.querySelector('#live-session-status').textContent,'Checking session...');
  assert.equal(document.querySelector('#live-setup-form button').textContent,'Checking session...');
  release({ok:true,redirected:false,json:async()=>({session:null})});await tick();
  assert.equal(document.querySelector('#live-setup-form button').textContent,'Start');
  assert.equal(document.querySelector('[name=language_a]').value,'id');
  assert.equal(document.querySelector('[name=language_b]').value,'en');
  globalThis.fetch=async()=>{calls++;return {ok:false,status:503,redirected:false,json:async()=>({error:'Layanan belum tersedia.'})};};
  window.dispatchEvent(new window.Event('online'));await tick();
  assert.equal(document.querySelector('#live-error').textContent,'The service is unavailable.');
  assert.equal(document.querySelector('#live-end').getAttribute('aria-label'),'End session');
  assert.equal(document.querySelector('#live-active').hidden,true);assert.equal(calls,2);
 });
}
