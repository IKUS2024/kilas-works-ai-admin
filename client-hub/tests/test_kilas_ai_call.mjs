// Lifecycle/transport with synthetic PCM. No browser, microphone or paid IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CallInput,CallSession,callLanguage} from '../static/kilas_ai_call_engine.mjs';
import {PcmEncoder} from '../static/kilas_live_translator_pcm.mjs';
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
const pcm=()=>new Uint8Array([1,0,2,0]);

test('Input waits for admission, preserves every byte and batches to bounded sequential POSTs',async()=>{
 const controller=new AbortController(),requests=[],source=[];
 const input=new CallInput({signal:controller.signal,path:'/call',request:async(url,{body})=>{requests.push({url,body});return {accepted_index:requests.length-1};}});
 input.push(pcm());await tick();assert.equal(requests.length,0);input.open();await input.chain;
 for(let i=0;i<100;i++){const raw=new Uint8Array(3200).fill(i);source.push(raw);input.push(raw);await input.chain;}
 input.flush();await input.chain;
 assert.equal(requests.length,21);assert.ok(requests.every(x=>x.body.length<=16000));
 assert.deepEqual(Buffer.concat(requests.map(x=>Buffer.from(x.body))),Buffer.concat([Buffer.from(pcm()),...source.map(x=>Buffer.from(x))]));
 assert.equal(input.queued,0);
});
test('Input cancellation before admission sends no audio and bounded backlog fails',async()=>{
 const controller=new AbortController();let requests=0;
 const input=new CallInput({signal:controller.signal,path:'/call',request:async()=>{requests++;}});
 for(let i=0;i<16;i++)input.push(new Uint8Array(16000));
 assert.throws(()=>input.push(pcm()),/call_backlog/);controller.abort();input.cancel();await tick();assert.equal(requests,0);
});
test('Input wrong acknowledgment is terminal and never retried',async()=>{
 let requests=0,error;const input=new CallInput({signal:new AbortController().signal,path:'/call',onError:e=>{error=e;},request:async()=>{requests++;return {accepted_index:99};}});
 input.push(pcm());input.open();await input.chain.catch(()=>{});await tick();assert.equal(error.code,'call_input_invalid');assert.equal(requests,1);
});
test('Delayed microphone uploads retain every queued frame and sequential index',async()=>{
 const inFlight=deferred(),requests=[];
 const input=new CallInput({signal:new AbortController().signal,path:'/call',request:async(url,{body})=>{requests.push({url,body});if(requests.length===1)return inFlight.promise;return {accepted_index:requests.length-1};}});
 input.push(pcm());input.open();await tick();
 input.push(new Uint8Array(16000).fill(2));input.push(pcm());
 input.push(new Uint8Array([7,0]));input.flush();inFlight.resolve({accepted_index:0});await input.chain;
 assert.deepEqual(requests.map(x=>x.url),['/call/chunks/0','/call/chunks/1','/call/chunks/2']);
 assert.deepEqual(Buffer.concat(requests.map(x=>Buffer.from(x.body))),Buffer.concat([Buffer.from(pcm()),Buffer.alloc(16000,2),Buffer.from(pcm()),Buffer.from([7,0])]));
 assert.equal(input.queued,0);assert.equal(input.total,16010);
});
function fixture(options={}){
 const posts=[],postOptions=[],bodies=[],states=[],errors=[],captions=[],timers=new Map();let timer=0,captureOptions,stops=0,audioStops=0,plays=0;
 const hold=deferred();
 const f={posts,postOptions,bodies,states,errors,captions,timers,hold,
  get capture(){return captureOptions;},get stops(){return stops;},get plays(){return plays;},get audioStops(){return audioStops;}};
 const player={push(){plays++;},checkpoint:async()=>{},cancel(){},...options.player};
 const session=new CallSession({key:()=> 'a'.repeat(32),prepare:async()=>{},
  capture:{start:async callbacks=>{captureOptions=callbacks;callbacks.pcm(pcm());},cancel(){stops++;}},stopAudio(){audioStops++;},
  request:async(path,args={})=>{
   if(args.method==='POST'){posts.push(path);postOptions.push(args);if(path.endsWith('/end'))return {};if(path.endsWith('/ready'))return {ready:true};if(path.includes('/chunks/')){bodies.push(args.body);return {accepted_index:Number(path.split('/').at(-1))};}return {call_id:'a'.repeat(32)};}
   if(path.endsWith('/readiness'))return {available:true};
   return hold.promise;
  },onState:value=>states.push(value),onText:text=>captions.push(text),onError:code=>errors.push(code),
  schedule:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clear:id=>timers.delete(id),...options,player});
 f.session=session;f.player=player;return f;
}
const snapshot=(extra={})=>({state:'LISTENING',frames:[],next_index:0,total_frames:0,...extra});
const resumePoll=f=>{const entry=[...f.timers].find(([,value])=>value.ms===250);assert.ok(entry);f.timers.delete(entry[0]);entry[1].fn();};

