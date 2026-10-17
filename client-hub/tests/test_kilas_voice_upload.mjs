// Node VM + synthetic DOM/media/network doubles. No browser or paid provider.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../static/kilas_personal_voice.js',import.meta.url),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const response=(body={duration_ms:1600},ok=true)=>({ok,redirected:false,json:async()=>body});
function fixture({saved=false}={}){
 const stats={requests:[],mics:0,revoked:[],urls:0,keys:0,now:0,recorders:[],mic:null,handler:null};
 const timers=new Map(),intervals=new Map(),events=new Map();let seq=0;
 function node(){return {hidden:false,disabled:false,value:'',textContent:'',checked:false,dataset:{},handlers:new Map(),addEventListener(type,fn){this.handlers.set(type,fn);},fire(type,event={}){return this.handlers.get(type)?.(event);},pause(){this.paused=true;},async play(){this.paused=false;},removeAttribute(key){delete this[key];},focus(){},querySelectorAll(){return [];}};}
 const ids=['personal-voice-setup','voice-recorder','record-start','record-stop','record-again','record-cancel','record-playback','voice-consent','save-personal-voice','record-state','record-timer','record-error','selected-voice','kilas-voice-choice','voice-generate','saved-voice-choice','record-voice-name','voice-sample-file','voice-sample-selection','kilas-voice-options','personal-ready','add-saved-voice','personal-voice-state','audio-script','voice-language','voice-language-status','rename-saved-voice','delete-saved-voice','saved-voice-notice','saved-voice-rename','saved-voice-new-name','saved-voice-error','cancel-voice-name','save-voice-name'];
 ids.push('personal-preview','play-personal-preview','voice-preview-error');
 const nodes=Object.fromEntries(ids.map(id=>['#'+id,node()]));const n=id=>nodes['#'+id];
 const radioPersonal=Object.assign(node(),{value:'personal',checked:true}),radioKilas=Object.assign(node(),{value:'kilas'});
 const library=n('saved-voice-choice');library.options=saved?[{value:'7',textContent:'Saved',dataset:{preview:'true'}}]:[{value:'',textContent:'None',dataset:{}}];library.value=saved?'7':'';
 Object.defineProperty(library,'selectedOptions',{get(){return [library.options.find(o=>o.value===library.value)||library.options[0]];}});
 library.add=option=>library.options.push(option);library.querySelector=()=>({remove(){library.options=library.options.filter(o=>o.value!=='');}});
 n('personal-voice-setup').dataset.operationKey='initial-operation-key';n('voice-generate').dataset.enabled='true';n('kilas-voice-choice').value='kilas-male';n('voice-language').value='auto';n('voice-recorder').hidden=true;
 n('audio-script').value='Synthetic words';n('voice-recorder').querySelectorAll=()=>['record-start','record-stop','record-again','record-cancel','voice-sample-file','voice-consent','record-voice-name','save-personal-voice'].map(n);
 n('personal-ready').querySelectorAll=()=>['add-saved-voice','rename-saved-voice','delete-saved-voice'].map(n);
 const document={querySelector:q=>q==='[name=voice_kind]:checked'?(radioPersonal.checked?radioPersonal:radioKilas):q==='#audio-studio [name=csrf_token]'?{value:'synthetic-csrf'}:nodes[q],querySelectorAll:()=>[radioPersonal,radioKilas],addEventListener(){}};
 class Recorder{
  static isTypeSupported(){return true;}state='inactive';mimeType='audio/webm';handlers=new Map();
  constructor(){stats.recorders.push(this);}addEventListener(type,fn){this.handlers.set(type,fn);}start(){this.state='recording';}
  stop(){this.state='inactive';if(!this.delayStop)this.finish();}
  finish(){this.handlers.get('dataavailable')({data:new Blob(['synthetic recorded data'])});this.handlers.get('stop')();}
 }
 class Form{values=new Map();names=new Map();append(k,v,name){this.values.set(k,v);if(name)this.names.set(k,name);}get(k){return this.values.get(k);}}
 const window={MediaRecorder:Recorder,addEventListener:(type,fn)=>events.set(type,fn)};
 const navigator={mediaDevices:{async getUserMedia(){if(stats.mic)return stats.mic.promise;stats.mics++;let stopped=false;return {getTracks:()=>[{stop(){if(!stopped){stopped=true;stats.mics--;}}}]};}}};
 const context={document,window,navigator,MediaRecorder:Recorder,Blob,AbortController,FormData:Form,crypto:{randomUUID:()=>`operation-key-${++stats.keys}`},confirm:()=>true,Option:class{constructor(text,value){this.textContent=text;this.value=value;this.dataset={};}},URL:{createObjectURL:()=>`blob:synthetic-${++stats.urls}`,revokeObjectURL:url=>stats.revoked.push(url)},Date:{now:()=>stats.now},setInterval:(fn,ms)=>{const k=++seq;intervals.set(k,{fn,ms});return k;},clearInterval:k=>intervals.delete(k),setTimeout:(fn,ms)=>{const k=++seq;timers.set(k,{fn,ms});return k;},clearTimeout:k=>timers.delete(k),fetch:async(url,options)=>{stats.requests.push({url,options});return stats.handler?stats.handler(url,options):response();}};
 vm.runInNewContext(source,context);
 const file=(name='voice.mp3',type='audio/mpeg',size=100)=>({name,type,size});
 return {n,stats,timers,intervals,events,radios:[radioPersonal,radioKilas],library,file,async choose(selected=file()){n('voice-sample-file').files=selected?[selected]:[];return n('voice-sample-file').fire('change');},consent(){n('voice-consent').checked=true;n('voice-consent').fire('change');},open(){n('add-saved-voice').fire('click');},async cancel(){n('record-cancel').fire('click');await flush();}};
}

