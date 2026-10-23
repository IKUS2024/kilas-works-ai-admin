// Injectable Call lifecycle. No microphone, provider or network work on import.
import {prepareCallPcm} from './kilas_ai_call_pcm.mjs?v=call-understanding-gain-20261017';
const aborted=()=>new DOMException('Aborted','AbortError');
const failure=code=>Object.assign(Error(code),{code});
const transient=error=>error?.code==='request_timeout'||error instanceof TypeError||[502,503,504].includes(error?.status);
const backoff=(signal,ms)=>new Promise((resolve,reject)=>{
 const cancel=()=>{clearTimeout(timer);signal.removeEventListener('abort',cancel);reject(aborted());};
 const timer=setTimeout(()=>{signal.removeEventListener('abort',cancel);resolve();},ms);
 signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
});
export class CallInput {
 constructor({request,path,signal,onError=()=>{},onRecovery=()=>{},wait=backoff}){
  Object.assign(this,{request,path,signal,onError,onRecovery,wait});this.pending=new Uint8Array(16000);this.length=0;this.index=0;this.queued=0;this.total=0;this.firstPacket=true;
  this.chain=new Promise((resolve,reject)=>{this.open=resolve;this.rejectOpen=reject;});this.chain.catch(()=>{});
 }
 push(raw){
  if(this.signal.aborted)throw aborted();
  if(!(raw instanceof Uint8Array)||!raw.length||raw.length%2||raw.length>16000)throw failure('call_input_invalid');
  if(this.queued+raw.length>20*32000)throw failure('call_backlog');
  this.queued+=raw.length;this.total+=raw.length;let at=0;
  while(at<raw.length){const count=Math.min(raw.length-at,16000-this.length);this.pending.set(raw.subarray(at,at+count),this.length);this.length+=count;at+=count;if(this.length===16000)this.flush();}
  if(this.firstPacket){this.firstPacket=false;this.flush();}
 }
 flush(){
  if(!this.length)return;const raw=this.pending.slice(0,this.length);this.length=0;
  const work=this.chain.then(async()=>{
   if(this.signal.aborted)throw aborted();
   const index=this.index++;
   for(let attempt=0;;attempt++){
    if(this.signal.aborted)throw aborted();
    try{
     const result=await this.request(this.path+'/chunks/'+index,{method:'POST',body:raw,signal:this.signal,timeoutMs:5000});
     if(result.accepted_index!==index)throw failure('call_input_invalid');
     if(attempt)this.onRecovery(false);break;
    }catch(error){
     if(this.signal.aborted)throw aborted();
     if(!transient(error)||attempt>=2)throw error;
     this.onRecovery(true);await this.wait(this.signal,300*(attempt+1));
    }
   }
  }).finally(()=>{this.queued-=raw.length;});
  this.chain=work;work.catch(error=>{if(!this.signal.aborted)this.onError(error);});
 }
 cancel(){this.rejectOpen(aborted());this.pending.fill(0);this.length=0;}
}