test('Call uses the established four HTML languages and English fallback',()=>{
 for(const [value,expected] of [['id','id'],['en-US','en'],['es_MX','es'],['zh-Hans','zh'],['  ID-id  ','id'],['fr','en'],['','en'],[undefined,'en']])assert.equal(callLanguage(value),expected);
});
for(const language of ['id','en','es','zh'])test(`Ready is sent once with ${language} only after real capture and provider readiness`,async()=>{
 const f=fixture({getLanguage:()=>language}),started=f.session.start();await tick();
 assert.equal(f.session.captureReady,true);assert.equal(f.posts.some(path=>path.endsWith('/ready')),false);
 f.hold.resolve(snapshot({provider_ready:true}));await tick();
 const at=f.posts.findIndex(path=>path.endsWith('/ready'));assert.ok(at>0);
 assert.deepEqual(f.postOptions[at].json,{language,user_started_speaking:false});
 assert.ok(f.posts.slice(0,at).some(path=>path.endsWith('/chunks/0')));
 assert.equal(f.session.readyAcknowledged,true);
 resumePoll(f);await tick();assert.equal(f.posts.filter(path=>path.endsWith('/ready')).length,1);
 f.session.end();await started;assert.deepEqual(f.errors,[]);
});
test('Provider not ready never receives the greeting handshake',async()=>{
 const f=fixture(),started=f.session.start();await tick();f.hold.resolve(snapshot({provider_ready:false}));await tick();
 assert.equal(f.session.readyRequested,false);assert.equal(f.posts.some(path=>path.endsWith('/ready')),false);
 f.session.end();await started;
});
for(const kind of ['silence','low room noise','brief transient','sustained Indonesian speech'])test(`Startup ${kind} is observed before input gain without filtering any microphone samples`,async t=>{
 let samples;
 if(kind==='sustained Indonesian speech'){
  const wav=readFileSync(new URL('./fixtures/ai_call_synthetic/id-first.wav',import.meta.url));
  samples=Float32Array.from({length:(wav.length-44)/2},(_,i)=>wav.readInt16LE(44+i*2)/32768);
 }else{
  let seed=17;samples=Float32Array.from({length:16000},(_,i)=>{
   if(kind==='silence')return 0;
   if(kind==='brief transient')return i<3200?.025*Math.sin(i*.37):0;
   seed=(1664525*seed+1013904223)>>>0;return (seed/2**32*2-1)*.0035;
  });
 }
 const frames=[],encoder=new PcmEncoder(16000,frame=>frames.push(frame));
 for(let i=0;i<samples.length;i+=128)encoder.feed([samples.subarray(i,i+128)]);encoder.finish();
 const f=fixture({getLanguage:()=> 'id'}),started=f.session.start();await tick();
 for(const frame of frames){const raw=new Uint8Array(frame.bytes);f.capture.pcm(raw);f.capture.level(frame.rms,raw.length/32);}
 f.hold.resolve(snapshot({provider_ready:true}));await tick();
 const readyAt=f.posts.findIndex(path=>path.endsWith('/ready'));assert.ok(readyAt>=0);
 const shouldSuppress=kind==='sustained Indonesian speech';assert.equal(f.postOptions[readyAt].json.user_started_speaking,shouldSuppress);
 f.session.input.flush();await f.session.input.chain;
 assert.equal(f.bodies.reduce((n,raw)=>n+raw.length,0),4+samples.length*2);
 t.diagnostic(JSON.stringify({synthetic:true,kind,input_ms:samples.length/16,max_raw_rms:Math.max(...frames.map(frame=>frame.rms)),user_started_speaking:shouldSuppress}));
 f.session.end();await started;assert.deepEqual(f.errors,[]);
});
test('Ready awaits first buffered PCM without blocking playback/reset and includes speech observed while waiting',async()=>{
 const firstChunk=deferred(),events=[],bodies=[],playback=deferred();let cancelled=0;
 const encoded=Buffer.from(pcm()).toString('base64');let poll=0;
 const f=fixture({getLanguage:()=> 'id-ID',player:{checkpoint:()=>playback.promise,cancel(){cancelled++;playback.reject(new DOMException('Aborted','AbortError'));}},request:async(path,args={})=>{
  if(path.endsWith('/readiness'))return {available:true};
  if(args.method==='POST'){
   events.push({path,json:args.json});
   if(path.includes('/chunks/')){bodies.push(args.body);const index=Number(path.split('/').at(-1));if(index===0)return firstChunk.promise;return {accepted_index:index};}
   if(path.endsWith('/ready'))return {ready:true};if(path.endsWith('/end'))return {};
   return {call_id:'a'.repeat(32)};
  }
  if(poll++===0)return snapshot({provider_ready:true,state:'SPEAKING',frames:[{index:0,type:'audio',pcm:encoded},{index:1,type:'turn_complete'}],next_index:2,total_frames:2});
  return snapshot({provider_ready:true,frames:[{index:2,type:'reset'},{index:3,type:'turn_complete'}],next_index:4,total_frames:4});
 }});
 const started=f.session.start();await tick();
 assert.equal(f.session.readyRequested,true);assert.equal(events.some(event=>event.path.endsWith('/ready')),false);assert.equal(f.session.state,'speaking');
 // This first utterance must survive both the model audio start and reset.
 f.capture.level(.006,200);f.capture.level(.007,200);f.capture.pcm(new Uint8Array([3,0,4,0]));
 resumePoll(f);await tick();assert.equal(f.session.state,'listening');assert.equal(cancelled,1);assert.deepEqual(f.errors,[]);
 firstChunk.resolve({accepted_index:0});await tick();
 const ready=events.find(event=>event.path.endsWith('/ready'));assert.deepEqual(ready.json,{language:'id',user_started_speaking:true});
 assert.deepEqual(Buffer.concat(bodies.map(body=>Buffer.from(body))),Buffer.from([1,0,2,0,3,0,4,0]));
 assert.equal(f.session.echoGuard,true);assert.equal(f.session.state,'listening');
 f.session.end();await started;
});
test('End while first mic upload is pending prevents late ready and ignores aborted ready work',async()=>{
 const firstChunk=deferred(),events=[];
 const f=fixture({request:async(path,args={})=>{
  if(path.endsWith('/readiness'))return {available:true};
  if(args.method==='POST'){events.push(path);if(path.includes('/chunks/'))return firstChunk.promise;if(path.endsWith('/end'))return {};return {call_id:'a'.repeat(32)};}
  return snapshot({provider_ready:true});
 }}),started=f.session.start();await tick();assert.equal(f.session.readyRequested,true);
 f.session.end();firstChunk.resolve({accepted_index:0});await started;await tick();
 assert.equal(events.some(path=>path.endsWith('/ready')),false);assert.deepEqual(f.errors,[]);assert.equal(f.timers.size,0);
});
test('Provider reset immediately listens and preserves real quiet mic at unity gain through speaker decay',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 f.hold.resolve(snapshot({frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'text',text:'Interrupted answer'},{index:2,type:'reset'}],next_index:3,total_frames:3}));await tick();
 assert.equal(f.session.state,'listening');assert.equal(f.captions.at(-1),'');
 const raw=new Uint8Array([128,0,128,0]);f.capture.pcm(raw);f.session.input.flush();await f.session.input.chain;
 assert.deepEqual(f.bodies.at(-1),raw);
 const guard=[...f.timers].find(([,value])=>value.ms===300);assert.ok(guard);f.timers.delete(guard[0]);guard[1].fn();
 f.capture.pcm(raw);f.session.input.flush();await f.session.input.chain;
 assert.deepEqual([...f.bodies.at(-1)],[0,4,0,4]);assert.deepEqual([...raw],[128,0,128,0]);
 f.session.end();guard[1].fn();await started;assert.equal(f.session.echoGuard,false);assert.equal(f.session.state,'ended');
});
test('New output fences a reset decay callback without stopping the live microphone',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 const value=snapshot({frames:[{index:0,type:'reset'}],next_index:1,total_frames:1});f.hold.resolve(value);await tick();
 const guard=[...f.timers.values()].find(value=>value.ms===300);assert.ok(guard);
 Object.assign(value,{state:'SPEAKING',frames:[{index:1,type:'audio',pcm:Buffer.from(pcm()).toString('base64')}],next_index:2,total_frames:2});resumePoll(f);await tick();
 guard.fn();assert.equal(f.session.state,'speaking');assert.equal(f.session.speaking,true);assert.equal(f.session.echoGuard,false);
 f.capture.pcm(new Uint8Array([128,0,128,0]));await f.session.input.chain;assert.deepEqual([...f.bodies.at(-1)],[128,0,128,0]);
 f.session.end();await started;assert.deepEqual(f.errors,[]);
});
test('Malformed ready acknowledgment ends once and never automatically retries admission or greeting',async()=>{
 const events=[];const f=fixture({request:async(path,args={})=>{
  if(path.endsWith('/readiness'))return {available:true};
  if(args.method==='POST'){events.push(path);if(path.includes('/chunks/'))return {accepted_index:Number(path.split('/').at(-1))};if(path.endsWith('/ready'))return {};return {call_id:'a'.repeat(32)};}
  return snapshot({provider_ready:true});
 }});await f.session.start();assert.deepEqual(f.errors,['call_protocol']);
 assert.equal(events.filter(path=>path.endsWith('/ready')).length,1);assert.equal(events.filter(path=>/\/[a-f0-9]{32}$/.test(path)).length,1);
});
test('Readiness denial never captures microphone, admits or schedules retry',async()=>{
 let mic=0,posts=0;
 const f=fixture({capture:{start(){mic++;},cancel(){}},request:async(path,args={})=>{if(args.method)posts++;return {available:false,reason:'budget_limit'};}});
 await f.session.start();assert.equal(mic,0);assert.equal(posts,0);assert.deepEqual(f.errors,['budget_limit']);assert.equal(f.session.state,'ended');assert.equal(f.timers.size,0);
});
test('Microphone permission failure precedes paid admission',async()=>{
 const f=fixture({capture:{async start(){throw Object.assign(Error('denied'),{code:'microphone_permission_denied'});},cancel(){}}});
 await f.session.start();assert.equal(f.posts.length,0);assert.deepEqual(f.errors,['microphone_permission_denied']);
});
test('End during pending readiness fences all late callbacks',async()=>{
 const ready=deferred();let captured=0;
 const f=fixture({request:()=>ready.promise,capture:{start(){captured++;},cancel(){}}});
 const started=f.session.start();await tick();f.session.end();ready.resolve({available:true});await started;
 assert.equal(captured,0);assert.equal(f.session.state,'ended');assert.equal(f.errors.length,0);
});
test('End during pending Start sends owned nonce cancellation and ignores late admission',async()=>{
 const admitted=deferred(),posts=[];
 const f=fixture({request:async(path,args={})=>{if(!args.method)return {available:true};posts.push(path);if(path.endsWith('/end'))return {};return admitted.promise;}});
 const started=f.session.start();await tick();assert.equal(posts.length,1);assert.ok(f.capture);
 f.session.end();assert.equal(f.stops,1);assert.equal(f.audioStops,1);assert.ok(posts[1].endsWith('/'+'a'.repeat(32)+'/end'));
 admitted.resolve({call_id:'a'.repeat(32)});await started;assert.equal(posts.length,2);assert.equal(f.session.state,'ended');
});
test('Server audio stays Speaking through actual queue drain while real mic speech remains live',async()=>{
 const playback=deferred();const f=fixture({player:{checkpoint:()=>playback.promise}}),started=f.session.start();await tick();
 const before=f.session.input.total;
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'text',text:'Hello'},{index:2,type:'turn_complete'}],next_index:3,total_frames:3});
 await tick();assert.equal(f.session.state,'speaking');assert.equal(f.plays,1);assert.equal(f.captions.at(-1),'Hello');
 f.capture.pcm(pcm());assert.equal(f.session.input.total,before+4);
 await tick();assert.deepEqual([...f.bodies.at(-1)],[1,0,2,0]);
 playback.resolve();await tick();assert.equal(f.session.state,'speaking');
 f.capture.pcm(pcm());await tick();assert.deepEqual([...f.bodies.at(-1)],[1,0,2,0]);
 const guard=[...f.timers].find(([,value])=>value.ms===300);assert.ok(guard);f.timers.delete(guard[0]);guard[1].fn();
 assert.equal(f.session.state,'listening');f.capture.pcm(pcm());assert.equal(f.session.input.total,before+12);
 assert.deepEqual([...f.session.input.pending.slice(-4+f.session.input.length,f.session.input.length)],[1,0,2,0]);
 f.session.end();await started;assert.equal(f.timers.size,0);
});
test('Playback rejection ends microphone/transport and never auto-admits a replacement',async()=>{
 const f=fixture({player:{checkpoint:async()=>{throw Error('speaker stalled');}}}),started=f.session.start();await tick();
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'turn_complete'}],next_index:2,total_frames:2});
 await started;assert.equal(f.session.state,'ended');assert.equal(f.stops,1);assert.equal(f.audioStops,1);assert.deepEqual(f.errors,['call_transport']);
 assert.equal(f.posts.filter(x=>!x.includes('/chunks/')&&!x.endsWith('/end')).length,1);
});
test('A synchronous audio failure fences the rest of its poll batch after End',async()=>{
 let f;f=fixture({player:{push(){f.session.fail({code:'call_audio'});}}});const started=f.session.start();await tick();
 f.hold.resolve({state:'SPEAKING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'text',text:'Late answer'},{index:2,type:'turn_complete'}],next_index:3,total_frames:3});
 await started;assert.equal(f.session.state,'ended');assert.deepEqual(f.errors,['call_audio']);assert.equal(f.captions.at(-1),'');assert.ok(!f.captions.includes('Late answer'));assert.equal(f.stops,1);
});
test('Call has no client duration deadline and End cancels pending polling',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 assert.equal([...f.timers.values()].find(x=>x.ms===90000),undefined);
 assert.notEqual(f.session.state,'ended');f.session.end();
 assert.equal(f.session.state,'ended');assert.equal(f.stops,1);assert.deepEqual(f.errors,[]);
 f.hold.resolve({state:'LISTENING',frames:[],next_index:0,total_frames:0});await started;
});
test('More than sixty seconds of sequential PCM retains all bytes without a session cap',async()=>{
 let bytes=0,index=0;const input=new CallInput({signal:new AbortController().signal,path:'/call',request:async(url,{body})=>{bytes+=body.length;return {accepted_index:index++};}});
 input.open();for(let i=0;i<300;i++){input.push(new Uint8Array(16000));await input.chain;}
 input.flush();await input.chain;assert.equal(bytes,4800000);assert.equal(input.queued,0);
});
test('Malformed stream cursor fails once without passing any audio to player',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 f.hold.resolve({state:'SPEAKING',frames:[{index:9,type:'audio',pcm:'AQACAA=='}],next_index:1,total_frames:1});
 await started;assert.equal(f.plays,0);assert.deepEqual(f.errors,['call_protocol']);
});

