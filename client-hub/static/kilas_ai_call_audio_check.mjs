// Explicit opt-in, provider-free hardware diagnostic. Never imports CallSession,
// sends requests, records audio, retains microphone PCM or enumerates devices.
import {CallCapture} from './kilas_ai_call_capture.mjs?v=call-ready-barge-in-20261017';
import {CallPlayer} from './kilas_ai_call_player.mjs?v=call-jitter-20261016';

export function safeTrackSettings(track){
 let settings={};try{settings=track?.getSettings?.()||{};}catch{}
 const result={};
 for(const name of ['echoCancellation','noiseSuppression','autoGainControl','channelCount','sampleRate','latency']){
  const value=settings[name];result[name]=typeof value==='boolean'||Number.isFinite(value)||(name==='echoCancellation'&&['all','remote-only'].includes(value))?value:null;
 }
 let modes=[];try{modes=track?.getCapabilities?.().echoCancellation||[];}catch{}
 result.echoCancellationModes=Array.isArray(modes)?modes.filter(value=>typeof value==='boolean'||['all','remote-only'].includes(value)):[];
 return result;
}

export function envelopeCorrelation(mic,reference){
 let best=null;
 for(let lag=0;lag<=1000;lag+=100){
  const pairs=[];
  for(const item of reference){
   const at=(item.start+item.end)/2+lag/1000;
   const frame=mic.reduce((near,value)=>!near||Math.abs(value.at-at)<Math.abs(near.at-at)?value:near,null);
   if(frame&&Math.abs(frame.at-at)<=.11)pairs.push([item.rms,frame.rms]);
  }
  if(pairs.length<12)continue;
  const x=pairs.reduce((sum,p)=>sum+p[0],0)/pairs.length,y=pairs.reduce((sum,p)=>sum+p[1],0)/pairs.length;
  let xy=0,xx=0,yy=0;for(const [a,b] of pairs){xy+=(a-x)*(b-y);xx+=(a-x)**2;yy+=(b-y)**2;}
  if(xx<=1e-18||yy<=1e-18)continue;
  const value=xy/Math.sqrt(xx*yy);
  if(best===null||value>best.coefficient)best={coefficient:value,lagMs:lag,pairs:pairs.length};
 }
 return best&&{...best,coefficient:Number(best.coefficient.toFixed(4))};
}

function syntheticChunk(index){
 const raw=new Uint8Array(9600),view=new DataView(raw.buffer);
 const amplitude=[.02,.08,0,.04,.08,.02,.04,0,.08,.04,.02,.08,0,.02,.08,.04,.02,0,.04,.08,.02,.04,.08,0,.04,.02,.08,.04,0,.08][index];
 for(let sample=0;sample<4800;sample++){
  const t=(index*4800+sample)/24000,fade=Math.min(1,sample/240,(4799-sample)/240);
  const signal=(Math.sin(2*Math.PI*317*t)+Math.sin(2*Math.PI*673*t)+Math.sin(2*Math.PI*1151*t)+Math.sin(2*Math.PI*1789*t))/4;
  view.setInt16(2*sample,Math.round(32767*amplitude*fade*signal),true);
 }
 return raw;
}

