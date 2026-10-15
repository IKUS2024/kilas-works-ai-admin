// Browser-free UI text, recovery and bounded playback; no provider or microphone.
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {uiText} from '../static/ui_i18n.mjs';
import {TranslatorRecovery} from '../static/kilas_live_translator_recovery.mjs';
import {TranslatorPlayback} from '../static/kilas_live_translator_playback.mjs';

const catalog=JSON.parse(readFileSync(new URL('../locales/ui.json',import.meta.url),'utf8'));
const english=JSON.parse(readFileSync(new URL('../locales/ui_en.json',import.meta.url),'utf8'));
const source=readFileSync(new URL('../static/ui_i18n.js',import.meta.url),'utf8');
function install(t,language='en'){
 const messages=Object.fromEntries(Object.entries(catalog).map(([key,value])=>[key,value[language]??key]));
 if(language==='en')Object.assign(messages,english);
 const context={window:{},document:{getElementById:()=>({textContent:JSON.stringify(messages)})}};
 vm.runInNewContext(source,context);
 const previous=globalThis.KilasUI;globalThis.KilasUI=context.window.KilasUI;
 t.after(()=>{if(previous)globalThis.KilasUI=previous;else delete globalThis.KilasUI;});
 return context.window.KilasUI;
}

test('English applies only to explicit UI text, with exact placeholder values',t=>{
 const ui=install(t);
 assert.equal(ui.t('Pilih suara'),'Choose a voice');
 assert.equal(uiText('Halaman {value0} dari {value1}.',{value0:2,value1:7}),'Page 2 of 7.');
 assert.equal(uiText('File maksimal {value0} MB.',{value0:10}),'Files must be no larger than 10 MB.');
 const script='Pilih suara',sourceLanguage='id',targetLanguage='en',voice='kilas-male';
 assert.deepEqual({script,sourceLanguage,targetLanguage,voice},{script:'Pilih suara',sourceLanguage:'id',targetLanguage:'en',voice:'kilas-male'});
 assert.equal(ui.t('Arbitrary customer <script>data</script>'),'Arbitrary customer <script>data</script>');
});

test('an explicit Indonesian UI preference retains source copy and interpolation',t=>{
 install(t,'id');
 assert.equal(uiText('Pilih suara'),'Pilih suara');
 assert.equal(uiText('See all'),'Lihat semua');
 assert.equal(uiText('Wallet'),'Dompet');
 assert.equal(uiText('Halaman {value0} dari {value1}.',{value0:2,value1:7}),'Halaman 2 dari 7.');
});

test('English session recovery error keeps End responsive without ending another session',async t=>{
 install(t);const errors=[];let ends=0;
 const recovery=new TranslatorRecovery({api:{active:async()=>({session:{session_id:'owned-old'}}),end:async()=>{ends++;throw Error('offline');}},onError:message=>errors.push(message)});
 await recovery.refresh();await recovery.endPrevious();
 assert.equal(ends,1);assert.equal(recovery.pending,false);assert.equal(recovery.active.session_id,'owned-old');
 assert.equal(errors[0],'The session has not been confirmed as ended. Check the session or end it again when the network is available.');
});

test('English playback failure preserves the error code and never fetches replacement audio',async t=>{
 install(t);let calls=0;
 const player=new TranslatorPlayback({getContext:()=>null,fetchAudio:()=>{calls++;throw Error('unexpected fetch');}});
 await assert.rejects(player.prepare(new AbortController().signal,()=>true),error=>{
  assert.equal(error.code,'audio_context');
  assert.equal(error.message,'Audio is unavailable. Check browser audio. This audio will not be regenerated automatically.');
  return true;
 });assert.equal(calls,0);player.cancel();
});
