import test from 'node:test';
import assert from 'node:assert/strict';
import {TranslatorRecovery} from '../static/kilas_live_translator_recovery.mjs';

const deferred = () => {let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise,resolve,reject};};
const old = {session_id: 'synthetic-old', processing: false};

test('discovery blocks Start and never automatically ends an existing session', async () => {
  let ends=0;
  const recovery=new TranslatorRecovery({api:{active:async()=>({session:old}),end:async()=>{ends++;}}});
  assert.equal(recovery.canStart(),false);
  await recovery.refresh();
  assert.equal(recovery.canStart(),false);assert.equal(ends,0);
  assert.equal(recovery.active,old);
});

test('an explicit owner End waits for acknowledgement and rechecks before enabling Start', async () => {
  const end=deferred();let reads=0,ends=0;
  const recovery=new TranslatorRecovery({api:{active:async()=>({session:++reads===1?old:null}),end:async id=>{assert.equal(id,old.session_id);ends++;await end.promise;}}});
  await recovery.refresh();
  const pending=recovery.endPrevious();
  assert.equal(recovery.canStart(),false);assert.equal(recovery.ending,true);
  assert.equal(await recovery.endPrevious(),false);
  end.resolve();await pending;
  assert.equal(ends,1);assert.equal(reads,2);assert.equal(recovery.canStart(),true);
});

test('failed End keeps the old session visible and never retries automatically', async () => {
  let ends=0;const errors=[];
  const recovery=new TranslatorRecovery({api:{active:async()=>({session:old}),end:async()=>{ends++;throw Error('offline');}},onError:value=>errors.push(value)});
  await recovery.refresh();await recovery.endPrevious();
  assert.equal(ends,1);assert.equal(recovery.canStart(),false);
  assert.equal(recovery.active.session_id,old.session_id);
  assert.match(errors[0],/belum terkonfirmasi/);
});

test('another tab starting after End remains active and is never force-ended', async () => {
  const newer={session_id:'synthetic-new'};let reads=0;const ended=[];
  const recovery=new TranslatorRecovery({api:{active:async()=>({session:++reads===1?old:newer}),end:async id=>ended.push(id)}});
  await recovery.refresh();await recovery.endPrevious();
  assert.deepEqual(ended,[old.session_id]);assert.equal(recovery.active,newer);
  assert.equal(recovery.canStart(),false);
});

test('expired or already-ended session becomes available through a read without history mutation', async () => {
  let reads=0,ends=0;
  const recovery=new TranslatorRecovery({api:{active:async()=>({session:++reads===1?old:null}),end:async()=>{ends++;}}});
  await recovery.refresh();await recovery.refresh();
  assert.equal(recovery.canStart(),true);assert.equal(ends,0);
});

test('a stale discovery response cannot undo a newer confirmed End', async () => {
  const read=deferred();let reads=0;
  const recovery=new TranslatorRecovery({api:{active:()=>++reads===1?read.promise:Promise.resolve({session:null}),end:async()=>{}}});
  const pending=recovery.refresh();
  await recovery.endKnown(old.session_id);
  read.resolve({session:old});await pending;
  assert.equal(recovery.canStart(),true);assert.equal(recovery.active,null);
});

test('unknown status or active local capture cannot silently admit or end a session', async () => {
  let reads=0,ends=0,idle=false;
  const recovery=new TranslatorRecovery({api:{active:async()=>{reads++;throw Error('offline');},end:async()=>{ends++;}},isIdle:()=>idle});
  await recovery.refresh();assert.equal(reads,0);
  assert.equal(await recovery.endPrevious(),false);assert.equal(ends,0);
  idle=true;await recovery.refresh();assert.equal(reads,1);
  assert.equal(recovery.canStart(),false);
});

test('missing or malformed discovery never enables Start', async () => {
  for (const result of [{},null,{session:{}},{session:false}]) {
    const recovery=new TranslatorRecovery({api:{active:async()=>result,end:async()=>{throw Error('Unexpected End');}}});
    await recovery.refresh();assert.equal(recovery.canStart(),false);
  }
});

