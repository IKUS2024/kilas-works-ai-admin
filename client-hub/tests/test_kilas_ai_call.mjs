// Lifecycle/transport with synthetic PCM. No browser, microphone or paid IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {CallInput,CallSession} from '../static/kilas_ai_call_engine.mjs';
import {prepareCallPcm} from '../static/kilas_ai_call_pcm.mjs';
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
test('Captured PCM queued behind an in-flight upload retains every byte and sequential index',async()=>{
 const inFlight=deferred(),requests=[];
 const input=new CallInput({signal:new AbortController().signal,path:'/call',request:async(url,{body})=>{requests.push({url,body});if(requests.length===1)return inFlight.promise;return {accepted_index:requests.length-1};}});
 input.push(pcm());input.open();await tick();
 input.push(new Uint8Array(16000).fill(2));input.push(pcm());
 input.flush();inFlight.resolve({accepted_index:0});await input.chain;
 assert.deepEqual(requests.map(x=>x.url),['/call/chunks/0','/call/chunks/1','/call/chunks/2']);
 assert.deepEqual(Buffer.concat(requests.map(x=>Buffer.from(x.body))),Buffer.concat([Buffer.from(pcm()),Buffer.alloc(16000,2),Buffer.from(pcm())]));
 assert.equal(input.queued,0);assert.equal(input.total,16008);
});
function fixture(options={}){
 const posts=[],bodies=[],states=[],errors=[],captions=[],timers=new Map();let timer=0,captureOptions,stops=0,audioStops=0,plays=0;
 const hold=deferred();
 const f={posts,bodies,states,errors,captions,timers,hold,
  get capture(){return captureOptions;},get stops(){return stops;},get plays(){return plays;},get audioStops(){return audioStops;}};
 const player={push(){plays++;},checkpoint:async()=>{},cancel(){},...options.player};
 const session=new CallSession({key:()=> 'a'.repeat(32),prepare:async()=>{},
  capture:{start:async callbacks=>{captureOptions=callbacks;callbacks.pcm(pcm());},cancel(){stops++;}},stopAudio(){audioStops++;},
  request:async(path,args={})=>{
   if(args.method==='POST'){posts.push(path);if(path.endsWith('/end'))return {};if(path.includes('/chunks/')){bodies.push(args.body);return {accepted_index:Number(path.split('/').at(-1))};}return {call_id:'a'.repeat(32)};}
   if(path.endsWith('/readiness'))return {available:true};
   return hold.promise;
  },onState:value=>states.push(value),onText:text=>captions.push(text),onError:code=>errors.push(code),
  schedule:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clear:id=>timers.delete(id),...options,player});
 f.session=session;f.player=player;return f;
}
test('Restored user-first flow sends no opening/readiness cue and plays only a provider reply',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 assert.equal(f.plays,0);assert.equal(f.captions.at(-1),'');
 assert.equal(f.posts.some(path=>path.endsWith('/ready')),false);
 assert.deepEqual(f.posts,['/kilas-ai/call/'+'a'.repeat(32),'/kilas-ai/call/'+'a'.repeat(32)+'/chunks/0']);
 assert.deepEqual([...f.bodies[0]],[1,0,2,0]);
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},
  {index:1,type:'text',text:'Synthetic relevant reply'},{index:2,type:'turn_complete'}],next_index:3,total_frames:3});
 await tick();assert.equal(f.plays,1);assert.equal(f.captions.at(-1),'Synthetic relevant reply');
 f.session.end();await started;assert.deepEqual(f.errors,[]);
});
test('A reply arriving before upload ACK preserves the captured question tail in order',async()=>{
 const ack=deferred(),requests=[];let f;
 f=fixture({request:async(path,args={})=>{
  if(path==='/kilas-ai/call/readiness')return {available:true};
  if(path.endsWith('/end'))return {};
  if(args.method==='POST'&&!path.includes('/chunks/'))return {call_id:'a'.repeat(32)};
  if(path.includes('/chunks/')){
   const index=Number(path.split('/').at(-1));requests.push({index,raw:args.body.slice()});
   if(index===0)await ack.promise;return {accepted_index:index};
  }
  return f.hold.promise;
 }});
 const started=f.session.start();await tick();
 const queued=new Uint8Array(16000).fill(7),tail=new Uint8Array(6400).fill(9);
 f.capture.pcm(queued);f.capture.pcm(tail);await tick();assert.equal(requests.length,1);
 f.hold.resolve({state:'SPEAKING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')}],next_index:1,total_frames:1});
 await tick();assert.equal(f.session.state,'speaking');
 f.session.input.flush();ack.resolve();await f.session.input.chain;await tick();
 const expected=Buffer.concat([Buffer.from(pcm()),Buffer.from(prepareCallPcm(queued)),Buffer.from(prepareCallPcm(tail))]);
 const actual=Buffer.concat(requests.map(value=>Buffer.from(value.raw)));
 try{assert.equal(actual.length,expected.length,'already captured user audio was discarded at reply start');assert.deepEqual(actual,expected);assert.deepEqual(requests.map(value=>value.index),[0,1,2]);}
 finally{f.session.end();await started;}
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
test('Server audio stays Speaking through actual queue drain; mic resumes for next turn',async()=>{
 const playback=deferred();const f=fixture({player:{checkpoint:()=>playback.promise}}),started=f.session.start();await tick();
 const before=f.session.input.total;
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'text',text:'Hello'},{index:2,type:'turn_complete'}],next_index:3,total_frames:3});
 await tick();assert.equal(f.session.state,'speaking');assert.equal(f.plays,1);assert.equal(f.captions.at(-1),'Hello');
 f.capture.pcm(pcm());assert.equal(f.session.input.total,before+4);
 f.session.input.flush();await f.session.input.chain;assert.deepEqual([...f.bodies.at(-1)],[0,0,0,0]);
 playback.resolve();await tick();assert.equal(f.session.state,'speaking');
 f.capture.pcm(pcm());assert.deepEqual([...f.session.input.pending.slice(0,f.session.input.length)],Array(4).fill(0));
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

