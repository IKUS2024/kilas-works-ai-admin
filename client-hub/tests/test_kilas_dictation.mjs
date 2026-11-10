import test from 'node:test';
import assert from 'node:assert/strict';
import {appendDictation} from '../static/kilas_dictation.mjs';
test('dictation preserves existing editable text including changes made during processing',()=>{
  assert.equal(appendDictation('Naskah yang sudah diedit','Hasil dikte'),'Naskah yang sudah diedit\nHasil dikte');
  assert.equal(appendDictation('','Hasil dikte'),'Hasil dikte');
  assert.equal(appendDictation('A\n','B'),'A\nB');
});
test('no speech and length failure never return truncated/replacement text',()=>{
  assert.throws(()=>appendDictation('Original',' '));
  assert.throws(()=>appendDictation('Original','Long result',10));
});

import fs from 'node:fs';
import vm from 'node:vm';
import {VoiceRecorder} from '../static/kilas_transcription_recorder.mjs';
import {finalDictation} from '../static/kilas_dictation.mjs';
const source=fs.readFileSync(new URL('../static/kilas_dictation.mjs',import.meta.url),'utf8').replace(/^import .*;$/gm,'').replace(/export function /g,'function ');
const final=text=>Object.assign([{transcript:text}],{isFinal:true});
const interim=text=>Object.assign([{transcript:text}],{isFinal:false});
function harness({available=true,webkit=false,server=false,constructorFailure=false,startFailure=false,android=false}={}){
  const nodes=new Map(),events=new Map(),timers=new Map(),stats={starts:0,stops:0,aborts:0,confirms:0,accepted:true,requests:[],input:0,mics:0,instances:[]};let timerID=0;
  function node(id){if(!nodes.has(id))nodes.set(id,{hidden:false,disabled:false,textContent:'',value:'',maxLength:4000,dataset:{},listeners:{},addEventListener(type,handler){this.listeners[type]=handler;},dispatchEvent(){stats.input++;},querySelector:selector=>selector==='[name=csrf_token]'?{value:'synthetic-csrf'}:selector==='[aria-busy=true]'?null:node(selector)});return nodes.get(id);}
  node('#voice-dictation').dataset.ready=String(server);node('#personal-voice-setup').dataset.recorderOpen='false';
  class Recognition{
    constructor(){if(constructorFailure)throw Error('unsupported');stats.instances.push(this);}
    start(){if(startFailure)throw Error('unavailable');stats.starts++;this.onstart?.();}
    stop(){stats.stops++;this.onend?.();}
    abort(){stats.aborts++;this.onend?.();}
  }
  const document={querySelector:node,documentElement:{lang:'id'},hidden:false,addEventListener:(name,handler)=>events.set(name,handler)};
  const window={addEventListener:(name,handler)=>events.set(name,handler),confirm:()=>{stats.confirms++;return stats.accepted;}};
  if(available)window[webkit?'webkitSpeechRecognition':'SpeechRecognition']=Recognition;
  const context={document,window,navigator:{language:'en-US',userAgent:android?'Mozilla/5.0 (Linux; Android 15) Chrome/130.0.0.0 Mobile Safari/537.36':'Mozilla/5.0 Chrome/130.0.0.0',mediaDevices:{getUserMedia:()=>{stats.mics++;throw Error('No microphone IO');}}},VoiceRecorder,t:text=>text,Event:class{},AbortController,FormData,crypto:globalThis.crypto,fetch:async(...args)=>{stats.requests.push(args);throw Error('No network IO');},setTimeout:(handler,delay)=>{timers.set(++timerID,{handler,delay});return timerID;},clearTimeout:id=>timers.delete(id)};
  vm.runInNewContext(source,context);
  return {node,stats,window,document,events,timers,click:async id=>node(id).listeners.click(),emit:results=>stats.instances.at(-1).onresult({results}),end:()=>stats.instances.at(-1).onend(),fail:error=>stats.instances.at(-1).onerror({error}),runTimer:delay=>[...timers.values()].find(timer=>timer.delay===delay)?.handler()};
}

