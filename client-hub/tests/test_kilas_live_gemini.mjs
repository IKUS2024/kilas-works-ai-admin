// Synthetic clocks, PCM, transport and capture. No browser/provider/microphone.
import test from 'node:test';
import assert from 'node:assert/strict';
import {GeminiPlayer} from '../static/kilas_live_gemini_player.mjs';
import {GeminiSession} from '../static/kilas_live_gemini_engine.mjs';
const tick=async()=>{for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));};
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const pcm=()=>new Uint8Array(9600);
function clock(){let time=0,id=0;const timers=new Map();return {now:()=>time,schedule:(fn,ms)=>{const key=++id;timers.set(key,{fn,at:time+ms});return key;},clear:key=>timers.delete(key),advance(ms){time+=ms;const due=[...timers].filter(([,v])=>v.at<=time);for(const [key,v] of due){timers.delete(key);v.fn();}},timers};}
function audio(){
 const starts=[],nodes=[];const context={currentTime:0,state:'running',destination:{},
  createBuffer(channels,length,rate){assert.equal(channels,1);assert.equal(rate,24000);return {length,duration:length/rate,getChannelData:()=>new Float32Array(length)};},
  createBufferSource(){const node={connect(){},disconnect(){},stop(){node.stopped=true;},start(at){starts.push(at);}};nodes.push(node);return node;}};
 return {context,starts,nodes};
}

test('PCM prebuffer schedules consecutive buffers on one audio clock and drains the final short buffer',async()=>{
 const c=clock(),a=audio();const player=new GeminiPlayer({...c,getContext:()=>a.context});
 player.push(pcm());assert.equal(a.starts.length,0);
 player.push(pcm());assert.deepEqual(a.starts,[.02,.22]);
 const last=new Uint8Array(480);player.push(last);
 assert.ok(Math.abs(a.starts[2]-.42)<1e-8);
 let done=false;const drained=player.drain().then(()=>{done=true;});await tick();assert.equal(done,false);
 a.context.currentTime=.1;a.nodes[0].onended(); // First clip is still playing: must fail, not drop its end.
 await assert.rejects(drained,error=>error.code==='audio_stalled');
});

test('complete audio drains only after every sample; missing onended uses audio-clock completion',async()=>{
 const c=clock(),a=audio();const player=new GeminiPlayer({...c,getContext:()=>a.context});player.push(pcm());
 let done=false;const drained=player.drain().then(()=>{done=true;});assert.equal(a.starts.length,1);await tick();assert.equal(done,false);
 a.context.currentTime=.1;c.advance(250);await tick();assert.equal(done,false);
 a.context.currentTime=.6;c.advance(250);await drained;assert.equal(done,true);
});

test('continuous PCM cannot hide a stalled clock and End cancels every scheduled node',async()=>{
 const c=clock(),a=audio(),errors=[];const player=new GeminiPlayer({...c,getContext:()=>a.context,onError:e=>errors.push(e.code)});
 player.push(pcm());player.push(pcm());
 for(let i=0;i<5;i++){c.advance(1000);if(!player.failed)player.push(pcm());}
 assert.deepEqual(errors,['audio_stalled']);assert.ok(a.nodes.every(n=>n.stopped));
 const next=new GeminiPlayer({...c,getContext:()=>a.context});next.push(pcm());const drain=next.drain();next.cancel();
 await assert.rejects(drain,{name:'AbortError'});assert.ok(a.nodes.every(n=>n.stopped));
});

test('slow audio-clock progress cannot extend an accepted PCM drain beyond its absolute wall deadline',async()=>{
 const c=clock(),a=audio(),errors=[],player=new GeminiPlayer({...c,getContext:()=>a.context,onError:error=>errors.push(error.code)});
 player.push(pcm());const drain=player.drain(),rejected=assert.rejects(drain,error=>error.code==='audio_stalled');
 // The clock advances each second, preventing the ordinary no-progress timeout.
 for(let seconds=1;seconds<=6;seconds++){a.context.currentTime=seconds*.001;c.advance(1000);await tick();}
 await rejected;assert.deepEqual(errors,['audio_stalled']);assert.ok(a.nodes.every(node=>node.stopped));assert.equal(player.deadlines.size,0);
});

