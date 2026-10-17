// Call-only input conditioning. Browser AGC is requested but is device-dependent.
// Preserve every sample and the 16k PCM clock; never turn silence into speech.
export function prepareCallPcm(raw){
 if(!(raw instanceof Uint8Array)||!raw.length||raw.length%2||raw.length>16000)throw Object.assign(Error('call_input_invalid'),{code:'call_input_invalid'});
 const view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);let energy=0,peak=0;
 for(let i=0;i<raw.length;i+=2){const value=view.getInt16(i,true)/32768;energy+=value*value;peak=Math.max(peak,Math.abs(value));}
 const rms=Math.sqrt(energy/(raw.length/2));
 // Leave near-silence/noise and already strong input untouched. For quiet
 // input, a capped gain preserves the waveform and prevents PCM clipping.
 if(rms<.002||rms>=.06)return raw;
 const gain=Math.min(8,.06/rms,.95/peak);if(gain<=1)return raw;
 const bytes=new Uint8Array(raw.length),output=new DataView(bytes.buffer);
 for(let i=0;i<raw.length;i+=2)output.setInt16(i,Math.round(view.getInt16(i,true)*gain),true);
 return bytes;
}
