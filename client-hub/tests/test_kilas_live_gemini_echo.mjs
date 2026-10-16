// Synthetic reference/PCM only; no browser, microphone or provider IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {PlaybackEcho} from '../static/kilas_live_gemini_echo.mjs';
function fixture(){
 const context={currentTime:.8},echo=new PlaybackEcho({getContext:()=>context});
 const reference4k=Float32Array.from({length:400},(_,i)=>Math.sin(i*.19)*.3+Math.sin(i*.371)*.15);
 const reference24k=Float32Array.from({length:2400},(_,i)=>reference4k[Math.floor(i/6)]);
 echo.remember({sampleRate:24000,getChannelData:()=>reference24k},.2);
 function frame({gain=.7,voice=()=>0}={}){
  const raw=new Uint8Array(3200),view=new DataView(raw.buffer);let voiceEnergy=0;
  for(let i=0;i<1600;i++){const spoken=voice(i);voiceEnergy+=spoken**2;view.setInt16(i*2,Math.round((reference4k[Math.floor(i/4)]*gain+spoken)*32768),true);}
  return {raw,voiceRms:Math.sqrt(voiceEnergy/1600)};
 }
 return {echo,context,frame};
}

test('a delayed scaled reference remains recognizable when the original-rate residual is below the conservative floor',()=>{
 const f=fixture();
 for(const gain of [.1,.35,.7,1])assert.equal(f.echo.matches(f.frame({gain}).raw),true);
 assert.equal(f.echo.matches(f.frame({voice:i=>Math.sin(i*.031)*.001}).raw),true);
 f.echo.hold(.2);assert.equal(f.echo.matches(f.frame().raw),false);
});

test('quieter new speech above VAD is retained even when louder playback dominates correlation',()=>{
 const f=fixture();
 for(const amplitude of [.03,.04,.045,.15]){
  const {raw,voiceRms}=f.frame({voice:i=>Math.sin(i*.031)*amplitude});
  assert.ok(voiceRms>=.015);assert.equal(f.echo.matches(raw),false);
 }
});

test('downsampling cannot conceal new speech energy inside a strongly correlated playback frame',()=>{
 const f=fixture(),{raw,voiceRms}=f.frame({voice:i=>[.04,-.04,.04,-.04][i%4]});
 assert.ok(voiceRms>=.015);
 // Each four-sample average removes this unrelated component completely, so
 // the4k correlation is effectively perfect. The16k residual retains it.
 assert.equal(f.echo.matches(raw),false);
});

test('uncertain low-level mixtures above the residual floor remain input',()=>{
 const f=fixture(),{raw,voiceRms}=f.frame({voice:i=>Math.sin(i*.031)*.006});
 assert.ok(voiceRms>.003&&voiceRms<.015);assert.equal(f.echo.matches(raw),false);
});