test('End during echo clearance fences late resume and releases all timers',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'turn_complete'}],next_index:2,total_frames:2});
 await tick();const guard=[...f.timers.values()].find(value=>value.ms===300);assert.ok(guard);
 f.session.end();guard.fn();await started;assert.equal(f.session.state,'ended');assert.equal(f.timers.size,0);
});

test('A new answer fences prior drain state without suppressing interrupting microphone speech',async()=>{
 const playback=deferred(),f=fixture({player:{checkpoint:()=>playback.promise}}),started=f.session.start();await tick();
 const encoded=Buffer.from(pcm()).toString('base64');
 f.hold.resolve({state:'SPEAKING',frames:[{index:0,type:'audio',pcm:encoded},{index:1,type:'turn_complete'},{index:2,type:'audio',pcm:encoded}],next_index:3,total_frames:3});
 await tick();assert.equal(f.plays,2);playback.resolve();await tick();
 assert.equal(f.session.state,'speaking');assert.equal([...f.timers.values()].some(value=>value.ms===300),false);
 f.capture.pcm(pcm());await tick();assert.deepEqual([...f.bodies.at(-1)],[1,0,2,0]);
 f.session.end();await started;
});

test('Public sources attach to their answer and clear for a subsequent answer',async()=>{
 const sources=[],citations=[{url:'https://example.org/news',title:'Synthetic public source'}];
 const f=fixture({onSources:(items,date)=>sources.push({items,date})}),started=f.session.start();await tick();
 const encoded=Buffer.from(pcm()).toString('base64');
 f.hold.resolve({state:'SPEAKING',frames:[{index:0,type:'sources',citations,checked_on:'2026-10-17'},
  {index:1,type:'audio',pcm:encoded},{index:2,type:'turn_complete'},{index:3,type:'audio',pcm:encoded}],next_index:4,total_frames:4});
 await tick();assert.deepEqual(sources.map(value=>value.items),[[],citations,[]]);
 assert.equal(sources[1].date,'2026-10-17');assert.equal(f.plays,2);
 f.session.end();await started;assert.deepEqual(sources.at(-1).items,[]);
});
test('Waiting for public lookup results keeps microphone live; End fences late sources',async()=>{
 const sources=[],f=fixture({onSources:items=>sources.push(items)}),started=f.session.start();await tick();
 assert.equal(f.session.speaking,false);f.capture.pcm(pcm());
 assert.deepEqual([...f.session.input.pending.slice(0,f.session.input.length)],[1,0,2,0]);
 f.session.end();
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'sources',citations:[{url:'https://example.org',title:'Late'}]}],next_index:1,total_frames:1});
 await started;assert.ok(sources.every(items=>items.length===0));assert.equal(f.session.state,'ended');
});