test('queue is bounded and malformed PCM never enters playback',()=>{
 const c=clock(),a=audio(),player=new GeminiPlayer({...c,getContext:()=>a.context});
 assert.throws(()=>player.push(new Uint8Array(3)),/gemini_pcm_invalid/);
 for(let i=0;i<40;i++)player.push(pcm());
 assert.throws(()=>player.push(pcm()),/gemini_playback_backlog/);player.cancel();
});

test('a nonclosing checkpoint includes short prebuffered PCM and later audio does not postpone it',async()=>{
 const c=clock(),a=audio(),player=new GeminiPlayer({...c,getContext:()=>a.context});
 player.push(new Uint8Array(480),'first');let completed=false;const checkpoint=player.checkpoint().then(()=>{completed=true;});
 assert.equal(a.starts.length,1);player.push(pcm(),'second');assert.equal(a.starts.length,2);
 a.context.currentTime=.04;a.nodes[0].onended();await checkpoint;assert.equal(completed,true);assert.equal(player.nodes.size,1);assert.equal(player.closed,false);
 player.cancel();
});

test('provider interruption cancels only its own turn while previous accepted audio keeps playing',async()=>{
 const c=clock(),a=audio(),player=new GeminiPlayer({...c,getContext:()=>a.context});
 player.push(pcm(),'previous');player.push(pcm(),'current');let previousDone=false;const checkpoint=player.checkpoint().catch(error=>error);
 player.interrupt('current');assert.equal(a.nodes[0].stopped,undefined);assert.equal(a.nodes[1].stopped,true);assert.equal(player.pendingSamples,4800);
 assert.equal((await checkpoint).name,'AbortError');
 const previous=player.checkpoint().then(()=>{previousDone=true;});player.push(pcm(),'current');assert.ok(Math.abs(a.starts[2]-.22)<1e-8);
 a.context.currentTime=.23;a.nodes[0].onended();await previous;assert.equal(previousDone,true);assert.equal(player.nodes.size,1);player.cancel();
});

function fixture(){
 const requests=[],played=[],states=[],errors=[],warnings=[],tails=deferred(),drained=deferred(),c=clock();let handlers,reads=0,mic=false,keys=0;
 const id='a'.repeat(48),key='live-'+'b'.repeat(32),path='/kilas-translator/live/gemini/sessions/'+id+'/turns/'+key;
 const frame=(index)=>({index,type:'audio',generation:0,pcm:btoa(String.fromCharCode(...new Uint8Array(480)))});
 const player={reset(){},push(raw){played.push({raw,mic});},interrupt(){},cancel(){},drain:()=>drained.promise};
 const capture={async start(value){handlers=value;mic=true;value.ready();},finalize(){mic=false;handlers.blob(null);},cancel(){mic=false;}};
 const json=async(url,options={})=>{
  requests.push({url,...options});
  if(url==='/kilas-translator/live/gemini/sessions')return {session_id:id,input_mode:'gemini-live-v1'};
  if(url.endsWith('/end'))return {status:'ENDED'};
  if(url.endsWith('/chunks/0'))return {accepted_index:0};
  if(url.endsWith('/chunks/1'))return {accepted_index:1};
  if(url.endsWith('/finish'))return {status:'DRAINING'};
  if(options.method==='POST')return {input_mode:'gemini-live-v1'};
  if(reads++===0)return {status:'PROCESSING',frames:[frame(0)],next_index:1,translated_text:'Repeat. ',output_closed:false};
  return tails.promise;
 };
 const session=new GeminiSession({...c,json,capture,player,csrf:'synthetic',prepare:async()=>{},key:()=> (++keys).toString(16).padStart(32,'b'),onState:s=>states.push(s),onError:e=>errors.push(e),onWarning:w=>warnings.push(w)});
 return {session,requests,played,states,errors,warnings,tails,drained,c,id,path,frame,get handlers(){return handlers;},get mic(){return mic;}};
}