test('validated upload previews locally, requires consent and saves through existing named clone endpoint',async()=>{
 const f=fixture();f.open();assert.equal(f.n('voice-recorder').hidden,false);assert.equal(f.stats.mics,0);
 await f.choose();assert.equal(f.n('record-playback').src,'blob:synthetic-1');assert.equal(f.n('record-playback').hidden,false);assert.equal(f.n('save-personal-voice').disabled,true);assert.equal(f.timers.size,0);
 f.consent();assert.equal(f.n('save-personal-voice').disabled,false);
 f.stats.handler=async()=>response({id:9,name:'Synthetic voice'});f.n('record-voice-name').value='Synthetic voice';await f.n('save-personal-voice').fire('click');
 const saved=f.stats.requests[1];assert.equal(saved.url,'/kilas-translator/personal-voice');assert.equal(saved.options.body.names.get('recording'),'voice.mp3');assert.equal(saved.options.body.get('consent'),'yes');assert.equal(f.stats.mics,0);assert.equal(f.library.value,'9');assert.equal(f.n('voice-recorder').hidden,true);assert.deepEqual(f.stats.revoked,['blob:synthetic-1']);
});

test('invalid MIME, empty or oversized source clears earlier preview without posting it',async()=>{
 const f=fixture();f.open();await f.choose();f.consent();
 for(const file of [f.file('bad.html','text/html'),f.file('empty.mp3','audio/mpeg',0),f.file('large.wav','audio/wav',10*1024*1024+1)]){
  await f.choose(file);assert.equal(f.n('record-playback').hidden,true);assert.equal(f.n('save-personal-voice').disabled,true);assert.equal(f.n('voice-consent').checked,false);assert.equal(f.n('record-error').hidden,false);
 }
 assert.equal(f.stats.requests.length,1);assert.equal(f.stats.revoked.length,1);assert.equal(f.timers.size,0);
});

test('cancel picker retains sample; selecting new file replaces preview and resets consent and operation key',async()=>{
 const f=fixture();f.open();await f.choose();f.consent();const old=f.n('personal-voice-setup').dataset.operationKey;
 await f.choose(null);assert.equal(f.n('record-playback').src,'blob:synthetic-1');assert.equal(f.n('save-personal-voice').disabled,false);
 await f.choose(f.file('new.wav','audio/wav'));assert.equal(f.n('record-playback').src,'blob:synthetic-2');assert.equal(f.n('voice-consent').checked,false);assert.notEqual(f.n('personal-voice-setup').dataset.operationKey,old);assert.equal(f.stats.revoked.length,1);
 await f.cancel();assert.equal(f.n('voice-recorder').hidden,true);assert.equal(f.n('record-playback').hidden,true);assert.equal(f.stats.revoked.length,2);
});

