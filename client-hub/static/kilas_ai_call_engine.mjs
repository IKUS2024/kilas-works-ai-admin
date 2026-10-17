// Injectable Call lifecycle. No microphone, provider or network work on import.
import {prepareCallPcm} from './kilas_ai_call_pcm.mjs?v=call-understanding-gain-20261017';
const aborted=()=>new DOMException('Aborted','AbortError');
const failure=code=>Object.assign(Error(code),{code});
// The HTML language comes from the existing cookie-backed UI resolver.
export function callLanguage(value){
 const language=typeof value==='string'?value.trim().toLowerCase().split(/[-_]/)[0]:'';
 return ['id','en','es','zh'].includes(language)?language:'en';
}
export class CallInput {
 constructor({request,path,signal,onError=()=>{}}){
  Object.assign(this,{request,path,signal,onError});this.pending=new Uint8Array(16000);this.length=0;this.index=0;this.queued=0;this.total=0;this.firstPacket=true;
  this.chain=new Promise((resolve,reject)=>{this.open=resolve;this.rejectOpen=reject;});this.chain.catch(()=>{});
 }
 push(raw){
  if(this.signal.aborted)throw aborted();
  if(!(raw instanceof Uint8Array)||!raw.length||raw.length%2||raw.length>16000)throw failure('call_input_invalid');
  if(this.queued+raw.length>8*32000)throw failure('call_backlog');
  this.queued+=raw.length;this.total+=raw.length;let at=0;
  while(at<raw.length){const count=Math.min(raw.length-at,16000-this.length);this.pending.set(raw.subarray(at,at+count),this.length);this.length+=count;at+=count;if(this.length===16000)this.flush();}
  if(this.firstPacket){this.firstPacket=false;this.flush();}
 }
 flush(){
  if(!this.length)return;const raw=this.pending.slice(0,this.length);this.length=0;
  const work=this.chain.then(async()=>{
   if(this.signal.aborted)throw aborted();
   const index=this.index++;
   const result=await this.request(this.path+'/chunks/'+index,{method:'POST',body:raw,signal:this.signal,timeoutMs:8000});
   if(result.accepted_index!==index)throw failure('call_input_invalid');
  }).finally(()=>{this.queued-=raw.length;});
  this.chain=work;work.catch(error=>{if(!this.signal.aborted)this.onError(error);});
 }
 cancel(){this.rejectOpen(aborted());this.pending.fill(0);this.length=0;}
}