test('native output plays during capture; Finish flushes partial input and preserves the logical session after bounded drain',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();
 assert.equal(f.played.length,1);assert.equal(f.played[0].mic,true);assert.equal(f.mic,true);
 f.handlers.pcm(new Uint8Array(122));f.session.finish();await tick();
 const uploads=f.requests.filter(r=>r.url.includes('/chunks/'));
 assert.equal(uploads.length,2);assert.deepEqual(await uploads[0].body.get('pcm').arrayBuffer(),new Uint8Array(6400).buffer);
 assert.equal(uploads[1].body.get('pcm').size,122);
 assert.equal(f.requests.find(r=>r.url.endsWith('/finish')).body.get('count'),'2');
 f.c.advance(200);await tick();
 f.tails.resolve({status:'COMPLETED',frames:[f.frame(1)],next_index:2,translated_text:'Repeat. Accepted tail.',output_closed:true,total_frames:2,completion_kind:'bounded_drain',tail_confirmed:false});await tick();
 assert.equal(f.played.length,2);assert.equal(f.session.active,true);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,0);
 assert.equal(f.mic,true);assert.deepEqual(f.warnings,[{code:'gemini_tail_unconfirmed',completion_kind:'bounded_drain',tail_confirmed:false}]);
 await f.session.end();assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);assert.deepEqual(f.errors,[]);
});

test('late output after End is ignored and does not reopen capture or another provider request',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 await f.session.end();f.tails.resolve({status:'COMPLETED',frames:[f.frame(1)],next_index:2,translated_text:'Late',output_closed:true,total_frames:2});await tick();
 assert.equal(f.played.length,1);assert.equal(f.mic,false);assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url.includes('/turns/')&&r.method==='POST'&&!r.url.includes('/chunks/')&&!r.url.endsWith('/finish')).length,1);
});

test('duplicate or out-of-order output fails closed without paid replay',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'PROCESSING',frames:[f.frame(0)],next_index:2,translated_text:'Repeat.',output_closed:false});await tick();
 assert.equal(f.mic,false);assert.equal(f.session.active,true);assert.deepEqual(f.errors,[]);f.drained.resolve();await tick();
 assert.equal(f.errors.length,1);assert.match(f.errors[0].message,/gemini_output_invalid/);assert.equal(f.session.active,false);assert.equal(f.played.length,1);
});

test('a late admitted session is closed after End; original admission never auto-retries',async()=>{
 const admission=deferred(),requests=[];const f=fixture();f.session.json=async(url,options={})=>{
  requests.push({url,...options});if(url.endsWith('/end'))return {status:'ENDED'};return admission.promise;
 };
 const start=f.session.start(new FormData());await tick();await f.session.end();
 admission.resolve({session_id:f.id,input_mode:'gemini-live-v1'});await start;await tick();
 assert.equal(f.mic,false);assert.equal(requests.length,2);assert.ok(requests[1].url.endsWith('/'+f.id+'/end'));
});

test('an admission rejection after End refreshes Start availability without reopening media',async()=>{
 const f=fixture(),admission=deferred(),availability=[];f.session.json=()=>admission.promise;
 f.session.onAdmissionChange=()=>availability.push({pending:f.session.admissionPending,active:f.session.active});
 const starting=f.session.start(new FormData());await tick();assert.equal(f.session.admissionPending,true);await f.session.end();
 admission.reject(new DOMException('Aborted','AbortError'));await starting;await tick();
 assert.deepEqual(availability,[{pending:false,active:false}]);assert.equal(f.mic,false);assert.deepEqual(f.errors,[]);
});

test('provider interruption clears pending output generation while input capture continues',async()=>{
 const f=fixture();let resets=0;f.session.player.interrupt=()=>{resets++;};
 await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'PROCESSING',frames:[{index:1,type:'reset',generation:1},{...f.frame(2),generation:1}],next_index:3,translated_text:'New generation',output_closed:false});
 await tick();assert.equal(resets,1);assert.equal(f.mic,true);assert.equal(f.played.length,2);assert.equal(f.session.cursor,3);
 await f.session.end();assert.equal(f.mic,false);
});

