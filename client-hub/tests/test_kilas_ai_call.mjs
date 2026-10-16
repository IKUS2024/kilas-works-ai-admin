// Lifecycle/transport with synthetic PCM. No browser, microphone or paid IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {CallInput,CallSession} from '../static/kilas_ai_call_engine.mjs';
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
 assert.throws(()=>input.push(pcm()),/call_limit/);controller.abort();input.cancel();await tick();assert.equal(requests,0);
});
test('Input wrong acknowledgment is terminal and never retried',async()=>{
 let requests=0,error;const input=new CallInput({signal:new AbortController().signal,path:'/call',onError:e=>{error=e;},request:async()=>{requests++;return {accepted_index:99};}});
 input.push(pcm());input.open();await input.chain.catch(()=>{});await tick();assert.equal(error.code,'call_input_invalid');assert.equal(requests,1);
});
function fixture(options={}){
 const posts=[],states=[],errors=[],captions=[],timers=new Map();let timer=0,captureOptions,stops=0,audioStops=0,plays=0;
 const hold=deferred();
 const f={posts,states,errors,captions,timers,hold,
  get capture(){return captureOptions;},get stops(){return stops;},get plays(){return plays;},get audioStops(){return audioStops;}};
 const player={push(){plays++;},checkpoint:async()=>{},cancel(){},...options.player};
 const session=new CallSession({key:()=> 'a'.repeat(32),prepare:async()=>{},
  capture:{start:async callbacks=>{captureOptions=callbacks;callbacks.pcm(pcm());},cancel(){stops++;}},stopAudio(){audioStops++;},
  request:async(path,args={})=>{
   if(args.method==='POST'){posts.push(path);if(path.endsWith('/end'))return {};if(path.includes('/chunks/'))return {accepted_index:Number(path.split('/').at(-1))};return {call_id:'a'.repeat(32)};}
   if(path.endsWith('/readiness'))return {available:true};
   return hold.promise;
  },onState:value=>states.push(value),onText:text=>captions.push(text),onError:code=>errors.push(code),
  schedule:(fn,ms)=>{timers.set(++timer,{fn,ms});return timer;},clear:id=>timers.delete(id),...options,player});
 f.session=session;f.player=player;return f;
}
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
 f.capture.pcm(pcm());assert.equal(f.session.input.total,before);
 playback.resolve();await tick();assert.equal(f.session.state,'listening');f.capture.pcm(pcm());assert.equal(f.session.input.total,before+4);
 f.session.end();await started;assert.equal(f.timers.size,0);
});
test('Playback rejection ends microphone/transport and never auto-admits a replacement',async()=>{
 const f=fixture({player:{checkpoint:async()=>{throw Error('speaker stalled');}}}),started=f.session.start();await tick();
 f.hold.resolve({state:'LISTENING',frames:[{index:0,type:'audio',pcm:Buffer.from(pcm()).toString('base64')},{index:1,type:'turn_complete'}],next_index:2,total_frames:2});
 await started;assert.equal(f.session.state,'ended');assert.equal(f.stops,1);assert.equal(f.audioStops,1);assert.deepEqual(f.errors,['call_transport']);
 assert.equal(f.posts.filter(x=>!x.includes('/chunks/')&&!x.endsWith('/end')).length,1);
});
test('Client hard limit ends capture even while server polling is pending',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 const hard=[...f.timers.values()].find(x=>x.ms===90000);assert.ok(hard);hard.fn();
 assert.equal(f.session.state,'ended');assert.equal(f.stops,1);assert.deepEqual(f.errors,['call_limit']);
 f.hold.resolve({state:'LISTENING',frames:[],next_index:0,total_frames:0});await started;
});
test('Malformed stream cursor fails once without passing any audio to player',async()=>{
 const f=fixture(),started=f.session.start();await tick();
 f.hold.resolve({state:'SPEAKING',frames:[{index:9,type:'audio',pcm:'AQACAA=='}],next_index:1,total_frames:1});
 await started;assert.equal(f.plays,0);assert.deepEqual(f.errors,['call_protocol']);
});
