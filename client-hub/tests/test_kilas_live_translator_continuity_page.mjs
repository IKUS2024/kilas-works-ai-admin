// Node-only page wiring with synthetic recorder, audio context and fetch. No browser.
import test from 'node:test';
import assert from 'node:assert/strict';
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const id='a'.repeat(48);
async function page(name,{pendingAdmission=false,invalidAdmission=false,pendingAudio=false}={}){
 const original={document:globalThis.document,window:globalThis.window,fetch:globalThis.fetch,FormData:globalThis.FormData,setTimeout:globalThis.setTimeout,clearTimeout:globalThis.clearTimeout,setInterval:globalThis.setInterval,clearInterval:globalThis.clearInterval};
 const navigatorDescriptor=Object.getOwnPropertyDescriptor(globalThis,'navigator'),performanceDescriptor=Object.getOwnPropertyDescriptor(globalThis,'performance'),dateNow=Date.now;
 const stats={now:0,rms:0,mics:0,captures:0,plays:0,requests:[],beacons:[],deferTurn:null,deferActive:null,deferAdmission:pendingAdmission?deferred():null,deferAudio:pendingAudio?deferred():null};
 const intervals=new Map(),timers=new Map(),events=new Map(),docEvents=new Map(),formEvents=new Map();let seq=0;
 const node=()=>({hidden:true,disabled:false,textContent:'',dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;},getAttribute(k){return this.attrs[k];},addEventListener(type,fn){this[type]=fn;}});
 const a={value:'id',options:[{value:'id'},{value:'en'}],addEventListener(){}},b={value:'en',options:[{value:'id'},{value:'en'}],addEventListener(){}};
 const start=node();start.hidden=false;const orb=node();
 const form={elements:{language_a:a,language_b:b},querySelector:q=>q==='button'?start:{value:'synthetic-csrf'},reportValidity:()=>true,addEventListener:(type,fn)=>formEvents.set(type,fn)};
 const nodes={'.kilas-live-translator':{dataset:{ready:'true'}},'#live-setup-form':form,'#live-setup':node(),'#live-active':Object.assign(node(),{querySelector:()=>orb})};
 for(const key of ['live-error','live-end','live-resume','live-state','live-translation','live-recovery','live-recovery-status','live-recovery-end','live-recovery-check','live-recovery-retry','live-session-status'])nodes['#'+key]=node();
 const sources=[];
 class Context{
  state=pendingAudio?'suspended':'running';currentTime=0;destination={};
  async resume(){if(stats.deferAudio)await stats.deferAudio.promise;this.state='running';}async close(){this.state='closed';}
  createMediaStreamSource(){return {connect(){},disconnect(){}};}
  createAnalyser(){return {fftSize:2048,disconnect(){},getFloatTimeDomainData(array){array.fill(stats.rms);}};}
  async decodeAudioData(){return {duration:2};}
  createBufferSource(){const source={connect(){},disconnect(){},stop(){},start(){assert.equal(stats.mics,0);stats.plays++;}};sources.push(source);return source;}
 }
 class Recorder{
  static isTypeSupported(){return true;}state='inactive';mimeType='audio/webm';events=new Map();
  addEventListener(type,fn){this.events.set(type,fn);}start(){this.state='recording';}
  stop(){if(this.state!=='recording')return;this.state='inactive';this.events.get('dataavailable')?.({data:new Blob(['complete synthetic recording'])});this.events.get('stop')?.();}
 }
 try{
  globalThis.document={hidden:false,querySelector:q=>nodes[q],addEventListener:(type,fn)=>docEvents.set(type,fn)};
  globalThis.window={AudioContext:Context,MediaRecorder:Recorder,addEventListener:(type,fn)=>events.set(type,fn)};
  globalThis.FormData=class{values=new Map();append(k,v){this.values.set(k,v);}get(k){return this.values.get(k);}};
  Object.defineProperty(globalThis,'performance',{configurable:true,value:{now:()=>stats.now}});Date.now=()=>stats.now;
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{async getUserMedia(){stats.captures++;stats.mics++;const track={addEventListener(){},stopped:false,stop(){if(!this.stopped){this.stopped=true;stats.mics--;}}};return {getTracks:()=>[track]};}},sendBeacon:(url,data)=>{stats.beacons.push(url);return true;}}});
  globalThis.setTimeout=(fn,ms)=>{const k=++seq;timers.set(k,{fn,ms});return k;};globalThis.clearTimeout=k=>timers.delete(k);
  globalThis.setInterval=(fn,ms)=>{const k=++seq;intervals.set(k,{fn,ms});return k;};globalThis.clearInterval=k=>intervals.delete(k);
  globalThis.fetch=async(url,options={})=>{
   stats.requests.push({url,method:options.method||'GET',body:options.body});
   if(url.endsWith('/active')){const session=stats.deferActive?await stats.deferActive.promise:null;return {ok:true,json:async()=>({session})};}
   if(url==='/kilas-translator/live/sessions'){if(stats.deferAdmission)await stats.deferAdmission.promise;return {ok:true,json:async()=>(invalidAdmission?{}:{session_id:id})};}
   if(url.endsWith('/end'))return {ok:true,json:async()=>({status:'ENDED'})};
   if(url.endsWith('/cancel'))return {ok:true,json:async()=>({status:'CANCELLED'})};
   if(url==='/kilas-translator/live/sessions/'+id)return {ok:true,json:async()=>({status:'ACTIVE',processing:false})};
   if(url.endsWith('/audio'))return {ok:true,arrayBuffer:async()=>new ArrayBuffer(32)};
   if(options.method==='POST'){if(stats.deferTurn)await stats.deferTurn.promise;return {ok:true,json:async()=>({status:'PROCESSING'})};}
   return {ok:true,json:async()=>({status:'COMPLETED',translated_text:'Synthetic translation',audio_url:url+'/audio'})};
  };
  await import(`../static/kilas_live_translator.mjs?continuity-page-${name}`);await tick();formEvents.get('submit')({preventDefault(){}});await tick();
  assert.equal(stats.mics,pendingAdmission||pendingAudio||invalidAdmission?0:1);
 }catch(e){restore();throw e;}
 function restore(){
  for(const [key,value] of Object.entries(original))if(value===undefined)delete globalThis[key];else globalThis[key]=value;
  if(navigatorDescriptor)Object.defineProperty(globalThis,'navigator',navigatorDescriptor);else delete globalThis.navigator;
  if(performanceDescriptor)Object.defineProperty(globalThis,'performance',performanceDescriptor);else delete globalThis.performance;Date.now=dateNow;
 }
 return {stats,nodes,start,formEvents,sources,events,docEvents,intervals,timers,monitor(){[...intervals.values()].find(t=>t.ms===50)?.fn();},async finish(){nodes['#live-end'].click();await tick();assert.equal(stats.mics,0);assert.equal(intervals.size,0);assert.equal(timers.size,0);restore();},restore};
}