test('End still cleans media and reaches the server when a UI callback throws',async()=>{
 const f=fixture();await f.session.start(new FormData());f.session.onState=()=>{throw Error('synthetic UI');};
 await f.session.end();assert.equal(f.mic,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('FAILED terminal pages preserve valid final PCM and drain before reporting failure without renewal',async()=>{
 const f=fixture(),json=f.session.json;
 f.session.json=(url,options={})=>url.includes('?after=2')?Promise.resolve({status:'FAILED',code:'gemini_transport',frames:[f.frame(2)],next_index:3,translated_text:'Accepted final samples',output_closed:true,total_frames:3,tail_confirmed:false,completion_kind:null}):json(url,options);
 await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'FAILED',code:'gemini_transport',frames:[f.frame(1)],next_index:2,translated_text:'Accepted samples',output_closed:true,total_frames:3,tail_confirmed:false,completion_kind:null});await tick();
 assert.equal(f.played.length,2);assert.equal(f.mic,false);assert.equal(f.session.active,true);assert.deepEqual(f.errors,[]);
 f.c.advance(200);await tick();assert.equal(f.played.length,3);assert.equal(f.session.active,true);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,0);
 f.drained.resolve();await tick();assert.equal(f.errors.length,1);assert.equal(f.errors[0].code,'gemini_transport');assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
 assert.equal(f.requests.filter(r=>r.method==='POST'&&r.url.includes('/turns/')&&!r.url.includes('/chunks/')&&!r.url.endsWith('/finish')).length,1);
});

test('FAILED final PCM without turnComplete drains on the audio clock before owned-session cleanup',async()=>{
 const f=fixture(),a=audio();f.session.player=new GeminiPlayer({...f.c,getContext:()=>a.context});
 await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'FAILED',code:'gemini_transport',frames:[f.frame(1)],next_index:2,translated_text:'Final accepted PCM',output_closed:true,total_frames:2,tail_confirmed:false,completion_kind:null});await tick();
 assert.equal(a.nodes.length,2);assert.equal(f.session.active,true);assert.deepEqual(f.errors,[]);assert.ok(a.nodes.every(node=>!node.stopped));
 a.context.currentTime=.5;f.c.advance(250);await tick();assert.equal(f.session.active,false);assert.equal(f.errors[0].code,'gemini_transport');
});

test('End immediately cancels a pending terminal drain and late drain cannot end a successor session',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'FAILED',code:'gemini_transport',frames:[f.frame(1)],next_index:2,translated_text:'Tail',output_closed:true,total_frames:2,tail_confirmed:false,completion_kind:null});await tick();
 await f.session.end();assert.equal(f.mic,false);assert.equal(f.session.active,false);
 f.drained.resolve();await tick();assert.deepEqual(f.errors,[]);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('a poll transport failure stops further input immediately and preserves accepted PCM until drained',async()=>{
 const f=fixture();await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 const transport=Object.assign(Error('No poll reply'),{code:'request_timeout'});f.tails.reject(transport);await tick();
 assert.equal(f.session.controller.signal.aborted,true);assert.equal(f.mic,false);assert.equal(f.session.active,true);assert.equal(f.played.length,1);assert.deepEqual(f.errors,[]);
 const requests=f.requests.length;f.handlers.pcm(new Uint8Array(6400));await tick();assert.equal(f.requests.length,requests);
 f.drained.resolve();await tick();assert.equal(f.errors[0],transport);assert.equal(f.session.active,false);assert.equal(f.requests.filter(r=>r.url.endsWith('/end')).length,1);
});

test('FAILED publication before output_closed stops input but still fetches remaining terminal PCM',async()=>{
 const f=fixture(),json=f.session.json;
 f.session.json=(url,options={})=>url.includes('?after=2')?Promise.resolve({status:'FAILED',code:'gemini_transport',frames:[f.frame(2)],next_index:3,translated_text:'Retained final PCM',output_closed:true,total_frames:3}):json(url,options);
 await f.session.start(new FormData());f.handlers.pcm(new Uint8Array(6400));await tick();f.c.advance(200);await tick();
 f.tails.resolve({status:'FAILED',code:'gemini_transport',frames:[f.frame(1)],next_index:2,translated_text:'Publishing terminal PCM',output_closed:false,total_frames:null});await tick();
 assert.equal(f.mic,false);assert.equal(f.session.controller.signal.aborted,false);assert.equal(f.played.length,2);assert.deepEqual(f.errors,[]);
 f.c.advance(200);await tick();assert.equal(f.played.length,3);assert.equal(f.session.active,true);assert.equal(f.session.controller.signal.aborted,true);
 f.drained.resolve();await tick();assert.equal(f.errors[0].code,'gemini_transport');assert.equal(f.session.active,false);
});