test('browser fallback requires explicit consent, never calls Kilas STT, and does not start on load',async()=>{
  const h=harness();assert.equal(h.node('#voice-dictation').dataset.engine,'browser');assert.equal(h.node('#dictation-start').disabled,false);assert.equal(h.stats.starts,0);
  h.stats.accepted=false;await h.click('#dictation-start');assert.equal(h.stats.starts,0);assert.equal(h.node('#audio-studio').dataset.dictationBusy,'false');
  h.stats.accepted=true;await h.click('#dictation-start');await h.click('#dictation-start');assert.equal(h.stats.starts,1);assert.equal(h.stats.confirms,2);assert.equal(h.stats.instances[0].lang,'id-ID');assert.equal(h.stats.mics,0);assert.deepEqual(h.stats.requests,[]);
  await h.click('#dictation-cancel');assert.equal(h.stats.aborts,1);assert.equal(h.timers.size,0);
});
test('browser final results are applied once after stop, preserve latest typing, and undo safely',async()=>{
  const h=harness({webkit:true});h.node('#audio-script').value='Awal';await h.click('#dictation-start');
  h.emit([final('Kalimat pertama.'),interim('belum final')]);h.emit([final('Kalimat pertama.'),final('Kalimat kedua.')]);
  assert.equal(h.node('#audio-script').value,'Awal');h.node('#audio-script').value='Edit terbaru.';await h.click('#dictation-stop');h.end();
  assert.equal(h.node('#audio-script').value,'Edit terbaru.\nKalimat pertama. Kalimat kedua.');assert.equal(h.stats.input,1);assert.equal(h.node('#dictation-start').disabled,false);assert.equal(h.timers.size,0);
  await h.click('#dictation-undo');assert.equal(h.node('#audio-script').value,'Edit terbaru.');assert.equal(h.stats.input,2);assert.deepEqual(h.stats.requests,[]);
});
test('cancel, pagehide and backgrounding fence late recognition events',async()=>{
  for(const event of ['cancel','pagehide','visibilitychange']){
    const h=harness();h.node('#audio-script').value='Naskah aman';await h.click('#dictation-start');const old=h.stats.instances[0];h.emit([final('Buang ini')]);
    if(event==='cancel')await h.click('#dictation-cancel');else{if(event==='visibilitychange')h.document.hidden=true;h.events.get(event)();}
    old.onresult({results:[final('Terlambat')]});old.onend();assert.equal(h.node('#audio-script').value,'Naskah aman');assert.equal(h.stats.input,0);assert.equal(h.node('#dictation-start').disabled,false);assert.equal(h.stats.aborts,1);assert.equal(h.timers.size,0);assert.deepEqual(h.stats.requests,[]);
  }
});
test('old result cannot change a later session, and natural end does not auto-restart',async()=>{
  const h=harness();await h.click('#dictation-start');const old=h.stats.instances[0];await h.click('#dictation-cancel');await h.click('#dictation-start');old.onresult({results:[final('Lama')]});old.onend();
  h.emit([final('Baru')]);h.end();assert.equal(h.node('#audio-script').value,'Baru');assert.equal(h.stats.starts,2);assert.equal(h.node('#audio-studio').dataset.dictationBusy,'false');
});
test('permission denial, network error, empty speech and unsupported browser keep text and explain',async()=>{
  for(const error of ['not-allowed','service-not-allowed','network','no-speech','audio-capture']){
    const h=harness();h.node('#audio-script').value='Utuh';await h.click('#dictation-start');h.emit([final('Tidak diterapkan')]);h.fail(error);h.end();assert.equal(h.node('#audio-script').value,'Utuh');assert.equal(h.node('#dictation-error').hidden,false);assert.equal(h.node('#dictation-start').disabled,false);assert.equal(h.node('#dictation-status').textContent,'');assert.equal(h.timers.size,0);
  }
  const h=harness({available:false});assert.equal(h.node('#dictation-start').disabled,true);assert.match(h.node('#dictation-status').textContent,/belum didukung/);assert.equal(h.stats.starts,0);
  const empty=harness();await empty.click('#dictation-start');empty.emit([interim('Bukan hasil final')]);empty.end();assert.match(empty.node('#dictation-error').textContent,/Tidak ada ucapan/);assert.equal(empty.node('#audio-script').value,'');
});
test('length overflow and edited undo never lose the user draft',async()=>{
  const h=harness();h.node('#audio-script').value='x'.repeat(3999);await h.click('#dictation-start');h.emit([final('terlalu panjang')]);h.end();assert.equal(h.node('#audio-script').value,'x'.repeat(3999));assert.match(h.node('#dictation-error').textContent,/4.000/);
  h.node('#audio-script').value='Awal';await h.click('#dictation-start');h.emit([final('Baru')]);h.end();h.node('#audio-script').value='Edit lagi';await h.click('#dictation-undo');assert.equal(h.node('#audio-script').value,'Edit lagi');assert.match(h.node('#dictation-error').textContent,/sudah diedit/);
});
test('three minute limit, missing stop event and failed construction cannot leave the UI stuck',async()=>{
  const h=harness();await h.click('#dictation-start');h.emit([final('Selesai')]);h.runTimer(179000);assert.equal(h.stats.stops,1);assert.equal(h.node('#audio-script').value,'Selesai');assert.equal(h.timers.size,0);
  const late=harness();await late.click('#dictation-start');late.emit([final('Sudah final')]);late.stats.instances[0].stop=()=>{late.stats.stops++;};await late.click('#dictation-stop');assert.equal(late.node('#dictation-stop').disabled,true);late.runTimer(8000);assert.equal(late.node('#audio-script').value,'Sudah final');assert.equal(late.stats.aborts,1);assert.equal(late.timers.size,0);
  for(const failure of [{constructorFailure:true},{startFailure:true}]){const broken=harness(failure);await broken.click('#dictation-start');assert.equal(broken.node('#dictation-start').disabled,false);assert.equal(broken.node('#dictation-error').hidden,false);assert.equal(broken.timers.size,0);}
});
test('existing funded server mode is retained, and open Add Voice prevents dictation',async()=>{
  const funded=harness({server:true});assert.equal(funded.node('#voice-dictation').dataset.engine,'server');assert.equal(funded.stats.confirms,0);
  const h=harness();h.node('#personal-voice-setup').dataset.recorderOpen='true';await h.click('#dictation-start');assert.equal(h.stats.starts,0);assert.equal(h.stats.confirms,0);
  assert.equal(finalDictation([final('A'),interim('discard'),final('B')]),'A B');
});


