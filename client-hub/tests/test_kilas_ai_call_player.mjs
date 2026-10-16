// Deterministic PCM delivery and hardware clock, without a browser or media.
import test from 'node:test';
import assert from 'node:assert/strict';
import {CallPlayer} from '../static/kilas_ai_call_player.mjs';
import {GeminiPlayer} from '../static/kilas_live_gemini_player.mjs?v=native-progressive-20261016';

function fixture({deviceRate=48000,frozen=false}={}){
 let time=0,id=0;const timers=new Map(),nodes=[],starts=[],errors=[];
 const schedule=(fn,ms)=>{timers.set(++id,{fn,at:time+ms});return id;},clear=id=>timers.delete(id);
 const context={sampleRate:deviceRate,state:'running',get currentTime(){return frozen?0:time/1000;},destination:{},
  createBuffer(channels,length,rate){assert.equal(channels,1);assert.equal(rate,24000);const samples=new Float32Array(length);return {length,sampleRate:rate,duration:length/rate,getChannelData:()=>samples};},
  createBufferSource(){const node={connect(){},disconnect(){},stop(){this.stopped=true;clear(this.timer);},start(at){this.at=at;starts.push({at,duration:this.buffer.duration,samples:this.buffer.getChannelData(0),node:this});if(!frozen)this.timer=schedule(()=>node.onended?.(),(at+this.buffer.duration-context.currentTime)*1000);}};nodes.push(node);return node;}};
 const f={context,timers,nodes,starts,errors,options:{getContext:()=>context,now:()=>time,schedule,clear,onError:e=>errors.push(e.code)},
  advanceTo(end){let loops=0;while(true){const due=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;if(++loops>10000)throw Error('Timer loop');time=due[1].at;timers.delete(due[0]);due[1].fn();}time=end;},
  gaps(){return starts.slice(1).map((x,i)=>Math.max(0,x.at-starts[i].at-starts[i].duration)).filter(x=>x>1/24000);}};
 return f;
}
const pcm=(samples=4800,value=1234)=>{const raw=new Uint8Array(samples*2),view=new DataView(raw.buffer);for(let i=0;i<samples;i++)view.setInt16(i*2,value,true);return raw;};

test('Call jitter cushion removes the reproduced poll-delivery gap without changing the Translator player',async t=>{
 const deliveries=[0,220,590,640,870,1040,1490,1510,1700,1930,2150,2290,2610,2690,2890,3150,3300,3470,3720,3900];
 function deliver(Player){const f=fixture(),player=new Player(f.options);for(const at of deliveries){f.advanceTo(at);player.push(pcm());}const drained=player.checkpoint();f.advanceTo(10000);return {f,player,drained};}
 const baseline=deliver(GeminiPlayer),fixed=deliver(CallPlayer);await Promise.all([baseline.drained,fixed.drained]);
 assert.ok(baseline.f.gaps().length>0);assert.deepEqual(fixed.f.gaps(),[]);
 assert.equal(fixed.f.starts.reduce((n,x)=>n+x.samples.length,0),deliveries.length*4800);
 assert.deepEqual(fixed.f.errors,[]);
 t.diagnostic(JSON.stringify({fixture_only:true,previous_gaps_ms:baseline.f.gaps().map(s=>Math.round(s*1000)),call_gaps_ms:fixed.f.gaps(),previous_first_start_ms:baseline.f.starts[0].at*1000,call_first_start_ms:fixed.f.starts[0].at*1000}));
});
for(const deviceRate of [44100,48000])test(`Call keeps PCM24k sample duration and little-endian values on a ${deviceRate}Hz output device`,async()=>{
 const f=fixture({deviceRate}),player=new CallPlayer(f.options);
 const raw=new Uint8Array([0,128,255,127,0,0,0,64]);player.push(raw);assert.equal(f.starts.length,0);
 const drained=player.checkpoint();assert.equal(f.starts.length,1);
 assert.deepEqual([...f.starts[0].samples],[-1,32767/32768,0,.5]);
 assert.equal(f.starts[0].duration,4/24000);f.advanceTo(100);await drained;
});
test('Each answer rearms its jitter cushion; a completed short tail bypasses prefill',async()=>{
 const f=fixture(),player=new CallPlayer(f.options);
 player.push(pcm(100));const first=player.checkpoint();f.advanceTo(100);await first;assert.equal(f.starts.length,1);
 player.push(pcm());assert.equal(f.starts.length,1);player.push(pcm());player.push(pcm());assert.equal(f.starts.length,1);
 player.push(pcm());assert.equal(f.starts.length,5);
 const drained=player.checkpoint();f.advanceTo(2000);await drained;
});
test('An actual underrun refills without replaying old samples',async()=>{
 const f=fixture(),player=new CallPlayer(f.options);player.push(pcm(4800,10));const first=player.checkpoint();f.advanceTo(400);await first;
 player.push(pcm(4800,20));assert.equal(f.starts.length,1);
 const second=player.checkpoint();f.advanceTo(800);await second;
 assert.equal(f.starts.length,2);assert.equal(f.starts[0].samples[0],10/32768);assert.equal(f.starts[1].samples[0],20/32768);
});
test('A stalled partial delivery starts once after the bounded prefill wait',()=>{
 const f=fixture(),player=new CallPlayer(f.options);player.push(pcm(240));f.advanceTo(1249);assert.equal(f.starts.length,0);
 f.advanceTo(1250);assert.equal(f.starts.length,1);assert.equal(f.starts[0].at,1.27);player.cancel();assert.equal(f.timers.size,0);
});
test('End before prefill cancels the timer and a late callback cannot schedule audio',()=>{
 const f=fixture(),player=new CallPlayer(f.options);player.push(pcm(240));const late=[...f.timers.values()][0].fn;
 player.cancel();late();f.advanceTo(2000);assert.equal(f.starts.length,0);assert.equal(f.timers.size,0);
});
test('End during drain stops every node and rejects its checkpoint',async()=>{
 const f=fixture(),player=new CallPlayer(f.options);for(let i=0;i<4;i++)player.push(pcm());const drained=player.checkpoint();player.cancel();
 await assert.rejects(drained,{name:'AbortError'});assert.ok(f.nodes.every(x=>x.stopped));assert.equal(f.timers.size,0);
});
test('Call output remains bounded to60 seconds and invalid PCM cannot enter playback',()=>{
 const f=fixture(),player=new CallPlayer(f.options);assert.throws(()=>player.push(new Uint8Array(3)),/gemini_pcm_invalid/);player.cancel();
 for(let i=0;i<300;i++)player.push(pcm());assert.throws(()=>player.push(pcm()),/gemini_playback_backlog/);player.cancel();assert.equal(f.timers.size,0);
});
test('A frozen Android audio clock still fails within the existing bounded watchdog',async()=>{
 const f=fixture({frozen:true}),player=new CallPlayer(f.options);player.push(pcm());const drained=player.checkpoint(),rejected=assert.rejects(drained,e=>e.code==='audio_stalled');
 f.advanceTo(6000);await rejected;assert.deepEqual(f.errors,['audio_stalled']);player.cancel();
});
