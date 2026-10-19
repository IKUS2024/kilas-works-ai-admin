import test from 'node:test';
import assert from 'node:assert/strict';
import {prepareProgressive,disposeProgressive} from '../static/kilas_live_translator_progressive.mjs';
import {TranslatorPlayback} from '../static/kilas_live_translator_playback.mjs';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
import {RealtimeCapture} from '../static/kilas_live_translator_realtime_capture.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};};
async function media(run){
 const names=['Audio','AudioContext','MediaSource'],old=new Map(names.map(n=>[n,Object.getOwnPropertyDescriptor(globalThis,n)])),calls=[];
 class Element {constructor(){this.muted=false;this.plays=0;}play(){this.plays++;calls.push(['play',this]);return Promise.resolve();}pause(){calls.push(['pause',this]);}removeAttribute(){}load(){}}
 class Context {createMediaElementSource(){return {connect(){},disconnect(){}};}}
 Object.assign(globalThis,{Audio:Element,AudioContext:Context,MediaSource:class{static isTypeSupported(){return true;}}});
 const context=new Context(),player={getContext:()=>context},controller=new AbortController();
 try{await run({Element,context,player,controller,calls});}finally{disposeProgressive(player);for(const [n,d] of old){if(d)Object.defineProperty(globalThis,n,d);else delete globalThis[n];}}
}
test('gesture authorization is synchronous, nonmuted, confirmed, same element reused, context replacement disposes it',()=>media(async f=>{
 const pending=prepareProgressive(f.player,f.controller.signal,()=>true);assert.equal(f.calls[0][0],'play');const slot=f.player.progressiveMedia;assert.equal(slot.ready,false);assert.equal(slot.audio.muted,false);assert.match(slot.audio.src,/^data:audio\/wav/);assert.equal(await pending,true);
 for(let i=0;i<3;i++)assert.equal(await prepareProgressive(f.player,f.controller.signal,()=>true),true);
 assert.equal(slot.audio.plays,1);assert.equal(f.player.progressiveMedia,slot);
 const next=new AudioContext();f.player.getContext=()=>next;assert.equal(await prepareProgressive(f.player,f.controller.signal,()=>true),true);assert.notEqual(f.player.progressiveMedia,slot);assert.equal(slot.ready,false);
}));
test('denied priming cannot claim authorization and can be retried by next gesture',()=>media(async f=>{
 f.Element.prototype.play=()=>Promise.reject(new DOMException('blocked','NotAllowedError'));
 assert.equal(await prepareProgressive(f.player,f.controller.signal,()=>true),false);assert.equal(f.player.progressiveMedia.ready,false);
 f.Element.prototype.play=()=>Promise.resolve();assert.equal(await prepareProgressive(f.player,f.controller.signal,()=>true),true);
}));
test('cancelled or stale priming cannot authorize a later session',()=>media(async f=>{
 const pending=deferred();f.Element.prototype.play=()=>pending.promise;
 const work=prepareProgressive(f.player,f.controller.signal,()=>true);f.controller.abort();assert.equal(await work,false);pending.resolve();await tick();assert.equal(f.player.progressiveMedia.ready,false);
}));
test('cached replay resumes context synchronously before async decode; no download',async()=>{
 const events=[],context={state:'suspended',currentTime:0,destination:{},resume(){events.push('resume');this.state='running';return Promise.resolve();},async decodeAudioData(){events.push('decode');return {duration:1};},createBufferSource(){return {connect(){},disconnect(){},stop(){},start(){context.currentTime=1;queueMicrotask(()=>this.onended());}};}};
 const player=new TranslatorPlayback({getContext:()=>context,fetchAudio(){throw Error('cached only');}}),url='/kilas-translator/live/sessions/'+'a'.repeat(48)+'/turns/live-'+'b'.repeat(32)+'/audio';player.remember(url,new ArrayBuffer(8));
 const work=player.play(url,new AbortController().signal,()=>true);assert.deepEqual(events,['resume']);await work;assert.deepEqual(events,['resume','decode']);
});
test('Hold calls microphone and interrupted context in same gesture; cancellation stops early and late tracks',async()=>{
 const resume=deferred(),permission=deferred(),calls=[],track={stops:0,stop(){this.stops++;},addEventListener(){}};
 const context={state:'suspended',audioWorklet:{addModule(){}},resume(){calls.push('resume');return resume.promise;}};
 const capture=new RealtimeCapture({getContext:()=>context,mediaDevices:{getUserMedia(){calls.push('microphone');return permission.promise;}}});
 const work=capture.start({level(){},pcm(){},blob(){},error(){}});const rejected=assert.rejects(work,{name:'AbortError'});assert.deepEqual(calls,['microphone','resume']);capture.cancel();permission.resolve({getTracks:()=>[track]});resume.resolve();await rejected;await tick();assert.equal(track.stops,1);
});
test('denied completed audio pauses with text retained, explicit Resume reuses stored audio and no resubmission',async()=>{
 let handlers,turns=0,plays=0,mics=0;const results=[],states=[],errors=[];
 const capture={async start(h){handlers=h;mics++;h.ready();},finalize(){mics=0;handlers.blob(new Blob(['speech']));},cancel(){mics=0;}};
 const playback={prepare:async()=>{},recover:async()=>{},cancel(){},stop(){},play:async()=>{assert.equal(mics,0);plays++;}};
 const session=new TranslatorSession({pushToTalk:true,capture,playback,onResult:v=>results.push(v),onState:v=>states.push(v),onError:(m,e)=>errors.push(e),api:{start:async()=>({session_id:'a'.repeat(48)}),resume:async()=>{},end:async()=>{},turn:async()=>{turns++;return {status:'COMPLETED',streamed:true,audio_url:'stored',translated_text:'Retained translation',playbackError:Object.assign(Error('Press Resume'),{code:'audio_permission',recoverable:false})};}}});
 await session.start({});await session.press();handlers.level(.2);session.release();await tick();assert.equal(session.state,'paused');assert.equal(session.pendingKey,null);assert.equal(session.outputPending,false);assert.equal(results.length,1);assert.equal(errors[0].code,'audio_permission');await session.foreground();assert.equal(session.state,'paused');await session.resume();assert.equal(session.state,'ready');assert.equal(plays,1);assert.equal(turns,1);assert.equal(mics,0);session.end();assert.equal(session.pendingPlayback,null);
});

import {VoiceRecorder} from '../static/kilas_transcription_recorder.mjs';
test('Safari batch capture selects supported MP4 and stops tracks before delivering bytes',async()=>{
 let stopped=0,options,blob;const stream={getTracks:()=>[{stop(){stopped++;},addEventListener(){}}]};
 class Recorder{static isTypeSupported(type){return type==='audio/mp4';}constructor(s,o){assert.equal(s,stream);options=o;this.mimeType=o.mimeType;this.events={};}addEventListener(k,fn){this.events[k]=fn;}start(){this.state='recording';}stop(){this.state='inactive';this.events.dataavailable({data:new Blob(['bytes'])});this.events.stop();}}
 const recorder=new VoiceRecorder({mediaDevices:{getUserMedia:async()=>stream},Recorder,onBlob:v=>{assert.equal(stopped,1);blob=v;},onState(){}});
 await recorder.start({userGesture:true,consent:true,enabled:true});assert.deepEqual(options,{mimeType:'audio/mp4'});recorder.stop();assert.equal(blob.type,'audio/mp4');assert.equal(blob.size,5);
});
