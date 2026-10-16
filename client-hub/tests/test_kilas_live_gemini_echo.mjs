// Synthetic reference/PCM only; no browser, microphone or provider IO.
import test from 'node:test';
import assert from 'node:assert/strict';
import {PlaybackEcho} from '../static/kilas_live_gemini_echo.mjs';
import {PcmEncoder} from '../static/kilas_live_translator_pcm.mjs';
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

const multiband=t=>.12*Math.sin(2*Math.PI*220*t)+.07*Math.sin(2*Math.PI*750*t)+.04*Math.sin(2*Math.PI*2500*t);
function continuous(wave=multiband){
 const context={currentTime:1.2,sampleRate:16000},echo=new PlaybackEcho({getContext:()=>context});
 const reference=Float32Array.from({length:24000},(_,i)=>wave(i/24000));
 echo.remember({sampleRate:24000,getChannelData:()=>reference},.2);
 const frame=({delay=.15,gain=.5,rate=16000,voice=()=>0}={})=>{
  context.sampleRate=rate;const output=[],encoder=new PcmEncoder(rate,value=>output.push(new Uint8Array(value.bytes)),1600);
  const samples=Float32Array.from({length:rate/10},(_,i)=>wave(context.currentTime-.1-delay-.2+i/rate)*gain+voice(i/rate));
  for(let i=0;i<samples.length;i+=4096)encoder.feed([samples.subarray(i,i+4096)]);
  encoder.finish();assert.equal(output.length,1);return output[0];
 };
 return {context,echo,frame};
}

test('continuous24k playback matches full-band pure echo at integer, fractional and formerly5ms-off-grid delays',()=>{
 for(const hz of [100,500,1000,2500]){
  const f=continuous(t=>.2*Math.sin(2*Math.PI*hz*t));
  for(const delay of [0,.15003125,.1536875,.599,.6])assert.equal(f.echo.matches(f.frame({delay})),true,`${hz}Hz delay${delay}`);
 }
});

test('continuous multiband playback survives the actual16k encoder at supported capture rates',()=>{
 const f=continuous();
 for(const rate of [16000,24000,44100,48000,96000])assert.equal(f.echo.matches(f.frame({rate,delay:.1536875})),true,`capture${rate}`);
});

test('full-band pure playback matches the real capture filter through7.1kHz at common context rates',()=>{
 for(const hz of [400,1000,2000,3000,4000,7100]){
  const f=continuous(t=>.2*Math.sin(2*Math.PI*hz*t));
  for(const rate of [16000,44100,48000,96000])assert.equal(f.echo.matches(f.frame({rate,delay:.1536875})),true,`${hz}Hz capture${rate}`);
 }
});

test('uncertain fractional-delay24k capture remains input instead of loosening the residual floor',()=>{
 const f=continuous(t=>.2*Math.sin(2*Math.PI*2000*t));
 assert.equal(f.echo.matches(f.frame({rate:24000,delay:.1536875})),false);
});

test('full-band alignment retains quiet new speech mixed with continuous loud playback',()=>{
 const f=continuous();
 for(const voice of [t=>.03*Math.sin(2*Math.PI*1317*t),t=>.03*Math.sin(2*Math.PI*4000*t),t=>.03*Math.sin(2*Math.PI*7100*t)]){
  assert.equal(f.echo.matches(f.frame({delay:.15003125,voice})),false);
 }
 assert.equal(f.echo.matches(f.frame({voice:t=>.006*Math.sin(2*Math.PI*1317*t)})),false);
});

test('silence, future playback and reference older than600ms cannot be classified as current echo',()=>{
 const f=continuous(),raw=f.frame();
 assert.equal(f.echo.matches(new Uint8Array(3200)),false);
 f.context.currentTime=.1;assert.equal(f.echo.matches(raw),false);
 f.context.currentTime=2;assert.equal(f.echo.matches(raw),false);
 f.echo.hold(.2);assert.equal(f.echo.matches(raw),false);
});

test('reference retention prunes old scheduled buffers and hold removes future samples',()=>{
 const f=continuous(),buffer={sampleRate:24000,getChannelData:()=>Float32Array.from({length:2400},(_,i)=>multiband(i/24000))};
 for(let i=0;i<100;i++){f.context.currentTime=i*.1;f.echo.remember(buffer,i*.1);}
 assert.ok(f.echo.segments.length<=12);assert.ok(f.echo.segments.reduce((total,item)=>total+item.values.length,0)<=12*2400);
 f.echo.hold(f.context.currentTime+.025);
 assert.ok(f.echo.segments.every(item=>item.at+item.values.length/24000<=f.context.currentTime+.025));
 f.echo.reset();assert.equal(f.echo.segments.length,0);
});