for(const mode of ['End','timeout'])test('ambiguous admission '+mode+' requires owner status verification before another Start',async()=>{
 const f=await page('admission-'+mode,{pendingAdmission:true});try{
  assert.equal(f.nodes['#live-state'].textContent,'Menyiapkan sesi');const verified=deferred();f.stats.deferActive=verified;
  if(mode==='End')f.nodes['#live-end'].click();else {[...f.timers.values()].find(t=>t.ms===32000).fn();}
  await tick();assert.equal(f.start.disabled,true);assert.equal(f.stats.captures,0);assert.equal(f.stats.requests.filter(r=>r.url==='/kilas-translator/live/sessions').length,1);
  verified.resolve({session_id:id,processing:false});await tick();assert.equal(f.start.disabled,true);assert.equal(f.nodes['#live-recovery'].hidden,false);
  f.formEvents.get('submit')({preventDefault(){}});assert.equal(f.stats.requests.filter(r=>r.url==='/kilas-translator/live/sessions').length,1);assert.equal(f.stats.requests.some(r=>r.url.endsWith('/end')),false);
  f.stats.deferAdmission.resolve();await tick();assert.equal(f.stats.captures,0);await f.finish();
 }finally{f.restore();}
});
test('empty admission response exposes an error and verifies status without microphone or paid turn',async()=>{
 const f=await page('invalid-admission',{invalidAdmission:true});try{
  assert.equal(f.nodes['#live-error'].hidden,false);assert.match(f.nodes['#live-error'].textContent,/sesi yang valid/);assert.equal(f.stats.captures,0);assert.equal(f.stats.requests.filter(r=>r.url.endsWith('/active')).length,2);assert.equal(f.stats.requests.filter(r=>r.method==='POST').length,1);await f.finish();
 }finally{f.restore();}
});
test('audio preparation has a distinct label and a finite failure before any admission',async()=>{
 const f=await page('prepare-timeout',{pendingAudio:true});try{
  assert.equal(f.nodes['#live-state'].textContent,'Menyiapkan audio');[...f.timers.values()].find(t=>t.ms===5000).fn();await tick();assert.equal(f.nodes['#live-error'].hidden,false);assert.equal(f.nodes['#live-active'].hidden,true);assert.equal(f.stats.requests.filter(r=>r.method==='POST').length,0);f.stats.deferAudio.resolve();await tick();await f.finish();
 }finally{f.restore();}
});

