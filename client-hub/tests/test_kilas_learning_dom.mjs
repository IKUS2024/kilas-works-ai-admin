// Browser-free DOM tests: rendered Flask markup, native DOM events, mocked IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';
import {RealtimeMic} from '../static/kilas_learning_realtime.mjs';
import {mountLearning} from '../static/kilas_learning.mjs';

const directory=process.env.KILAS_LEARNING_DOM_TOOLS||join(tmpdir(),'kilas-learning-dom');
const {JSDOM}=createRequire(pathToFileURL(join(directory,'package.json')))('jsdom');
const html=readFileSync(process.env.KILAS_LEARNING_DOM_FIXTURE_PATH||join(directory,'rendered-home.html'),'utf8');
const bootstrap=readFileSync(new URL('../static/kilas_learning_boot.js',import.meta.url),'utf8');
const tick=async()=>{for(let i=0;i<50;i++)await Promise.resolve();};

function fixture(t,{ready=true}={}){
  const dom=new JSDOM(html,{url:'https://learning.example.test/kilas-learning',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const {window}=dom,{document}=window,root=document.querySelector('[data-learning]'),form=root.querySelector('[data-learning-form]');
  form.dataset.ready=String(ready);
  const consent=form.elements.namedItem('consent'),start=form.querySelector('[data-learning-start]'),status=root.querySelector('[data-status]');
  const requested=[],events=[],played=[];let permissions=0,unlocks=0,listens=0;
  const completed={session_id:'session-synthetic',turn:'greeting-synthetic',status:'COMPLETED',ended:false,clips:[{index:0}]};
  window.fetch=async(url,options={})=>{
    requested.push({url,options});
    return {ok:true,status:200,json:async()=>url==='/kilas-learning/session'?{session_id:null}:url==='/kilas-learning/cancel-start'?{ended:true}:completed,arrayBuffer:async()=>new ArrayBuffer(4)};
  };
  const capture={permission:async()=>{permissions++;events.push('permission');},cancel:()=>{},start:async()=>{listens++;events.push('listen');}};
  const player={unlock:async()=>{unlocks++;events.push('unlock');},stop:()=>{},play:async()=>{played.push(0);events.push('played');}};
  const mount=()=>mountLearning(root,{capture,player,id:()=> 'synthetic-start-1234567890'});
  const check=()=>consent.click();
  return {dom,window,document,root,form,consent,start,status,capture,player,mount,check,requested,events,played,completed,counts:()=>({permissions,unlocks,listens})};
}

test('rendered Finance-first DOM binds Start to the lesson and sends checked consent/settings/CSRF',async t=>{
  const f=fixture(t);assert.equal(f.root.querySelector('form').className,'kilas-finance-entry');
  f.window.eval(bootstrap);const call=f.mount();await tick();
  assert.ok(f.status.compareDocumentPosition(f.root.querySelector('[data-call]'))&f.window.Node.DOCUMENT_POSITION_FOLLOWING);
  assert.equal(f.start.disabled,true);f.check();assert.equal(f.start.disabled,false);
  f.form.elements.namedItem('target').value='zh';f.form.elements.namedItem('native').value='es';f.form.elements.namedItem('level').value='advanced';f.form.elements.namedItem('voice').value='kilas-female';
  f.start.click();assert.match(f.status.textContent,/Meminta izin mikrofon/);await tick();
  const posts=f.requested.filter(x=>x.url==='/kilas-learning/sessions');assert.equal(posts.length,1);
  assert.deepEqual(Object.fromEntries(posts[0].options.body),{csrf_token:'audio-csrf',target:'zh',native:'es',level:'advanced',voice:'kilas-female',consent:'yes',start_key:'synthetic-start-1234567890'});
  assert.equal(posts[0].options.headers['X-CSRF-Token'],'audio-csrf');assert.equal(call.phase,'listening');
  assert.deepEqual(f.events,['unlock','permission','played','listen']);assert.equal(f.root.querySelector('[data-setup]').hidden,true);
});
test('Learning binding leaves Finance navigation submit untouched',async t=>{
  const f=fixture(t);f.mount();await tick();let preventedBefore=false;
  const finance=f.root.querySelector('.kilas-finance-entry');finance.addEventListener('submit',event=>{preventedBefore=event.defaultPrevented;event.preventDefault();});
  finance.querySelector('button').click();await tick();assert.equal(preventedBefore,false);assert.equal(f.counts().permissions,0);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/sessions').length,0);
});
test('unchecked consent blocks both click and synthetic submit; checked consent enables only ready account',async t=>{
  const f=fixture(t),call=f.mount();await tick();f.start.click();
  const event=new f.window.Event('submit',{bubbles:true,cancelable:true});f.form.dispatchEvent(event);await tick();
  assert.equal(event.defaultPrevented,true);assert.match(f.status.textContent,/Setujui/);assert.equal(call.active,false);assert.equal(f.counts().permissions,0);
  f.check();assert.equal(f.start.disabled,false);f.check();assert.equal(f.start.disabled,true);
  const denied=fixture(t,{ready:false});denied.mount();await tick();denied.check();assert.equal(denied.start.disabled,true);assert.match(denied.status.textContent,/akun ini/);
});
test('permission denial is visible, returns setup and permits another deliberate Start',async t=>{
  const f=fixture(t),call=f.mount();await tick();f.check();
  f.capture.permission=async()=>{throw new f.window.DOMException('denied','NotAllowedError');};
  f.start.click();await tick();assert.equal(call.active,false);assert.match(f.status.textContent,/Izin mikrofon ditolak/);assert.equal(f.start.disabled,false);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/sessions').length,0);
  f.capture.permission=async()=>{};f.start.click();await tick();assert.equal(call.phase,'listening');
});
test('pending permission has visible status, repeat Start is fenced and End prevents late admission',async t=>{
  const f=fixture(t),call=f.mount();await tick();f.check();let release;
  f.capture.permission=()=>new Promise(resolve=>{release=resolve;});
  f.start.click();assert.equal(call.phase,'preparing');assert.match(f.status.textContent,/mikrofon/);assert.equal(f.start.disabled,true);
  f.form.dispatchEvent(new f.window.Event('submit',{bubbles:true,cancelable:true}));
  f.root.querySelector('[data-end]').click();release();await tick();assert.equal(call.active,false);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/sessions').length,0);
});
test('backend account readiness rejection surfaces its message with safe recovery controls',async t=>{
  const f=fixture(t);f.window.fetch=async(url,options)=>{f.requested.push({url,options});return url==='/kilas-learning/sessions'?{ok:false,status:503,json:async()=>({code:'learning_unavailable',error:'Learning belum tersedia untuk akun ini. Konfigurasi dan batas biaya perlu diverifikasi.'})}:{ok:true,status:200,json:async()=>({session_id:null})};};
  const call=f.mount();await tick();f.check();f.start.click();await tick();
  assert.equal(call.phase,'paused');assert.match(f.status.textContent,/Konfigurasi dan batas biaya/);assert.equal(f.root.querySelector('[data-resume]').hidden,false);
  assert.deepEqual(f.played,[]);assert.equal(f.counts().listens,0);
});
test('expired login from read-only discovery leaves an actionable status and prevents admission',async t=>{
  const f=fixture(t);f.window.fetch=async()=>({ok:false,status:401,json:async()=>{throw Error('not JSON');}});
  f.mount();await tick();f.check();assert.equal(f.start.disabled,true);assert.match(f.status.textContent,/Masuk kembali/);assert.equal(f.counts().permissions,0);
});
test('unexpected rejected Start promise gets visible feedback without native navigation',async t=>{
  const f=fixture(t),call=f.mount();await tick();f.check();call.start=async()=>{throw Error('synthetic internal exception');};
  f.start.click();await tick();assert.match(f.status.textContent,/Kontrol Learning terhenti/);assert.doesNotMatch(f.status.textContent,/internal exception/);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/sessions').length,0);
});
test('module resource failure is visible and native form fallback stays blocked',t=>{
  const f=fixture(t);f.window.eval(bootstrap);f.document.querySelector('[data-learning-module]').dispatchEvent(new f.window.Event('error'));
  assert.equal(f.root.dataset.boot,'failed');assert.match(f.status.textContent,/belum berhasil dimuat/);assert.equal(f.start.disabled,true);
  const event=new f.window.Event('submit',{bubbles:true,cancelable:true});f.form.dispatchEvent(event);assert.equal(event.defaultPrevented,true);
  assert.equal(f.requested.length,0);
});
test('module loading timeout produces feedback; a successful boot clears the watchdog',t=>{
  const f=fixture(t);let timedOut,cleared=false;f.window.setTimeout=fn=>{timedOut=fn;return 1;};f.window.clearTimeout=()=>{cleared=true;};
  f.window.eval(bootstrap);timedOut();assert.equal(f.root.dataset.boot,'failed');assert.match(f.status.textContent,/koneksi browser/);
  f.mount();assert.equal(cleared,true);assert.equal(f.root.dataset.boot,'ready');f.check();assert.equal(f.start.disabled,false);
});
test('actual module entry boots the marked lesson form despite a preceding Finance form',async t=>{
  const f=fixture(t),previous=Object.getOwnPropertyDescriptor(globalThis,'document');
  Object.defineProperty(globalThis,'document',{value:f.document,configurable:true});
  try{await import('../static/kilas_learning.mjs?dom-auto-entry');await tick();assert.equal(f.root.dataset.boot,'ready');assert.match(f.status.textContent,/Setujui/);}
  finally{if(previous)Object.defineProperty(globalThis,'document',previous);else delete globalThis.document;}
});
test('actual module entry exposes malformed-control startup errors instead of silently failing',async t=>{
  const f=fixture(t),previous=Object.getOwnPropertyDescriptor(globalThis,'document');f.form.elements.namedItem('csrf_token').remove();
  Object.defineProperty(globalThis,'document',{value:f.document,configurable:true});
  try{await import('../static/kilas_learning.mjs?dom-failed-entry');assert.equal(f.root.dataset.boot,'failed');assert.match(f.status.textContent,/Kontrol Learning/);assert.equal(f.start.disabled,true);}
  finally{if(previous)Object.defineProperty(globalThis,'document',previous);else delete globalThis.document;}
});

test('opening with saved session leaves settings editable, mic silent and resume optional',async t=>{
  const f=fixture(t);f.window.sessionStorage.setItem('kilas-learning-session',JSON.stringify({session:'old-session',turn:'old-turn',next:1,settings:{target:'zh',native:'es',level:'advanced',voice:'kilas-female'}}));
  f.window.fetch=async(url,options)=>{f.requested.push({url,options});return {ok:true,status:200,json:async()=>({...f.completed,session_id:'old-session'}),arrayBuffer:async()=>new ArrayBuffer(4)};};
  const call=f.mount();f.form.elements.namedItem('target').value='es';await tick();
  assert.equal(call.active,false);assert.equal(f.root.querySelector('[data-setup]').hidden,false);assert.equal(f.root.querySelector('[data-call]').hidden,true);
  assert.equal(f.form.elements.namedItem('target').value,'es');assert.equal(f.root.querySelector('[data-previous]').hidden,false);
  assert.equal(f.start.textContent,'Mulai pelajaran baru');assert.deepEqual(f.counts(),{permissions:0,unlocks:0,listens:0});
  assert.equal(f.requested.filter(x=>x.options?.method==='POST').length,0);
});
test('explicit previous resume consumes completed stored clips without generating a new greeting',async t=>{
  const f=fixture(t);f.window.fetch=async(url,options)=>{f.requested.push({url,options});return {ok:true,status:200,json:async()=>({...f.completed,target:'en',native:'id',level:'beginner',voice:'kilas-male'}),arrayBuffer:async()=>new ArrayBuffer(4)};};
  const call=f.mount();await tick();assert.equal(call.active,false);
  f.root.querySelector('[data-resume-previous]').click();await tick();
  assert.equal(call.phase,'listening');assert.equal(f.played.length,1);assert.equal(f.counts().listens,1);
  assert.equal(f.requested.filter(x=>x.options?.method==='POST').length,0);
  f.root.querySelector('[data-end]').click();await tick();assert.equal(f.root.querySelector('[data-setup]').hidden,false);
});
test('new lesson ends the discovered old session before one consented new Start and preserves choices',async t=>{
  const f=fixture(t);f.window.fetch=async(url,options)=>{f.requested.push({url,options});return {ok:true,status:200,json:async()=>url==='/kilas-learning/session'?{...f.completed,session_id:'old-session'}:url==='/kilas-learning/cancel-start'?{ended:true}:f.completed,arrayBuffer:async()=>new ArrayBuffer(4)};};
  const call=f.mount();await tick();f.form.elements.namedItem('target').value='es';f.check();f.start.click();await tick();
  const posts=f.requested.filter(x=>x.options?.method==='POST');assert.deepEqual(posts.map(x=>x.url),['/kilas-learning/cancel-start','/kilas-learning/sessions']);
  assert.equal(posts[0].options.body.get('session_id'),'old-session');assert.equal(posts[1].options.body.get('target'),'es');assert.equal(posts[1].options.body.get('consent'),'yes');assert.equal(call.phase,'listening');
});

test('real microphone controller and browser timer receivers poll pending greeting; End restores setup and fences late result',async t=>{
  const f=fixture(t),nativeSet=globalThis.setTimeout,nativeClear=globalThis.clearTimeout;
  for(const [name,native]of [['setTimeout',nativeSet],['clearTimeout',nativeClear]])t.mock.method(globalThis,name,function(...args){
    if(this!==undefined&&this!==globalThis)throw new TypeError('Illegal invocation');
    return Reflect.apply(native,globalThis,args);
  });
  let release,opens=0,stops=0;
  f.window.fetch=async(url,options)=>{
    f.requested.push({url,options});
    const response=value=>({ok:true,status:200,json:async()=>value,arrayBuffer:async()=>new ArrayBuffer(4)});
    if(url==='/kilas-learning/session')return response({session_id:null});
    if(url==='/kilas-learning/sessions')return response({...f.completed,status:'PROCESSING',clips:[]});
    if(url==='/kilas-learning/cancel-start')return response({ended:true});
    return new Promise(resolve=>{release=()=>resolve(response(f.completed));});
  };
  let call;
  const mic=new RealtimeMic({api:{cancel:async()=>{}},session:()=>call.session,id:()=> 'synthetic-mic-turn',onOpened:()=>{},
    openMicrophone:async()=>{opens++;return ()=>{stops++;};}});
  call=mountLearning(f.root,{capture:mic,player:f.player,id:()=> 'synthetic-start-1234567890'});call.wait=async()=>{};
  await tick();f.check();f.start.click();await tick();assert.ok(release,'status polled after real Mic.cancel');assert.equal(opens,1);
  f.root.querySelector('[data-end]').click();await tick();
  assert.equal(call.active,false);assert.equal(f.root.querySelector('[data-setup]').hidden,false);assert.equal(f.root.querySelector('[data-call]').hidden,true);
  assert.equal(f.start.disabled,false);assert.match(f.status.textContent,/Sesi berakhir/);assert.doesNotMatch(f.status.textContent,/izin mikrofon/);
  release();await tick();assert.equal(f.played.length,0);assert.equal(call.phase,'ended');assert.equal(stops,1);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/sessions').length,1);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/cancel-start').length,1);
});
test('failed local cleanup still restores setup, stops remaining resources and closes server session without claiming stopped audio',async t=>{
  const f=fixture(t),call=f.mount();await tick();f.check();f.start.click();await tick();let playerStops=0;
  f.capture.cancel=()=>{throw new TypeError('synthetic cleanup fault');};f.player.stop=()=>{playerStops++;};
  f.root.querySelector('[data-end]').click();await tick();
  assert.equal(playerStops,1);assert.equal(call.active,false);assert.equal(call.phase,'ended');
  assert.equal(f.root.querySelector('[data-setup]').hidden,false);assert.equal(f.root.querySelector('[data-call]').hidden,true);
  assert.equal(f.start.disabled,true);assert.match(f.status.textContent,/belum berhenti bersih/);assert.doesNotMatch(f.status.textContent,/synthetic/);
  assert.equal(f.requested.filter(x=>x.url==='/kilas-learning/cancel-start').length,1);
});
test('late rejected control operation cannot overwrite a later End or new call',async t=>{
  const f=fixture(t),call=f.mount();await tick();f.check();let reject;
  call.start=()=>{call.active=true;call.version++;call.state('preparing');return new Promise((_r,j)=>{reject=j;});};
  f.start.click();f.root.querySelector('[data-end]').click();await tick();reject(Error('late synthetic startup failure'));await tick();
  assert.equal(call.phase,'ended');assert.match(f.status.textContent,/Sesi berakhir/);assert.equal(f.root.querySelector('[data-setup]').hidden,false);
});