test('session_busy in the actual page reveals owner recovery without microphone or automatic End', async () => {
  const formEvents=new Map(),events=new Map();const calls=[];
  const button=()=>({disabled:false,hidden:false,dataset:{enabled:'true'},addEventListener(type,handler){this[type]=handler;}});
  const a={value:'id',options:[{value:'id'},{value:'en'}],addEventListener(){}},b={value:'en',options:[{value:'id'},{value:'en'}],addEventListener(){},focus(){}};
  const start=button(),end=button(),check=button(),error={hidden:true},panel={hidden:true};
  const form={elements:{language_a:a,language_b:b},querySelector:query=>query==='button[type=submit]'?start:{value:'synthetic-csrf'},addEventListener:(type,handler)=>formEvents.set(type,handler),reportValidity:()=>true};
  const orb={dataset:{},setAttribute(key,value){this[key]=value;},getAttribute(key){return this[key];}};
  const nodes={'.kilas-live-translator':{dataset:{ready:'true'}},'#live-setup-form':form,'#live-setup':{},'#live-active':{querySelector:()=>orb},'#live-error':error,'#live-resume': {hidden:true,addEventListener() {}}, '#live-end':button(),'#live-state':{},'#live-translation':{},'#live-session-status': {}, '#live-recovery-retry': {addEventListener() {}}, '#live-recovery':panel,'#live-recovery-status':{},'#live-recovery-end':end,'#live-recovery-check':check};
  const original={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch,FormData:globalThis.FormData};
  const navigatorDescriptor=Object.getOwnPropertyDescriptor(globalThis,'navigator');
  const endResponse=deferred(),beacons=[];
  let reads=0,ended=false,audioClosed=0;
  try {
    globalThis.document={querySelector:query=>nodes[query],addEventListener(){}};
    globalThis.window={addEventListener:(type,handler)=>events.set(type,handler),AudioContext:class{state='running';resume(){return Promise.resolve();}close(){audioClosed++;return Promise.resolve();}}};
    globalThis.FormData=class{constructor(){this.entries=new Map();}append(key,value){this.entries.set(key,value);}};
    Object.defineProperty(globalThis,'navigator',{configurable:true,value:{sendBeacon:(url,data)=>{beacons.push({url,data});return true;}}});
    globalThis.fetch=async(url,options={})=>{
      calls.push({url,method:options.method||'GET'});
      if(url.endsWith('/active'))return {ok:true,json:async()=>({session:++reads===1||ended?null:old})};
      if(url.endsWith('/synthetic-old/end')){ended=true;await endResponse.promise;return {ok:true,json:async()=>({status:'ENDED'})};}
      assert.equal(url,'/kilas-translator/live/sessions');
      return {ok:false,json:async()=>({code:'session_busy',error:'Sesi lain masih aktif. Akhiri sesi itu terlebih dahulu.'})};
    };
    await import('../static/kilas_live_translator.mjs?busy-recovery-test');
    await new Promise(resolve=>setImmediate(resolve));
    formEvents.get('submit')({preventDefault(){}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(panel.hidden,false);assert.equal(start.disabled,true);assert.equal(end.hidden,false);
    assert.equal(audioClosed,1);
    assert.equal(calls.filter(call=>call.url.endsWith('/end')).length,0);
    const finishing=end.click();
    await new Promise(resolve=>setImmediate(resolve));
    events.get('pagehide')();
    assert.equal(beacons.length,1);assert.equal(beacons[0].url,'/kilas-translator/live/sessions/synthetic-old/end');
    assert.equal(beacons[0].data.entries.get('csrf_token'),'synthetic-csrf');
    endResponse.resolve();await finishing;
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(start.disabled,false);assert.equal(panel.hidden,true);assert.equal(error.hidden,true);
    assert.equal(calls.filter(call=>call.url==='/kilas-translator/live/sessions').length,1);
    assert.equal(calls.filter(call=>call.url.endsWith('/end')).length,1);
  } finally {
    for (const [key,value] of Object.entries(original))if(value===undefined)delete globalThis[key];else globalThis[key]=value;
    if(navigatorDescriptor)Object.defineProperty(globalThis,'navigator',navigatorDescriptor);else delete globalThis.navigator;
  }
});

for(const stalled of ['request','body'])test(`End ${stalled} timeout releases recovery controls and keeps server status unconfirmed`,async()=>{
  const buttons=()=>({disabled:false,hidden:false,dataset:{enabled:'true'},addEventListener(type,handler){this[type]=handler;}});
  const timers=new Map(),calls=[];let timerId=0,reads=0;
  const a={value:'id',options:[{value:'id'},{value:'en'}],addEventListener(){}},b={value:'en',options:[{value:'id'},{value:'en'}],addEventListener(){}};
  const start=buttons(),end=buttons(),check=buttons(),error={hidden:true},panel={hidden:true};
  const form={elements:{language_a:a,language_b:b},querySelector:q=>q==='button[type=submit]'?start:{value:'synthetic-csrf'},addEventListener(){}};
  const nodes={'.kilas-live-translator':{dataset:{ready:'true'}},'#live-setup-form':form,'#live-setup':{},'#live-active':{querySelector:()=>({})},'#live-error':error,'#live-resume': {hidden:true,addEventListener() {}}, '#live-end':buttons(),'#live-state':{},'#live-translation':{},'#live-session-status': {}, '#live-recovery-retry': {addEventListener() {}}, '#live-recovery':panel,'#live-recovery-status':{},'#live-recovery-end':end,'#live-recovery-check':check};
  const original={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch,FormData:globalThis.FormData,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout};
  try{
    globalThis.document={querySelector:q=>nodes[q],addEventListener(){}};globalThis.window={addEventListener(){}};
    globalThis.FormData=class{append(){}};
    globalThis.setTimeout=(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;};globalThis.clearTimeout=id=>timers.delete(id);
    globalThis.fetch=async(url,options={})=>{
      calls.push(url);
      if(url.endsWith('/active'))return {ok:true,json:async()=>({session:{session_id:++reads===1?'old':'newer'}})};
      assert.equal(url,'/kilas-translator/live/sessions/old/end');assert.equal(options.keepalive,true);assert.ok(options.signal);
      const blocked=new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Synthetic connection stall','AbortError')),{once:true}));
      return stalled==='request'?blocked:{ok:true,json:()=>blocked};
    };
    await import(`../static/kilas_live_translator.mjs?end-timeout-${stalled}`);await new Promise(r=>setImmediate(r));
    const ending=end.click();assert.equal(end.disabled,true);assert.equal(start.disabled,true);await new Promise(r=>setImmediate(r));
    const deadline=[...timers].find(([,timer])=>timer.ms===10000);assert.ok(deadline);timers.delete(deadline[0]);deadline[1].fn();
    assert.equal(await ending,false);assert.equal(end.disabled,false);assert.equal(check.disabled,false);assert.equal(start.disabled,true);assert.equal(panel.hidden,false);
    assert.match(error.textContent,/belum terkonfirmasi berakhir/);assert.equal(timers.size,0);
    await check.click();assert.equal(reads,2);assert.equal(start.disabled,true);
    assert.equal(calls.filter(url=>url.endsWith('/end')).length,1);assert.equal(calls.some(url=>url.endsWith('/newer/end')),false);
  }finally{for(const [key,value] of Object.entries(original))if(value===undefined)delete globalThis[key];else globalThis[key]=value;}
});

for(const outcome of ['no-session','active','error','malformed'])test(`initial page check stays neutral until verified ${outcome}`,async()=>{
  const read=deferred(),requests=[],events=new Map();let resolved=false;
  const button=()=>({hidden:true,disabled:false,dataset:{enabled:'true'},textContent:'',attrs:{},setAttribute(key,value){this.attrs[key]=value;},addEventListener(type,handler){this[type]=handler;}});
  const a={value:'id',options:[{value:'id'},{value:'en'}],addEventListener(){}},b={value:'en',options:[{value:'id'},{value:'en'}],addEventListener(){}};
  const start=button(),retry=button(),check=button(),end=button(),status={textContent:''},error={hidden:true};
  const visibility=[];let hidden=true;const panel={get hidden(){return hidden;},set hidden(value){visibility.push(value);hidden=value;}};
  const form={elements:{language_a:a,language_b:b},querySelector:q=>q==='button[type=submit]'?start:{value:'synthetic-csrf'},addEventListener(){}};
  const nodes={'.kilas-live-translator':{dataset:{ready:'true'}},'#live-setup-form':form,'#live-setup':{},'#live-active':{querySelector:()=>({})},'#live-resume': {hidden:true,addEventListener() {}}, '#live-end':button(),'#live-state':{},'#live-translation':{},'#live-error':error,'#live-recovery':panel,'#live-recovery-status':{},'#live-recovery-end':end,'#live-recovery-check':check,'#live-recovery-retry':retry,'#live-session-status':status};
  const original={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch};
  try{
    globalThis.document={querySelector:q=>nodes[q],addEventListener(){}};globalThis.window={addEventListener:(type,handler)=>events.set(type,handler)};
    globalThis.fetch=async url=>{requests.push(url);assert.equal(url,'/kilas-translator/live/sessions/active');return {ok:true,json:()=>resolved?Promise.resolve({session:null}):read.promise};};
    await import(`../static/kilas_live_translator.mjs?neutral-initial-${outcome}`);
    assert.equal(panel.hidden,true);assert.equal(start.disabled,true);assert.equal(start.textContent,'Start');assert.equal(start.attrs['aria-busy'],'true');
    assert.equal(status.textContent,'Memeriksa sesi...');assert.equal(retry.hidden,true);assert.equal(error.hidden,true);
    if(outcome==='error')read.reject(Error('Synthetic offline'));else read.resolve(outcome==='malformed'?{}:{session:outcome==='active'?old:null});
    await new Promise(r=>setImmediate(r));resolved=true;
    assert.equal(start.textContent,'Start');assert.equal(start.attrs['aria-busy'],'false');assert.equal(status.textContent,'');
    assert.equal(panel.hidden,outcome!=='active');assert.equal(start.disabled,outcome!=='no-session');
    assert.equal(retry.hidden,!['error','malformed'].includes(outcome));assert.equal(error.hidden,!['error','malformed'].includes(outcome));
    if(outcome==='active'){assert.equal(end.hidden,false);assert.match(nodes['#live-recovery-status'].textContent,/Sesi sebelumnya masih aktif/);}
    else assert.ok(visibility.every(Boolean),'No conflict panel may flash for loading, no-session, or error.');
    if(['error','malformed'].includes(outcome)){await retry.click();assert.equal(start.disabled,false);assert.equal(panel.hidden,true);assert.equal(retry.hidden,true);assert.equal(error.hidden,true);}
    if(outcome==='no-session'){
      events.get('pageshow')();assert.equal(panel.hidden,true);await new Promise(r=>setImmediate(r));assert.equal(panel.hidden,true);assert.equal(start.disabled,false);
    }
    assert.equal(a.value,'id');assert.equal(b.value,'en');assert.ok(requests.every(url=>url.endsWith('/active')));
  }finally{for(const [key,value] of Object.entries(original))if(value===undefined)delete globalThis[key];else globalThis[key]=value;}
});
