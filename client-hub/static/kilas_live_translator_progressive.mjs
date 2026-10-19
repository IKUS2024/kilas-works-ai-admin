import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
const LIMIT=20*1024*1024;
const failure=()=>Object.assign(Error(t('Pemutaran audio terputus.')+t(' Audio ini tidak dibuat ulang otomatis.')),{code:'audio_stalled',segmentPlayback:true});
export const progressiveSupported=()=>typeof MediaSource!=='undefined'&&typeof MediaSource.isTypeSupported==='function'&&MediaSource.isTypeSupported('audio/mpeg')&&typeof Audio!=='undefined'&&typeof (globalThis.AudioContext||globalThis.webkitAudioContext)?.prototype.createMediaElementSource==='function'&&typeof globalThis.crypto?.subtle?.digest==='function';
const permissionFailure=()=>Object.assign(Error(t('Audio belum diizinkan atau terputus. Periksa audio browser lalu tekan Lanjutkan.')),{code:'audio_permission',recoverable:false});

export function disposeProgressive(player){
 const slot=player.progressiveMedia;player.progressiveMedia=null;if(!slot)return;
 slot.ready=false;slot.audio.pause();slot.audio.removeAttribute('src');slot.audio.load();try{slot.node.disconnect();}catch{}
}

// Safari grants playback per element. Start/Resume call play() synchronously on
// this one element, then every turn replaces its source. The local silent WAV
// is not muted: a successful muted play would not prove sound permission.
export function prepareProgressive(player,signal,isCurrent){
 const context=player.getContext();
 if(!progressiveSupported()||!context)return Promise.resolve(false);
 if(player.progressiveMedia?.context!==context)disposeProgressive(player);
 let slot=player.progressiveMedia;
 if(!slot){
  try{const audio=new Audio();audio.preload='auto';audio.playsInline=true;audio.muted=false;audio.volume=1;const node=context.createMediaElementSource(audio);node.connect(context.destination);slot={audio,node,context,ready:false};player.progressiveMedia=slot;}
  catch{return Promise.resolve(false);}
 }
 if(slot.ready)return Promise.resolve(true);
 const bytes=new Uint8Array(204),view=new DataView(bytes.buffer);
 const word=(at,value)=>{for(let i=0;i<value.length;i++)bytes[at+i]=value.charCodeAt(i);};
 word(0,'RIFF');view.setUint32(4,196,true);word(8,'WAVEfmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,8000,true);view.setUint32(28,16000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);word(36,'data');view.setUint32(40,160,true);
 slot.audio.src='data:audio/wav;base64,'+btoa(String.fromCharCode(...bytes));
 return new Promise(resolve=>{
  let settled=false;
  const finish=ok=>{if(settled)return;settled=true;clearTimeout(timer);signal.removeEventListener('abort',cancel);slot.ready=Boolean(ok&&!signal.aborted&&isCurrent()&&player.progressiveMedia===slot);slot.audio.pause();resolve(slot.ready);};
  const cancel=()=>finish(false),timer=setTimeout(()=>finish(false),1500);
  signal.addEventListener('abort',cancel,{once:true});if(signal.aborted){cancel();return;}
  try{Promise.resolve(slot.audio.play()).then(()=>finish(true),()=>finish(false));}catch{finish(false);}
 });
}

// One already-dispatched TTS response. Sequential offset reads and appendBuffer
// acknowledgements bound both host copies and decoder queues. No paid action.
export function progressivePlay(player,url,signal,isCurrent,onStarted=()=>{}){
 if(!progressiveSupported()||!/^\/kilas-translator\/live\/sessions\/[a-f0-9]{48}\/turns\/live-[a-f0-9]{32}\/audio\/progress$/.test(url))return Promise.reject(failure());
 return player.run(signal,isCurrent,async op=>{
  const slot=player.progressiveMedia;
  if(!slot?.ready||slot.context!==op.context)throw permissionFailure();
  const audio=slot.audio,media=new MediaSource(),objectUrl=URL.createObjectURL(media),chunks=[];
  let buffer=null,total=0,started=false,ended=false,playFailure=null,blocked=null,expectedDigest=null,expectedSize=null;
  const onEnded=()=>{ended=true;},onError=()=>{playFailure=failure();};
  let cleaned=false;
  const finalUrl=url.slice(0,-'/progress'.length);
  const clean=()=>{if(cleaned)return;cleaned=true;
   if(started&&!ended&&Number.isFinite(audio.currentTime)&&audio.currentTime>0&&player.resumeOffsets){
    if(player.resumeOffsets.size>=50)player.resumeOffsets.delete(player.resumeOffsets.keys().next().value);
    player.resumeOffsets.set(finalUrl,Math.max(0,audio.currentTime-.1));
   }
   audio.removeEventListener('ended',onEnded);audio.removeEventListener('error',onError);
   audio.pause();audio.removeAttribute('src');audio.load();URL.revokeObjectURL(objectUrl);};
  op.controller.signal.addEventListener('abort',clean,{once:true});
  function wait(target,event,timeout=15000,act=()=>{}){
   return player.bounded(op,()=>new Promise((resolve,reject)=>{
    const done=()=>{clear();resolve();},bad=()=>{clear();reject(failure());},cancel=()=>{clear();reject(new DOMException('','AbortError'));};
    const clear=()=>{target.removeEventListener(event,done);target.removeEventListener('error',bad);op.controller.signal.removeEventListener('abort',cancel);};
    target.addEventListener(event,done,{once:true});target.addEventListener('error',bad,{once:true});op.controller.signal.addEventListener('abort',cancel,{once:true});
    try{act();}catch(e){clear();reject(e);}
   }),timeout,failure());
  }
  try{
   audio.addEventListener('ended',onEnded);audio.addEventListener('error',onError);
   const opened=wait(media,'sourceopen');audio.src=objectUrl;await opened;player.check(op);
   buffer=media.addSourceBuffer('audio/mpeg');
   const start=async()=>{
    try{await player.resume(op);player.check(op);await player.bounded(op,()=>audio.play(),5000,failure());player.check(op);started=true;onStarted();}
    catch(e){if(e?.name!=='NotAllowedError'&&e?.name!=='SecurityError'&&e?.code!=='audio_resume')throw e;player.check(op);slot.ready=false;blocked=e.code==='audio_resume'?e:permissionFailure();audio.pause();}
   };
   let complete=false,lastData=player.now(),idleDelay=40;
   while(!complete){
    player.check(op);if(playFailure)throw playFailure;
    const response=await player.bounded(op,()=>player.fetchAudio(url+'?offset='+total,{signal:op.controller.signal,cache:'no-store'}),15000,failure());
    if(![200,204].includes(response.status)||!/^audio\/mpeg(?:;|$)/i.test(response.headers.get('Content-Type')||''))throw failure();
    const offset=response.headers.get('X-Audio-Offset'),size=response.headers.get('X-Audio-Size'),flag=response.headers.get('X-Audio-Complete');
    if(offset!==String(total)||!/^(0|[1-9][0-9]*)$/.test(size||'')||!['0','1'].includes(flag)||Number(size)<total||Number(size)>LIMIT)throw failure();
    const declared=Number(response.headers.get('Content-Length'));if(!Number.isFinite(declared)||declared<0||declared>65536)throw failure();
    // Fetch streams are read with a hard chunk cap before assembling a response;
    // a lying Content-Length must not allocate an unbounded ArrayBuffer.
    const reader=response.body?.getReader();let count=0,parts=[];
    if(reader){try{while(true){const r=await player.bounded(op,()=>reader.read(),15000,failure());if(r.done)break;count+=r.value.byteLength;if(count>65536||total+count>LIMIT)throw failure();parts.push(r.value);}}finally{await reader.cancel().catch(()=>{});}}
    if(count!==declared||(response.status===204&&count))throw failure();
    const bytes=new Uint8Array(count);let n=0;for(const part of parts){bytes.set(part,n);n+=part.byteLength;}
    if(count){
     idleDelay=40;
     if(total+count>Number(size))throw failure();chunks.push(bytes);total+=count;lastData=player.now();
     await wait(buffer,'updateend',15000,()=>buffer.appendBuffer(bytes));
     if(!started&&!blocked&&buffer.buffered.length&&buffer.buffered.end(0)>=.15)await start();
    }
    if(flag==='1'){
     expectedDigest=response.headers.get('X-Audio-SHA256');expectedSize=Number(size);
     if(!/^[a-f0-9]{64}$/.test(expectedDigest||''))throw failure();complete=total===expectedSize;
    }
    if(!complete){if(player.now()-lastData>15000)throw failure();if(!count){await player.bounded(op,()=>new Promise(r=>setTimeout(r,idleDelay)),1000,failure());idleDelay=Math.min(250,idleDelay*2);}}
   }
   if(!total||total!==expectedSize)throw failure();
   const raw=new Uint8Array(total);let cursor=0;for(const part of chunks){raw.set(part,cursor);cursor+=part.byteLength;}
   const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(v=>v.toString(16).padStart(2,'0')).join('');if(digest!==expectedDigest)throw failure();
   if(buffer.updating)await wait(buffer,'updateend');media.endOfStream();
   if(!started&&!blocked)await start();
   // A denied element must not cancel the already-paid producer. Finish the
   // bounded download/digest and retain bytes for the explicit Resume gesture.
   if(blocked){player.check(op);player.remember(finalUrl,raw.buffer);return {sha256:digest,playbackError:blocked};}
   if(!Number.isFinite(audio.duration)||audio.duration<=0||audio.duration>600)throw failure();
   let lastClock=audio.currentTime,lastProgress=player.now();
   while(!ended){
    player.check(op);if(playFailure)throw playFailure;
    if(op.context.state!=='running')await player.resume(op);
    if(audio.currentTime>lastClock){lastClock=audio.currentTime;lastProgress=player.now();}
    if(player.now()-lastProgress>5000)throw failure();await player.bounded(op,()=>new Promise(r=>setTimeout(r,100)),1000,failure());
   }
   if(audio.currentTime<audio.duration-.1)throw failure();player.check(op);
   player.resumeOffsets?.delete(finalUrl);player.remember(finalUrl,raw.buffer);
   player.timing({progressive_audio_bytes:total});return {sha256:digest};
  }catch(e){e.segmentPlayback=true;throw e;}finally{op.controller.signal.removeEventListener('abort',clean);clean();}
 });
}