test('A new answer arriving before the prior checkpoint drains cannot reopen the microphone',async()=>{
 const playback=deferred(),f=fixture({player:{checkpoint:()=>playback.promise}}),started=f.session.start();await tick();
 const encoded=Buffer.from(pcm()).toString('base64');
 f.hold.resolve({state:'SPEAKING',frames:[{index:0,type:'audio',pcm:encoded},{index:1,type:'turn_complete'},{index:2,type:'audio',pcm:encoded}],next_index:3,total_frames:3});
 await tick();assert.equal(f.plays,2);playback.resolve();await tick();
 assert.equal(f.session.state,'speaking');assert.equal([...f.timers.values()].some(value=>value.ms===300),false);
 f.capture.pcm(pcm());f.session.input.flush();await f.session.input.chain;assert.deepEqual([...f.bodies.at(-1)],[0,0,0,0]);
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

test('Provider reset without replacement audio keeps visible state consistent with the reopened microphone',async()=>{
 let cancellations=0;
 const f=fixture({player:{cancel(){cancellations++;}}}),started=f.session.start();await tick();
 const encoded=Buffer.from(pcm()).toString('base64');
 // The backend emits reset on interrupted=true but retains SPEAKING until
 // turnComplete. No replacement audio or turnComplete is required in that
 // provider message, so this is a valid snapshot of the current backend.
 f.hold.resolve({state:'SPEAKING',frames:[{index:0,type:'audio',pcm:encoded},
  {index:1,type:'reset'}],next_index:2,total_frames:2});
 await tick();
 try{
  assert.equal(f.plays,1);assert.equal(cancellations,1);
  assert.equal(f.session.speaking,false,'reset must reopen the current microphone gate');
  f.capture.pcm(pcm());f.session.input.flush();await f.session.input.chain;
  assert.deepEqual([...f.bodies.at(-1)],[1,0,2,0],'microphone PCM after reset is live, not playback silence');
  assert.equal(f.session.state,'listening','visible state must reflect the live microphone after reset');
  assert.equal(f.states.at(-1),'listening');
 }finally{f.session.end();await started;}
});