test('real page adapter rotates a minute of idle synthetic capture without End or provider submission',async()=>{
 const f=await page('idle');try{f.stats.now=60001;f.monitor();await tick();assert.equal(f.stats.captures,2);assert.equal(f.stats.mics,1);assert.equal(f.nodes['#live-state'].textContent,'Mendengarkan mode rekaman');assert.equal(f.nodes['#live-active'].hidden,false);assert.equal(f.nodes['#live-error'].hidden,true);assert.equal(f.stats.requests.filter(r=>r.method==='POST').length,1);await f.finish();}finally{f.restore();}
});

test('two seconds after voice sends the full synthetic recording once, with capture off during playback',async()=>{
 const f=await page('speech');try{
  f.stats.now=1000;f.stats.rms=.1;f.monitor();f.stats.rms=0;f.stats.now=2999;f.monitor();assert.equal(f.stats.requests.filter(r=>r.url.includes('/turns/')&&r.method==='POST').length,0);
  f.stats.now=3000;f.monitor();await tick();assert.equal(f.stats.plays,1);assert.equal(f.stats.mics,0);assert.equal(f.nodes['#live-state'].textContent,'Memutar terjemahan');
  const posts=f.stats.requests.filter(r=>r.url.includes('/turns/')&&r.method==='POST');assert.equal(posts.length,1);assert.equal(await posts[0].body.get('recording').text(),'complete synthetic recording');
  f.sources[0].onended();await tick();assert.equal(f.stats.mics,1);assert.equal(f.stats.captures,2);await f.finish();
 }finally{f.restore();}
});

test('bounded long recording pauses with End visible; no truncated speech reaches the API',async()=>{
 const f=await page('long');try{
  f.stats.rms=.1;f.monitor();f.stats.now=179000;[...f.intervals.values()].find(t=>t.ms===250).fn();await tick();
  assert.equal(f.stats.mics,0);assert.equal(f.nodes['#live-state'].textContent,'Sesi dijeda');assert.equal(f.nodes['#live-resume'].hidden,false);assert.equal(f.nodes['#live-active'].hidden,false);
  assert.match(f.nodes['#live-error'].textContent,/tidak diproses sebagian/);assert.equal(f.stats.requests.some(r=>r.url.includes('/turns/')),false);assert.equal(f.stats.requests.some(r=>r.url.endsWith('/end')),false);await f.finish();
 }finally{f.restore();}
});

test('hidden/unloaded page cancels only its turn; explicit Resume checks it without re-sending the recording',async()=>{
 const f=await page('hidden');try{
  f.stats.deferTurn=deferred();f.stats.rms=.1;f.monitor();f.stats.rms=0;f.stats.now=2000;f.monitor();await tick();
  globalThis.document.hidden=true;f.docEvents.get('visibilitychange')();f.events.get('pagehide')();assert.equal(f.stats.mics,0);assert.equal(f.nodes['#live-state'].textContent,'Sesi dijeda');
  assert.equal(f.stats.beacons.length,1);assert.ok(f.stats.beacons[0].endsWith('/cancel'));assert.equal(f.stats.requests.some(r=>r.url.endsWith('/end')),false);
  f.stats.deferTurn.resolve();await tick();assert.equal(f.stats.plays,0);
  globalThis.document.hidden=false;f.nodes['#live-resume'].click();await tick();assert.equal(f.stats.mics,1);assert.equal(f.nodes['#live-state'].textContent,'Mendengarkan mode rekaman');
  assert.equal(f.stats.requests.filter(r=>r.method==='POST'&&r.url.includes('/turns/')&&!r.url.endsWith('/cancel')).length,1);await f.finish();
 }finally{f.restore();}
});
