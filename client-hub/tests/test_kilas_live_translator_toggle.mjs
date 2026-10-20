import test from 'node:test';
import assert from 'node:assert/strict';
import {bindRecordToggle,TranslatorMicrophone} from '../static/kilas_live_translator_toggle.mjs';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const stream=()=>{const track={stops:0,stop(){this.stops++;}};return {track,getTracks:()=>[track]};};
class Events{
 constructor(){this.handlers=new Map();this.disabled=false;}
 addEventListener(name,fn){const list=this.handlers.get(name)||[];list.push(fn);this.handlers.set(name,list);}
 removeEventListener(name,fn){this.handlers.set(name,(this.handlers.get(name)||[]).filter(value=>value!==fn));}
 send(name,event={}){event.preventDefault??=()=>{};for(const fn of this.handlers.get(name)||[])fn(event);}
}
function controls(){
 let now=0,presses=0,releases=[],session={state:'ready',press(){presses++;this.state='listening';},release(options){releases.push(options);this.state='ready';}};
 const button=new Events(),window=new Events(),document=new Events(),toggle=bindRecordToggle({button,session,window,document,now:()=>now});
 return {button,window,document,toggle,session,releases,get presses(){return presses;},advance(ms=400){now+=ms;}};
}
test('one native click starts, pointer release keeps recording, next click stops exactly once',()=>{
 const f=controls();f.button.send('click',{detail:1});assert.equal(f.presses,1);assert.equal(f.releases.length,0);
 f.window.send('pointerup');f.window.send('keyup',{key:' '});assert.equal(f.releases.length,0);
 f.advance();f.button.send('click',{detail:1});assert.deepEqual(f.releases,[undefined]);f.toggle.destroy();
});
test('double click, rapid taps, repeated keys and busy states cannot start or stop duplicate turns',()=>{
 const f=controls();f.button.send('click',{detail:1});f.button.send('click',{detail:2});f.advance(100);f.button.send('click',{detail:1});assert.equal(f.releases.length,0);
 let prevented=0;f.button.send('keydown',{key:'Enter',repeat:true,preventDefault(){prevented++;}});assert.equal(prevented,1);
 f.advance();f.button.send('click',{detail:1});assert.equal(f.releases.length,1);
 for(const state of ['processing','finalizing','playing','replaying','paused','ended']){f.advance();f.session.state=state;f.button.send('click',{detail:0});}
 assert.equal(f.presses,1);assert.equal(f.releases.length,1);f.toggle.destroy();
});
test('permission opening can be stopped; hidden/blur/pagehide cancel once and destroy unbinds',()=>{
 for(const event of ['click','blur','pagehide','visibilitychange']){
  const f=controls();f.session.state='opening';f.advance();
  if(event==='visibilitychange'){f.document.hidden=true;f.document.send(event);}else(event==='click'?f.button:f.window).send(event,{detail:1});
  assert.equal(f.releases.length,1);assert.deepEqual(f.releases[0],event==='click'?undefined:{cancel:true});f.toggle.destroy();f.button.send('click');assert.equal(f.presses,0);
 }
});
test('initial Start arms debounce without suppressing the next intentional Stop',()=>{
 const f=controls();f.toggle.arm();f.session.state='listening';f.button.send('click',{detail:1});assert.equal(f.releases.length,0);f.advance();f.button.send('click',{detail:1});assert.equal(f.releases.length,1);f.toggle.destroy();
});
test('microphone permission is requested synchronously in Start and consumed once after admission',async()=>{
 let calls=0;const first=stream(),second=stream(),microphone=new TranslatorMicrophone({getUserMedia(){calls++;return Promise.resolve(calls===1?first:second);}});
 const prime=microphone.prime();assert.equal(calls,1);await prime;assert.equal(first.track.stops,0);
 assert.equal(await microphone.getUserMedia({audio:true}),first);assert.equal(calls,1);microphone.cancel();assert.equal(first.track.stops,0);
 assert.equal(await microphone.getUserMedia({audio:true}),second);assert.equal(calls,2);first.track.stop();second.track.stop();
});
test('End/admission failure stops already granted and late permission streams without capture',async()=>{
 for(const late of [false,true]){
  const permission=deferred(),value=stream(),microphone=new TranslatorMicrophone({getUserMedia:()=>permission.promise});
  const prime=microphone.prime();if(!late){permission.resolve(value);await prime;}microphone.cancel();if(late){const failed=assert.rejects(prime,{name:'AbortError'});permission.resolve(value);await failed;}
  await tick();assert.equal(value.track.stops,1);
 }
});
test('denial keeps its browser cause, timeout stops unconsumed audio, and stale streams never reach new Start',async()=>{
 const denied=new DOMException('Synthetic denied','NotAllowedError'),microphone=new TranslatorMicrophone({getUserMedia:()=>Promise.reject(denied)});
 await assert.rejects(microphone.prime(),error=>error===denied);await assert.rejects(microphone.getUserMedia({audio:true}),error=>error===denied);
 let timer;const value=stream(),held=new TranslatorMicrophone({getUserMedia:()=>Promise.resolve(value)},{schedule:fn=>{timer=fn;return 1;},clear(){}});await held.prime();timer();assert.equal(value.track.stops,1);await assert.rejects(held.getUserMedia({audio:true}),e=>e.code==='microphone_permission_timeout');
 const old=deferred(),fresh=stream();let n=0;const newer=new TranslatorMicrophone({getUserMedia:()=>++n===1?old.promise:Promise.resolve(fresh)});
 const first=newer.prime(),failed=assert.rejects(first,{name:'AbortError'});await newer.prime();old.resolve(value);await failed;await tick();assert.equal(await newer.getUserMedia({audio:true}),fresh);assert.equal(fresh.track.stops,0);fresh.track.stop();
});
function engine(){
 let handlers,mics=0,turns=0,finalized=0,starts=0,ends=0;const output=[];
 const capture={async start(value){handlers=value;mics++;starts++;value.ready();},finalize(){finalized++;mics=0;handlers.blob(new Blob(['synthetic speech']));},cancel(){mics=0;}};
 const api={async start(){return {session_id:'a'.repeat(48)};},async turn(){turns++;return {status:'COMPLETED',audio_url:'stored-'+turns,source_language:turns%2?'id':'en',target_language:turns%2?'en':'id',translated_text:'Synthetic translation'};},async resume(){},async end(){ends++;}};
 const session=new TranslatorSession({api,capture,recordOnStart:true,pushToTalk:true,key:()=>String(turns).padStart(32,'a'),onResult:value=>output.push(value),playback:{async prepare(){},async play(){assert.equal(mics,0);},stop(){},cancel(){}}});
 return {session,api,capture,output,get handlers(){return handlers;},get mics(){return mics;},get turns(){return turns;},get finalized(){return finalized;},get starts(){return starts;},get ends(){return ends;}};
}
test('initial Start records once; Stop directly processes four alternating turns without a process button',async()=>{
 const f=engine();const start=f.session.start({});await f.session.start({});await start;assert.equal(f.starts,1);assert.equal(f.session.state,'listening');
 for(let n=0;n<4;n++){
  if(n)await f.session.press();f.handlers.level(.2);f.session.release();f.session.release();await tick();
  assert.equal(f.turns,n+1);assert.equal(f.finalized,n+1);assert.equal(f.mics,0);assert.equal(f.session.state,'ready');assert.equal(f.output[n].source_language,n%2?'en':'id');
 }
 f.session.end();assert.equal(f.mics,0);
});
test('Stop while initial microphone permission is pending records no speech or provider turn',async()=>{
 const f=engine(),permission=deferred();f.capture.start=()=>permission.promise;f.capture.cancel=()=>permission.reject(new DOMException('Stopped before permission','AbortError'));const start=f.session.start({});await tick();assert.equal(f.session.state,'opening');f.session.release();permission.resolve();await start;assert.equal(f.session.state,'ready');assert.equal(f.turns,0);f.session.end();
});
test('End during initial admission closes the late admitted session and never starts capture',async()=>{
 const f=engine(),admission=deferred();f.api.start=()=>admission.promise;const start=f.session.start({});await tick();f.session.end();admission.resolve({session_id:'a'.repeat(48)});await start;await tick();assert.equal(f.starts,0);assert.equal(f.turns,0);assert.equal(f.ends,1);assert.equal(f.session.state,'ended');
});