test('late inspection response after cancellation cannot restore preview or allow saving',async()=>{
 const f=fixture();f.open();const pending=deferred();f.stats.handler=()=>pending.promise;const choosing=f.choose();await flush();const req=f.stats.requests[0];
 f.consent();assert.equal(f.n('save-personal-voice').disabled,true);await f.cancel();assert.equal(req.options.signal.aborted,true);assert.equal(f.timers.size,0);
 pending.resolve(response());await choosing;assert.equal(f.n('record-playback').hidden,true);assert.equal(f.n('save-personal-voice').disabled,true);assert.equal(f.stats.urls,0);
});

test('superseded response and its stale timeout cannot abort or overwrite a newer selection',async()=>{
 const f=fixture();f.open();const first=deferred(),second=deferred();let calls=0;f.stats.handler=()=>++calls===1?first.promise:second.promise;
 const a=f.choose(f.file('old.mp3'));await flush();const stale=[...f.timers.values()][0].fn;
 const b=f.choose(f.file('new.wav','audio/wav'));await flush();assert.equal(f.stats.requests[0].options.signal.aborted,true);stale();assert.equal(f.stats.requests[1].options.signal.aborted,false);
 second.resolve(response({duration_ms:2200}));await b;first.resolve(response({error:'Old failed'},false));await a;
 assert.equal(f.n('voice-sample-selection').textContent,'new.wav');assert.equal(f.n('record-timer').textContent,'0:03');assert.equal(f.n('record-error').hidden,true);assert.equal(f.timers.size,0);
});

test('inspection deadline aborts only its request and gives a retry path',async()=>{
 const f=fixture();f.open();f.stats.handler=(_,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('Aborted'))));
 const choosing=f.choose();await flush();const timer=[...f.timers.values()][0];assert.equal(timer.ms,30000);timer.fn();await choosing;
 assert.match(f.n('record-error').textContent,/terlalu lama/);assert.equal(f.n('save-personal-voice').disabled,true);assert.equal(f.timers.size,0);
 f.stats.handler=async()=>response();await f.choose();assert.equal(f.n('record-playback').hidden,false);
});

test('decoder rejection, malformed JSON and network failure leave controls available for reselection',async()=>{
 for(const handler of [async()=>response({error:'Isi file tidak valid'},false),async()=>{throw new TypeError('offline');},async()=>({ok:true,json:async()=>{throw new SyntaxError('json');}}),async()=>response({duration_ms:181000})]){
  const f=fixture();f.open();f.stats.handler=handler;await f.choose();assert.equal(f.n('record-error').hidden,false);assert.equal(f.n('save-personal-voice').disabled,true);assert.equal(f.n('voice-sample-file').disabled,false);assert.equal(f.n('record-start').disabled,false);assert.equal(f.timers.size,0);
 }
});

test('microphone permission rejected after upload selection cannot clear newer preview',async()=>{
 const f=fixture();f.open();f.stats.mic=deferred();const recording=f.n('record-start').fire('click');await flush();await f.choose();f.stats.mic.reject(new Error('denied'));await recording;
 assert.equal(f.n('record-playback').src,'blob:synthetic-1');assert.equal(f.n('record-error').hidden,true);assert.equal(f.n('record-state').textContent,'Audio siap didengarkan');
});