export class CallSession {
 constructor({request,capture,player,prepare=async()=>{},stopAudio=()=>{},onState=()=>{},onError=()=>{},onText=()=>{},onSources=()=>{},
  key=()=>crypto.randomUUID().replaceAll('-',''),schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id)}){
  Object.assign(this,{request,capture,player,prepare,stopAudio,onState,onError,onText,onSources,key,schedule,clear});this.version=0;this.state='ended';
 }
 stateTo(value){this.state=value;this.onState(value);}
 current(ticket){return ticket===this.version&&!this.controller?.signal.aborted;}
 async start(settings={}){
  if(this.state!=='ended')return;
  const ticket=++this.version;this.controller=new AbortController();const signal=this.controller.signal;
  this.ident=this.key();this.path='/kilas-ai/call/'+this.ident;this.admitted=false;this.lastServerState='CONNECTING';this.uploadRecovering=false;this.speaking=false;this.turnSealed=false;this.cursor=0;this.playVersion=0;
  this.stateTo('connecting');this.onText('');this.onSources([]);this.sourceAwaitingAudio=false;this.captionAwaitingAudio=false;
  this.input=new CallInput({request:this.request,path:this.path,signal,onRecovery:active=>{if(this.current(ticket)){this.uploadRecovering=active;this.stateTo(active?'reconnecting':this.lastServerState==='CONNECTING'?'connecting':this.lastServerState==='RECONNECTING'?'reconnecting':this.speaking?'speaking':'listening');}},onError:error=>this.fail(error,ticket)});
  try{
   // Called synchronously from the click to preserve the audio user gesture.
   const prepared=Promise.resolve(this.prepare(signal));prepared.catch(()=>{});
   const eligibility=await this.request('/kilas-ai/call/readiness',{signal,timeoutMs:8000});
   if(!this.current(ticket))return;
   if(!eligibility.available)throw failure(eligibility.reason||'call_unavailable');
   await prepared;if(!this.current(ticket))return;
   await this.capture.start({ready:()=>{},level:()=>{},blob:()=>{},
    pcm:raw=>{if(this.current(ticket)){try{
     // Keep the provider's VAD clock running during playback, without sending
     // speaker echo back as another question. Never reuse microphone PCM here.
     this.input.push(this.speaking?new Uint8Array(raw.length):prepareCallPcm(raw));
    }catch(error){this.fail(error,ticket);}}},
    error:error=>this.fail(error,ticket)});
   if(!this.current(ticket))return;
   this.admitted=true;
   this.settings={...settings};
   const body=new FormData();body.append('settings',JSON.stringify(this.settings));
   const result=await this.request(this.path,{method:'POST',body,signal,timeoutMs:12000});
   if(!this.current(ticket))return;
   if(result.call_id!==this.ident)throw failure('call_protocol');
   this.input.open();
   await this.poll(ticket);
  }catch(error){if(this.current(ticket))this.fail(error,ticket);}
 }
 async pause(ticket,ms){
  if(!this.current(ticket))return;
  await new Promise(resolve=>{this.pollResolve=resolve;this.pollTimer=this.schedule(()=>{this.pollTimer=null;this.pollResolve=null;resolve();},ms);});
 }
 async poll(ticket){
  let transientFailures=0;
  while(this.current(ticket)){
   let value;
   try{value=await this.request(this.path+'?after='+this.cursor,{signal:this.controller.signal,timeoutMs:8000});transientFailures=0;}
   catch(error){
    if(!this.current(ticket))return;
    // Polling only reads the same server session/cursor. Never repeat admission,
    // PCM POSTs or provider requests when their outcome may be uncertain.
    if(!transient(error)||transientFailures>=2)throw error;
    this.stateTo('reconnecting');
    await this.pause(ticket,300*++transientFailures);continue;
   }
   if(!this.current(ticket))return;
   this.lastServerState=value.state;
   if(!Array.isArray(value.frames)||!Number.isInteger(value.next_index)||value.next_index!==this.cursor+value.frames.length)throw failure('call_protocol');
   for(const frame of value.frames){
    if(!this.current(ticket))return;
    if(frame.index!==this.cursor++)throw failure('call_protocol');
    if(frame.type==='audio'){
     if(typeof frame.pcm!=='string'||frame.pcm.length>12800)throw failure('call_protocol');
     // Reply arrival must not erase the question's captured/upload-pending
     // tail. Its original bytes stay ahead of subsequent playback silence.
     if(!this.speaking||this.turnSealed){this.clear(this.echoTimer);this.echoTimer=null;this.turnSealed=false;this.speaking=true;this.playVersion++;this.input.flush();if(!this.captionAwaitingAudio)this.onText('');this.captionAwaitingAudio=false;if(!this.sourceAwaitingAudio)this.onSources([]);this.sourceAwaitingAudio=false;}
     this.stateTo('speaking');const raw=Uint8Array.from(atob(frame.pcm),c=>c.charCodeAt(0));this.player.push(raw,'call');
    }else if(frame.type==='text'){
     if(typeof frame.text!=='string'||frame.text.length>4000)throw failure('call_protocol');this.onText(frame.text);
     // Transcription and audio arrive independently. Preserve an early caption
     // when this answer's first audio frame arrives, including across polls.
     this.captionAwaitingAudio=!this.speaking||this.turnSealed;
    }else if(frame.type==='sources'){
     if(!Array.isArray(frame.citations)||frame.citations.length>3||frame.citations.some(item=>!item||typeof item.url!=='string'||item.url.length>2048||typeof item.title!=='string'||item.title.length>160))throw failure('call_protocol');
     this.onSources(frame.citations,frame.checked_on);this.sourceAwaitingAudio=frame.citations.length>0&&(!this.speaking||this.turnSealed);
    }else if(frame.type==='reset'){
     this.clear(this.echoTimer);this.player.cancel();this.turnSealed=false;this.speaking=false;this.playVersion++;this.onText('');this.onSources([]);this.sourceAwaitingAudio=false;this.captionAwaitingAudio=false;
     this.stateTo('listening');
    }else if(frame.type==='turn_complete'){
     this.turnSealed=true;this.captionAwaitingAudio=false;const generation=this.playVersion;
     this.player.checkpoint().then(()=>{
      if(this.current(ticket)&&generation===this.playVersion){
       // Discard the final worklet frame containing room/speaker decay before
       // showing Listening. End and a newer answer fence this callback too.
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
   if(value.state==='RECONNECTING'||this.uploadRecovering)this.stateTo('reconnecting');
   else if(value.state==='LISTENING'&&!this.speaking)this.stateTo('listening');
   await this.pause(ticket,250);
  }
 }
 fail(error,ticket=this.version){if(!this.current(ticket))return;const code=error.code||(transient(error)?'call_network':'call_transport');this.end(code);this.onError(code);}
 end(reason='call_ended'){
  const path=this.path,admitted=this.admitted;this.admitted=false;this.ident=null;this.path=null;++this.version;
  this.controller?.abort();this.clear(this.timer);this.clear(this.echoTimer);this.clear(this.pollTimer);this.pollResolve?.();this.pollResolve=null;
  try{this.input?.cancel();}catch{}try{this.capture.cancel();}catch{}try{this.player.cancel();}catch{}try{this.stopAudio();}catch{}
  this.speaking=false;this.onText('');this.onSources([]);this.sourceAwaitingAudio=false;this.captionAwaitingAudio=false;this.stateTo('ended');
  if(path&&admitted){try{const body=new FormData();body.append('reason',reason);Promise.resolve(this.request(path+'/end',{method:'POST',body,keepalive:true,timeoutMs:8000})).catch(()=>{});}catch{}}
 }
}