test('Android cumulative final hypotheses replace prefixes without rewriting words',async()=>{
  const h=harness({android:true,webkit:true});h.node('#audio-script').value='Existing draft';
  await h.click('#dictation-start');
  const phrases=['hello','hello','hello','hello','hello','hello how can','hello how can you','hello how can you','hello how can you predica America'];
  for(let i=1;i<=phrases.length;i++)h.emit(phrases.slice(0,i).map(final));
  assert.equal(h.node('#audio-script').value,'Existing draft');
  h.node('#audio-script').value='Latest draft';
  h.stats.instances[0].stop=()=>{h.stats.stops++;};
  await h.click('#dictation-stop');await h.click('#dictation-stop');h.end();h.end();
  assert.equal(h.stats.stops,1);assert.equal(h.stats.input,1);
  assert.equal(h.node('#audio-script').value,'Latest draft\nhello how can you predica America');
  await h.click('#dictation-undo');assert.equal(h.node('#audio-script').value,'Latest draft');
});
test('Android revised result snapshots replace old text and exclude interim hypotheses',async()=>{
  const h=harness({android:true});await h.click('#dictation-start');
  h.emit([final('hello'),final('hello how can'),interim('unfinished')]);
  h.emit([final('hello'),final('hello how can you help')]);
  h.emit([final('hello'),final('hello how'),final('hello how can you')]);
  h.end();assert.equal(h.node('#audio-script').value,'hello how can you');
});
test('cumulative reconciliation preserves intentional repeats within a hypothesis and independent phrases',()=>{
  const options={cumulative:true};
  assert.equal(finalDictation([final('hello'),final('hello hello'),final('hello hello hello')],options),'hello hello hello');
  assert.equal(finalDictation([final('go'),final('go go'),final('go go go'),final('again again')],options),'go go go again again');
  assert.equal(finalDictation([final('hello'),final('hello')],options),'hello hello');
  assert.equal(finalDictation([final('hello'),final('hello how')],options),'hello hello how');
  assert.equal(finalDictation([final('can'),final('candy')],options),'can candy');
  assert.equal(finalDictation([final('one two'),final('two three')],options),'one two two three');
  assert.equal(finalDictation([final('hello'),final('hello'),final('hello how are you')]),'hello hello hello how are you');
});
test('cancelled Android cumulative hypotheses never leak into a new recording',async()=>{
  const h=harness({android:true});h.node('#audio-script').value='Safe';await h.click('#dictation-start');
  const old=h.stats.instances[0];h.emit([final('hello'),final('hello how can')]);await h.click('#dictation-cancel');
  await h.click('#dictation-start');old.onresult({results:[final('hello how can you')]});old.onend();
  h.emit([final('bye bye')]);h.end();assert.equal(h.node('#audio-script').value,'Safe\nbye bye');assert.equal(h.stats.input,1);
});