test('upload supersedes microphone and late stop/error cannot stop a subsequent recording',async()=>{
 const f=fixture();f.open();await f.n('record-start').fire('click');assert.equal(f.stats.mics,1);const old=f.stats.recorders[0];old.delayStop=true;
 await f.choose();assert.equal(f.stats.mics,0);assert.equal(f.intervals.size,0);await f.n('record-start').fire('click');assert.equal(f.stats.mics,1);
 old.finish();old.handlers.get('error')();assert.equal(f.stats.mics,1);assert.equal(f.n('record-playback').hidden,true);
 f.stats.now=2000;f.n('record-stop').fire('click');assert.equal(f.stats.mics,0);assert.equal(f.n('record-playback').hidden,false);f.consent();assert.equal(f.n('save-personal-voice').disabled,false);f.events.get('pagehide')();assert.equal(f.n('record-playback').hidden,true);assert.equal(f.intervals.size,0);
});

test('failed Add Voice preserves the selected saved voice and retries without replacing it',async()=>{
 const f=fixture({saved:true});f.open();await f.choose();f.consent();const key=f.n('personal-voice-setup').dataset.operationKey;
 f.stats.handler=async()=>response({error:'Try again'},false);await f.n('save-personal-voice').fire('click');assert.equal(f.n('record-playback').hidden,false);assert.equal(f.n('save-personal-voice').disabled,false);assert.equal(f.library.value,'7');
 await f.n('save-personal-voice').fire('click');const posts=f.stats.requests.slice(1);assert.equal(posts[0].options.body.get('operation_key'),key);assert.equal(posts[1].options.body.get('operation_key'),key);assert.equal(posts[0].options.body.get('saved_voice_id'),undefined);assert.equal(posts[1].options.body.get('saved_voice_id'),undefined);
});

test('changing voice kind while inspecting aborts upload and preserves voiceover form',async()=>{
 const f=fixture();f.open();const pending=deferred();f.stats.handler=()=>pending.promise;const uploading=f.choose();await flush();f.radios[0].checked=false;f.radios[1].checked=true;f.radios[1].fire('change');
 assert.equal(f.stats.requests[0].options.signal.aborted,true);assert.equal(f.n('personal-voice-setup').hidden,true);assert.equal(f.n('kilas-voice-options').hidden,false);pending.resolve(response());await uploading;assert.equal(f.stats.urls,0);assert.equal(f.timers.size,0);
});

test('saved sample uses selected owner preview and resets on voice change, recording, mode change and pagehide',async()=>{
 const f=fixture({saved:true});assert.equal(f.n('play-personal-preview').disabled,false);assert.equal(f.n('personal-preview').hidden,true);
 await f.n('play-personal-preview').fire('click');assert.equal(f.n('personal-preview').src,'/kilas-translator/personal-voices/7/preview');assert.equal(f.n('personal-preview').paused,false);assert.equal(f.stats.requests.length,0);
 f.library.options.push({value:'8',textContent:'Legacy',dataset:{preview:'false'}});f.library.value='8';f.library.fire('change');assert.equal(f.n('personal-preview').hidden,true);assert.equal(f.n('personal-preview').src,undefined);assert.equal(f.n('play-personal-preview').disabled,true);
 f.library.value='7';f.library.fire('change');await f.n('play-personal-preview').fire('click');f.open();assert.equal(f.n('personal-preview').paused,true);assert.equal(f.n('personal-preview').src,undefined);await f.cancel();
 await f.n('play-personal-preview').fire('click');f.radios[0].checked=false;f.radios[1].checked=true;f.radios[1].fire('change');assert.equal(f.n('personal-preview').paused,true);assert.equal(f.n('personal-preview').hidden,true);
 f.radios[0].checked=true;f.radios[1].checked=false;f.radios[0].fire('change');await f.n('play-personal-preview').fire('click');f.events.get('pagehide')();assert.equal(f.n('personal-preview').src,undefined);
});

test('saved sample playback rejection offers retry and stale rejection cannot affect another selection',async()=>{
 const f=fixture({saved:true});f.n('personal-preview').play=async()=>{throw new Error('decode failed');};await f.n('play-personal-preview').fire('click');assert.equal(f.n('voice-preview-error').hidden,false);
 const pending=deferred();f.n('personal-preview').play=()=>pending.promise;const play=f.n('play-personal-preview').fire('click');f.library.fire('change');pending.reject(new Error('aborted'));await play;assert.equal(f.n('voice-preview-error').hidden,true);
});
