import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {prepareCallPcm} from '../static/kilas_ai_call_pcm.mjs';
const stats=raw=>{const view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);let energy=0,peak=0;for(let i=0;i<raw.length;i+=2){const value=view.getInt16(i,true)/32768;energy+=value*value;peak=Math.max(peak,Math.abs(value));}return {rms:Math.sqrt(energy/(raw.length/2)),peak};};
test('Quiet Indonesian input gains audibility without dropping, reordering or clipping any sample',t=>{
 const wav=readFileSync(new URL('./fixtures/ai_call_synthetic/id-first.wav',import.meta.url)),raw=new Uint8Array(wav.subarray(44));
 let peak=0,gained=0;const parts=[];
 for(let i=0;i<raw.length;i+=6400){const input=raw.subarray(i,i+6400),before=stats(input),output=prepareCallPcm(input),after=stats(output);parts.push(output);
  assert.equal(output.length,input.length);assert.ok(after.peak<=.951);assert.ok(after.rms>=before.rms-1/32768);peak=Math.max(peak,after.peak);
  if(before.rms>=.002&&before.rms<.06){gained++;assert.ok(after.rms>.015);assert.ok(after.rms<=before.rms*8+1/32768);}
 }
 assert.ok(gained>10);assert.equal(parts.reduce((n,p)=>n+p.length,0),raw.length);
 t.diagnostic(JSON.stringify({synthetic:true,duration_ms:raw.length/32,frames_with_bounded_gain:gained,output_peak:peak}));
});
test('Silence, low-level non-speech and normal browser AGC output retain exactly their original PCM',()=>{
 const silent=new Uint8Array(6400);assert.equal(prepareCallPcm(silent),silent);
 for(const amplitude of [40,6000]){const raw=new Uint8Array(6400),view=new DataView(raw.buffer);for(let i=0;i<3200;i++)view.setInt16(i*2,Math.round(amplitude*Math.sin(i*.37)),true);assert.equal(prepareCallPcm(raw),raw);}
});
test('A quiet frame containing a large transient cannot clip, and no source buffer is mutated',()=>{
 const raw=new Uint8Array(6400),view=new DataView(raw.buffer);for(let i=0;i<3200;i++)view.setInt16(i*2,200,true);view.setInt16(0,30000,true);
 const before=raw.slice(),after=prepareCallPcm(raw);assert.deepEqual(raw,before);assert.ok(stats(after).peak<=.951);
 for(const bad of [null,new Uint8Array(3),new Uint8Array(16002)])assert.throws(()=>prepareCallPcm(bad),/call_input_invalid/);
});