export class CallSession {
 constructor({request,capture,player,prepare=async()=>{},stopAudio=()=>{},onState=()=>{},onError=()=>{},onText=()=>{},onSources=()=>{},
  getLanguage=()=>globalThis.document?.documentElement?.lang||'en',
  key=()=>crypto.randomUUID().replaceAll('-',''),schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id)}){
  Object.assign(this,{request,capture,player,prepare,stopAudio,onState,onError,onText,onSources,getLanguage,key,schedule,clear});this.version=0;this.state='ended';
 }
 stateTo(value){this.state=value;this.onState(value);}
 current(ticket){return ticket===this.version&&!this.controller?.signal.aborted;}
 async start(){
  if(this.state!=='ended')return;
  const ticket=++this.version;this.controller=new AbortController();const signal=this.controller.signal;
  this.ident=this.key();this.path='/kilas-ai/call/'+this.ident;this.admitted=false;this.speaking=false;this.echoGuard=false;this.turnSealed=false;this.cursor=0;this.playVersion=0;
  this.captureReady=false;this.readyRequested=false;this.readyAcknowledged=false;this.userStartedSpeaking=false;this.openingSpeechMs=0;
  this.stateTo('connecting');this.onText('');this.onSources([]);this.sourceAwaitingAudio=false;
  this.input=new CallInput({request:this.request,path:this.path,signal,onError:error=>this.fail(error,ticket)});
  try{
   // Called synchronously from the click to preserve the audio user gesture.
   const prepared=Promise.resolve(this.prepare(signal));prepared.catch(()=>{});
   const eligibility=await this.request('/kilas-ai/call/readiness',{signal,timeoutMs:8000});
   if(!this.current(ticket))return;
   if(!eligibility.available)throw failure(eligibility.reason||'call_unavailable');
   await prepared;if(!this.current(ticket))return;
   await this.capture.start({ready:()=>{},level:(rms,durationMs)=>{
    // Startup evidence only, using raw AEC capture before quiet-input gain.
    // Sustained signal avoids treating a quiet room or one click as speech.
    // Provider VAD/transcription remains authoritative; no PCM is gated here.
    if(this.current(ticket)&&Number.isFinite(rms)&&Number.isFinite(durationMs)&&durationMs>0){
     this.openingSpeechMs=rms>=.004?this.openingSpeechMs+durationMs:0;
     if(this.openingSpeechMs>=400)this.userStartedSpeaking=true;
    }
   },blob:()=>{},
    pcm:raw=>{if(this.current(ticket)){try{
     // Capture is already browser AEC/NS/AGC processed. Keep real microphone
     // speech during playback so provider VAD can interrupt the current turn.
     // Avoid boosting residual speaker echo with the quiet-input gain.
     this.input.push(this.speaking||this.echoGuard?raw:prepareCallPcm(raw));
     if(this.speaking)this.input.flush();
    }catch(error){this.fail(error,ticket);}}},
    error:error=>this.fail(error,ticket)});
   if(!this.current(ticket))return;
   this.captureReady=true;
   this.admitted=true;
   const result=await this.request(this.path,{method:'POST',signal,timeoutMs:12000});
   if(!this.current(ticket))return;
   if(result.call_id!==this.ident)throw failure('call_protocol');
   this.input.open();
   await this.poll(ticket);
  }catch(error){if(this.current(ticket))this.fail(error,ticket);}
 }
 notifyReady(ticket){
  if(!this.current(ticket)||!this.captureReady||this.readyRequested)return;
  this.readyRequested=true;
  // Deliver the first utterance before allowing a greeting. Snapshot this
  // chain: ongoing capture must not hold readiness (or polling) indefinitely.
  this.input.flush();const buffered=this.input.chain;
  this.readyTask=(async()=>{
   await buffered;if(!this.current(ticket))return;
   const result=await this.request(this.path+'/ready',{method:'POST',signal:this.controller.signal,timeoutMs:8000,
    json:{language:callLanguage(this.getLanguage()),user_started_speaking:this.userStartedSpeaking}});
   if(!this.current(ticket))return;
   if(result.ready!==true)throw failure('call_protocol');
   this.readyAcknowledged=true;
  })().catch(error=>{if(this.current(ticket))this.fail(error,ticket);});
 }
 async poll(ticket){
  while(this.current(ticket)){
   const value=await this.request(this.path+'?after='+this.cursor,{signal:this.controller.signal,timeoutMs:8000});
   if(!this.current(ticket))return;
   if(!Array.isArray(value.frames)||!Number.isInteger(value.next_index)||value.next_index!==this.cursor+value.frames.length)throw failure('call_protocol');
   if(value.state!=='CLOSED'&&value.provider_ready===true)this.notifyReady(ticket);
   for(const frame of value.frames){
    if(!this.current(ticket))return;
    if(frame.index!==this.cursor++)throw failure('call_protocol');
    if(frame.type==='audio'){
     if(typeof frame.pcm!=='string'||frame.pcm.length>12800)throw failure('call_protocol');
     if(!this.speaking||this.turnSealed){this.clear(this.echoTimer);this.echoTimer=null;this.echoGuard=false;this.turnSealed=false;this.speaking=true;this.playVersion++;this.onText('');if(!this.sourceAwaitingAudio)this.onSources([]);this.sourceAwaitingAudio=false;}
     this.stateTo('speaking');const raw=Uint8Array.from(atob(frame.pcm),c=>c.charCodeAt(0));this.player.push(raw,'call');
    }else if(frame.type==='text'){
     if(typeof frame.text!=='string'||frame.text.length>4000)throw failure('call_protocol');this.onText(frame.text);
    }else if(frame.type==='sources'){
     if(!Array.isArray(frame.citations)||frame.citations.length>3||frame.citations.some(item=>!item||typeof item.url!=='string'||item.url.length>2048||typeof item.title!=='string'||item.title.length>160))throw failure('call_protocol');
     this.onSources(frame.citations,frame.checked_on);this.sourceAwaitingAudio=frame.citations.length>0&&(!this.speaking||this.turnSealed);
    }else if(frame.type==='reset'){
     // Fence the old drain callback before cancel rejects its checkpoint.
     // Call owns one output queue, including audio scheduled ahead of now.
     this.playVersion++;this.clear(this.echoTimer);this.turnSealed=false;this.speaking=false;this.echoGuard=true;this.player.cancel();this.onText('');this.onSources([]);this.sourceAwaitingAudio=false;this.stateTo('listening');
     const generation=this.playVersion;
     this.echoTimer=this.schedule(()=>{if(this.current(ticket)&&generation===this.playVersion){this.echoTimer=null;this.echoGuard=false;}},300);
    }else if(frame.type==='turn_complete'){
     if(!this.speaking)continue;
     this.turnSealed=true;const generation=this.playVersion;
     this.player.checkpoint().then(()=>{
      if(this.current(ticket)&&generation===this.playVersion){
       // Keep unity capture gain through the short room/speaker decay. Real
       // mic PCM continues throughout; End and newer audio fence this callback.
       this.clear(this.echoTimer);this.echoTimer=this.schedule(()=>{
        if(this.current(ticket)&&generation===this.playVersion){this.echoTimer=null;this.speaking=false;this.stateTo('listening');}
       },300);
      }
     },error=>{if(this.current(ticket)&&generation===this.playVersion)this.fail(error,ticket);});
    }else throw failure('call_protocol');
   }
   if(value.state==='CLOSED'&&this.cursor>=value.total_frames){
    if(['budget_limit','account_credit_limit'].includes(value.code))await this.player.checkpoint();
    if(this.current(ticket))this.fail(failure(value.code||'call_ended'),ticket);return;
   }
   if(value.state==='LISTENING'&&!this.speaking)this.stateTo('listening');
   await new Promise(resolve=>{this.pollTimer=this.schedule(resolve,250);this.pollResolve=resolve;});
  }
 }
 fail(error,ticket=this.version){if(!this.current(ticket))return;this.end();this.onError(error.code||'call_transport');}
 end(){
  const path=this.path,admitted=this.admitted;this.admitted=false;this.ident=null;this.path=null;++this.version;
  this.controller?.abort();this.clear(this.timer);this.clear(this.echoTimer);this.clear(this.pollTimer);this.pollResolve?.();this.pollResolve=null;
  try{this.input?.cancel();}catch{}try{this.capture.cancel();}catch{}try{this.player.cancel();}catch{}try{this.stopAudio();}catch{}
  this.speaking=false;this.echoGuard=false;this.onText('');this.onSources([]);this.sourceAwaitingAudio=false;this.stateTo('ended');
  if(path&&admitted){try{Promise.resolve(this.request(path+'/end',{method:'POST',keepalive:true,timeoutMs:8000})).catch(()=>{});}catch{}}
 }
}