const start=globalThis.document?.querySelector('#check-start'),stop=globalThis.document?.querySelector('#check-stop'),status=globalThis.document?.querySelector('#check-status'),output=globalThis.document?.querySelector('#check-summary'),copy=globalThis.document?.querySelector('#check-copy');
let active=null;
function finish(run){
 if(run.finished)return;run.finished=true;run.controller.abort();clearTimeout(run.watchdog);
 run.capture?.cancel();run.player?.cancel();try{run.context?.close().catch(()=>{});}catch{}
 if(active===run){active=null;start.disabled=false;stop.disabled=true;}
}
function pause(run,ms){return new Promise((resolve,reject)=>{
 const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};
 const timer=setTimeout(()=>{run.controller.signal.removeEventListener('abort',abort);resolve();},ms);
 run.controller.signal.addEventListener('abort',abort,{once:true});if(run.controller.signal.aborted)abort();
});}
function cancel(){const run=active;if(!run)return;finish(run);status.textContent='Tes dihentikan. Mikrofon dan bunyi tes sudah dimatikan.';}
start?.addEventListener('click',async()=>{
 if(active)return;const run={controller:new AbortController(),finished:false,mic:[],reference:[],samples:0,clipped:0,peak:0};active=run;
 start.disabled=true;stop.disabled=false;copy.hidden=true;output.textContent='';status.textContent='Menyiapkan mikrofon…';
 try{
  const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Error('unavailable');
  const context=run.context=new Audio({latencyHint:'playback'});await context.resume();if(run.finished)return;
  run.watchdog=setTimeout(()=>{cancel();},25000);
  const onError=()=>{if(!run.finished){finish(run);status.textContent='Tes audio gagal. Tidak ada AI Call yang dimulai.';}};
  const capture=run.capture=new CallCapture({getContext:()=>context,mediaDevices:navigator.mediaDevices});
  const player=run.player=new CallPlayer({getContext:()=>context,onError,onScheduled:(buffer,at)=>{
   const data=buffer.getChannelData(0);let energy=0;for(const value of data)energy+=value*value;
   run.reference.push({start:at,end:at+buffer.duration,rms:Math.sqrt(energy/data.length)});
  }});
  await capture.start({ready:()=>{},blob:()=>{},error:onError,level:(rms,ms)=>{if(!run.finished)run.mic.push({at:context.currentTime-ms/2000,rms});},pcm:raw=>{
   if(run.finished)return;const view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);
   for(let i=0;i<raw.length;i+=2){const value=Math.abs(view.getInt16(i,true)/32768);run.peak=Math.max(run.peak,value);run.samples++;if(value>=.98)run.clipped++;}
  }});
  if(run.finished)return;const settings=safeTrackSettings(capture.stream.getAudioTracks()[0]);
  const baselineAt=context.currentTime;status.textContent='Tetap diam. Mengukur suara ruangan…';await pause(run,2000);
  status.textContent='Bunyi tes sedang diputar. Tetap diam…';for(let index=0;index<30;index++)player.push(syntheticChunk(index));
  await player.checkpoint();if(run.finished)return;status.textContent='Hampir selesai. Tetap diam…';await pause(run,2000);
  const first=run.reference[0].start,last=run.reference.at(-1).end;
  const rms=frames=>frames.length?Math.sqrt(frames.reduce((sum,value)=>sum+value.rms**2,0)/frames.length):null;
  const baseline=run.mic.filter(frame=>frame.at>=baselineAt&&frame.at<first),playback=run.mic.filter(frame=>frame.at>=first&&frame.at<=last),tail=run.mic.filter(frame=>frame.at>last+.3);
  const summary={test:'kilas-local-audio-v1',providerCalls:0,audioUploaded:false,audioRecorded:false,physicalDeviceConclusion:'requires review; this test does not identify provider VAD cause',
   settings,output:{sampleRate:context.sampleRate,baseLatencySeconds:context.baseLatency??null,outputLatencySeconds:context.outputLatency??null},
   capture:{frames:run.mic.length,samples:run.samples,peak:Number(run.peak.toFixed(5)),clippedSamples:run.clipped,baselineRms:rms(baseline),playbackRms:rms(playback),tailRms:rms(tail)},
   playbackEnvelopeCorrelation:envelopeCorrelation(run.mic,run.reference),assumption:'user remained silent; correlation is approximate, not an AEC pass/fail or provider VAD measurement'};
  finish(run);output.textContent=JSON.stringify(summary,null,2);copy.hidden=false;status.textContent='Selesai. Mikrofon dimatikan. Salin ringkasan angka untuk pemeriksaan.';
 }catch(error){if(!run.finished){finish(run);status.textContent=error?.name==='NotAllowedError'?'Izin mikrofon belum diberikan. Tidak ada AI Call yang dimulai.':'Tes belum selesai. Tidak ada AI Call yang dimulai.';}}
 finally{run.mic.length=0;run.reference.length=0;}
});
stop?.addEventListener('click',cancel);
copy?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(output.textContent);status.textContent='Ringkasan angka disalin.';}catch{status.textContent='Pilih dan salin ringkasan angka di atas.';}});
globalThis.addEventListener?.('pagehide',cancel);globalThis.document?.addEventListener('visibilitychange',()=>{if(document.hidden)cancel();});
