// Injectable Call lifecycle. No microphone, provider or network work on import.
import {prepareCallPcm} from './kilas_ai_call_pcm.mjs?v=call-understanding-gain-20261017';
const aborted=()=>new DOMException('Aborted','AbortError');
const failure=code=>Object.assign(Error(code),{code});
export class CallInput {
 constructor({request,path,signal,onError=()=>{}}){
  Object.assign(this,{request,path,signal,onError});this.pending=new Uint8Array(16000);this.length=0;this.index=0;this.queued=0;this.total=0;this.epoch=0;this.firstPacket=true;
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
  if(!this.length)return;const raw=this.pending.slice(0,this.length),epoch=this.epoch;this.length=0;
  const work=this.chain.then(async()=>{
   if(this.signal.aborted)throw aborted();
   if(epoch!==this.epoch)return;
   const index=this.index++;
   const result=await this.request(this.path+'/chunks/'+index,{method:'POST',body:raw,signal:this.signal,timeoutMs:8000});
   if(result.accepted_index!==index)throw failure('call_input_invalid');
  }).finally(()=>{this.queued-=raw.length;});
  this.chain=work;work.catch(error=>{if(!this.signal.aborted)this.onError(error);});
 }
 discardPending(){
  // Turn-taking: never append a prior turn's unsent microphone tail to the
  // next question. An already dispatched request keeps its original index.
  ++this.epoch;this.queued-=this.length;this.pending.fill(0);this.length=0;this.firstPacket=true;
 }
 cancel(){this.rejectOpen(aborted());this.pending.fill(0);this.length=0;}
}

export class CallSession {
 constructor({request,capture,player,prepare=async()=>{},stopAudio=()=>{},onState=()=>{},onError=()=>{},onText=()=>{},
  key=()=>crypto.randomUUID().replaceAll('-',''),schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id)}){
  Object.assign(this,{request,capture,player,prepare,stopAudio,onState,onError,onText,key,schedule,clear});this.version=0;this.state='ended';
 }
 stateTo(value){this.state=value;this.onState(value);}
 current(ticket){return ticket===this.version&&!this.controller?.signal.aborted;}
 async start(){
  if(this.state!=='ended')return;
  const ticket=++this.version;this.controller=new AbortController();const signal=this.controller.signal;
  this.ident=this.key();this.path='/kilas-ai/call/'+this.ident;this.admitted=false;this.speaking=false;this.turnSealed=false;this.cursor=0;this.playVersion=0;
  this.stateTo('connecting');this.onText('');
  this.input=new CallInput({request:this.request,path:this.path,signal,onError:error=>this.fail(error,ticket)});
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
   const result=await this.request(this.path,{method:'POST',signal,timeoutMs:12000});
   if(!this.current(ticket))return;
   if(result.call_id!==this.ident)throw failure('call_protocol');
   this.input.open();
   await this.poll(ticket);
  }catch(error){if(this.current(ticket))this.fail(error,ticket);}
 }
 async poll(ticket){
  while(this.current(ticket)){
   const value=await this.request(this.path+'?after='+this.cursor,{signal:this.controller.signal,timeoutMs:8000});
   if(!this.current(ticket))return;
   if(!Array.isArray(value.frames)||!Number.isInteger(value.next_index)||value.next_index!==this.cursor+value.frames.length)throw failure('call_protocol');
   for(const frame of value.frames){
    if(!this.current(ticket))return;
    if(frame.index!==this.cursor++)throw failure('call_protocol');
    if(frame.type==='audio'){
     if(typeof frame.pcm!=='string'||frame.pcm.length>12800)throw failure('call_protocol');
     if(!this.speaking||this.turnSealed){this.clear(this.echoTimer);this.echoTimer=null;this.turnSealed=false;this.speaking=true;this.playVersion++;this.input.discardPending();this.onText('');}
     this.stateTo('speaking');const raw=Uint8Array.from(atob(frame.pcm),c=>c.charCodeAt(0));this.player.push(raw,'call');
    }else if(frame.type==='text'){
     if(typeof frame.text!=='string'||frame.text.length>4000)throw failure('call_protocol');this.onText(frame.text);
    }else if(frame.type==='reset'){
     this.clear(this.echoTimer);this.player.cancel();this.turnSealed=false;this.speaking=false;this.playVersion++;this.onText('');
    }else if(frame.type==='turn_complete'){
     this.turnSealed=true;const generation=this.playVersion;
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
   if(value.state==='LISTENING'&&!this.speaking)this.stateTo('listening');
   await new Promise(resolve=>{this.pollTimer=this.schedule(resolve,250);this.pollResolve=resolve;});
  }
 }
 fail(error,ticket=this.version){if(!this.current(ticket))return;this.end();this.onError(error.code||'call_transport');}
 end(){
  const path=this.path,admitted=this.admitted;this.admitted=false;this.ident=null;this.path=null;++this.version;
  this.controller?.abort();this.clear(this.timer);this.clear(this.echoTimer);this.clear(this.pollTimer);this.pollResolve?.();this.pollResolve=null;
  try{this.input?.cancel();}catch{}try{this.capture.cancel();}catch{}try{this.player.cancel();}catch{}try{this.stopAudio();}catch{}
  this.speaking=false;this.onText('');this.stateTo('ended');
  if(path&&admitted){try{Promise.resolve(this.request(path+'/end',{method:'POST',keepalive:true,timeoutMs:8000})).catch(()=>{});}catch{}}
 }
}
