import assert from 'node:assert/strict';
import test from 'node:test';
import {TranslatorSession} from '../static/kilas_live_translator_engine.mjs';
import {bindHoldToTalk} from '../static/kilas_live_translator_hold.mjs';
const tick=()=>new Promise(r=>setImmediate(r));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
function fixture(){
 let handlers,mics=0,calls=0,plays=0,cancels=0,time=0;const timers=new Map();let seq=0;
 const capture={async start(h){handlers=h;mics++;h.ready();},finalize(){mics=0;handlers.blob(new Blob(['synthetic']));},cancel(){mics=0;cancels++;}};
 const api={async start(){return {session_id:'a'.repeat(48)};},async turn(){calls++;return {status:'COMPLETED',audio_url:'stored',translated_text:'Synthetic'};},async resume(){},async end(){}};
 const playback={has:()=>true,async prepare(){},async play(){assert.equal(mics,0);plays++;},cancel(){},stop(){}};
 const session=new TranslatorSession({api,capture,playback,pushToTalk:true,now:()=>time,key:()=>String(calls).padStart(32,'a'),schedule:(fn,ms)=>{timers.set(++seq,{fn,ms});return seq;},clear:id=>timers.delete(id)});
 return {session,api,capture,playback,timers,get handlers(){return handlers;},get mics(){return mics;},get calls(){return calls;},get plays(){return plays;},get cancels(){return cancels;},voice(){handlers.level(.1);},silence(){time+=3000;handlers.level(0);}};
}
test('Start never opens microphone; held pauses never finalize; release submits once and remains ready for both directions',async()=>{
 const f=fixture();await f.session.start({});assert.equal(f.session.state,'ready');assert.equal(f.mics,0);
 for(let n=0;n<4;n++){await f.session.press();f.voice();f.silence();assert.equal(f.calls,n);f.session.release();f.session.release();await tick();assert.equal(f.calls,n+1);assert.equal(f.session.state,'ready');assert.equal(f.mics,0);}
 f.session.end();assert.equal(f.timers.size,0);
});
test('empty/short hold and release while permission is pending dispatch nothing; End cleans late permission',async()=>{
 const f=fixture();await f.session.start({});await f.session.press();f.session.release();assert.equal(f.calls,0);assert.equal(f.mics,0);
 const pending=deferred();f.capture.start=async()=>pending.promise;const pressing=f.session.press();f.session.release();pending.resolve();await pressing;assert.equal(f.session.state,'ready');assert.equal(f.calls,0);f.session.end();
});
test('cancel active hold reconciles existing paid input before any new press; replay cannot capture or call provider',async()=>{
 const f=fixture(),settled=deferred();f.api.resume=()=>settled.promise;await f.session.start({});await f.session.press();f.voice();f.session.pendingKey='live-existing';f.session.release({cancel:true});assert.equal(f.session.state,'recovering');await f.session.press();assert.equal(f.mics,0);settled.resolve();await tick();assert.equal(f.session.state,'ready');await f.session.replay('stored');assert.equal(f.plays,1);assert.equal(f.calls,0);assert.equal(f.mics,0);f.session.end();
});
test('long hold finalizes once, processing/playback cannot open another capture, Stop wins late output',async()=>{
 const f=fixture(),output=deferred();f.api.turn=()=>{return output.promise;};await f.session.start({});await f.session.press();f.voice();[...f.timers.values()].find(v=>v.ms===175000).fn();assert.equal(f.session.state,'processing');await f.session.press();assert.equal(f.mics,0);f.session.end();output.resolve({status:'COMPLETED',audio_url:'stored'});await tick();assert.equal(f.plays,0);assert.equal(f.session.state,'ended');
});
class Events{constructor(){this.handlers={};this.disabled=false;}addEventListener(t,fn){(this.handlers[t]??=[]).push(fn);}removeEventListener(){}send(t,e={}){e.preventDefault??=()=>{};for(const fn of this.handlers[t]||[])fn(e);}setPointerCapture(){}hasPointerCapture(){return true;}releasePointerCapture(){}}
test('pointer release outside/cancel/lostcapture, key repeat, blur/hidden each release at most once',()=>{
 const button=new Events(),window=new Events(),document=new Events();let presses=0,releases=[];const hold=bindHoldToTalk({button,window,document,session:{press(){presses++;},release(v){releases.push(v);}}});
 button.send('pointerdown',{pointerId:1,button:0});window.send('pointerup',{pointerId:1});button.send('lostpointercapture',{pointerId:1});assert.equal(releases.length,1);assert.equal(releases[0].cancel,false);
 for(const type of ['pointercancel','lostpointercapture','blur','visibilitychange']){button.send('pointerdown',{pointerId:2,button:0});if(type==='visibilitychange'){document.hidden=true;document.send(type);}else(type==='lostpointercapture'?button:window).send(type,{pointerId:2});}assert.equal(releases.length,5);assert.ok(releases.slice(1).every(v=>v.cancel));
 button.send('keydown',{key:' ',repeat:false});button.send('keydown',{key:' ',repeat:true});window.send('keyup',{key:' '});window.send('keyup',{key:' '});assert.equal(presses,6);assert.equal(releases.length,6);hold.destroy();
});
test('foreground reconnect polls the existing completed input with null blob; no second upload or cancellation',async()=>{
 const f=fixture(),old=deferred();let modes=[];f.api.turn=async(id,key,blob)=>{modes.push(blob);return modes.length===1?old.promise:{status:'COMPLETED',audio_url:'stored',translated_text:'Recovered'};};
 await f.session.start({});await f.session.press();f.voice();f.session.release();await tick();assert.equal(f.session.outputPending,true);f.session.suspend();assert.equal(f.session.state,'paused');await f.session.foreground();assert.equal(modes.length,2);assert.equal(modes[1],null);assert.equal(f.plays,1);assert.equal(f.mics,0);assert.equal(f.session.state,'ready');old.resolve({status:'COMPLETED',audio_url:'stale'});await tick();assert.equal(f.plays,1);f.session.end();
});
import {TranslatorHistory} from '../static/kilas_live_translator_history.mjs';
test('audio eviction retains all original/translated text and labels with an honest disabled replay',()=>{
 const original=globalThis.document;class Node{constructor(){this.children=[];this.attributes={};}setAttribute(k,v){this.attributes[k]=v;}addEventListener(){}append(...v){this.children.push(...v);}replaceChildren(){this.children=[];}}
 globalThis.document={createElement:()=>new Node()};
 try{const element=new Node(),history=new TranslatorHistory({element,languageName:code=>code==='id'?'Indonesian':'English',replay(){throw Error('must not regenerate');},available:()=>false});
 history.add({status:'COMPLETED',audio_url:'stored',source_text:'<script>literal speech</script>',translated_text:'Translated literal',source_language:'id',target_language:'en'},'id');history.remove('stored');history.busy(false);
 assert.equal(history.rows.size,1);assert.equal(element.children.length,1);const {row,button}=history.rows.get('stored');assert.equal(row.children[1].textContent,'<script>literal speech</script>');assert.equal(row.children[2].textContent,'Translated literal');assert.equal(button.disabled,true);assert.ok(button.title);history.clear();assert.equal(element.children.length,0);
 }finally{globalThis.document=original;}
});
