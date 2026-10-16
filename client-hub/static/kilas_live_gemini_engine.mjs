// One owned native stream. No fallback, paid retry, default switch or media on import.
import {GeminiPlayer} from './kilas_live_gemini_player.mjs?v=gemini-isolated-v1';
export {GeminiPlayer};
const abort=()=>new DOMException('Aborted','AbortError');
export class GeminiSession {
 constructor({json,capture,player,prepare,csrf,endOwned=null,onIdle=()=>{},key=()=>crypto.randomUUID().replaceAll('-',''),onState=()=>{},onText=()=>{},onError=()=>{},onTiming=()=>{},now=()=>performance.now(),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id)}){
  Object.assign(this,{json,capture,player,prepare,csrf,endOwned,onIdle,key,onState,onText,onError,onTiming,now,schedule,clear});this.version=0;this.id=null;this.active=false;this.admissionPending=false;
 }
 state(value){try{this.onState(value);}catch{}}
 form(values={}){const data=new FormData();data.set('csrf_token',this.csrf);for(const [key,value] of Object.entries(values))data.set(key,String(value));return data;}
 path(){return '/kilas-translator/live/gemini/sessions/'+encodeURIComponent(this.id)+'/turns/'+this.operation;}
 current(ticket){if(ticket!==this.version||this.controller.signal.aborted)throw abort();}
 async start(form){
  if(this.active||this.admissionPending)return;const ticket=++this.version;this.active=true;this.controller=new AbortController();this.state('starting');
  try{
   await this.prepare(this.controller.signal,()=>ticket===this.version);this.current(ticket);
   this.admissionPending=true;let result;
   try{result=await this.json('/kilas-translator/live/gemini/sessions',{method:'POST',body:form,signal:this.controller.signal,timeoutMs:15000});}finally{this.admissionPending=false;}
   if(!/^[a-f0-9]{48}$/.test(result?.session_id)||result.input_mode!=='gemini-live-v1')throw Error('gemini_session_invalid');
   if(ticket!==this.version){this.closeRemote(result.session_id);return;}
   this.id=result.session_id;this.operation='live-'+this.key();this.index=0;this.cursor=0;this.totalBytes=0;this.queuedBytes=0;this.pending=new Uint8Array(16000);this.pendingLength=0;this.begun=false;this.finishing=false;this.generation=0;this.firstInputAt=null;this.outputSeen=false;this.player.reset();
   await this.capture.start({ready:()=>{if(ticket===this.version)this.state('listening');},level:()=>{},
    pcm:bytes=>{try{this.current(ticket);this.push(bytes,ticket);}catch(error){this.fail(error,ticket);}},
    blob:()=>{this.finishInput(ticket).catch(error=>this.fail(error,ticket));},
    error:error=>this.fail(error,ticket)});this.current(ticket);
   this.state('listening');
  }catch(error){this.fail(error,ticket);}
 }
 push(bytes,ticket){
  if(this.finishing||!(bytes instanceof Uint8Array)||!bytes.byteLength||bytes.byteLength%2||bytes.byteLength>6400)throw Error('gemini_input_invalid');
  if(this.queuedBytes+bytes.byteLength>8*32000||this.totalBytes+bytes.byteLength>60*32000)throw Error('gemini_backlog');
  this.totalBytes+=bytes.byteLength;this.queuedBytes+=bytes.byteLength;
  if(!this.begun){
   this.begun=true;this.firstInputAt=this.now();
   this.chain=this.json(this.path(),{method:'POST',body:this.form(),signal:this.controller.signal,timeoutMs:15000}).then(result=>{
    this.current(ticket);if(result.input_mode!=='gemini-live-v1')throw Error('gemini_protocol');
    this.poll(ticket).catch(error=>this.fail(error,ticket));
   });
   this.timer=this.schedule(()=>this.finish(),59000); // Leave room for pre-roll/worklet flush inside 60s input cap.
   this.queue(bytes.slice(),ticket);return;
  }
  let offset=0;
  while(offset<bytes.length){const size=Math.min(bytes.length-offset,this.pending.length-this.pendingLength);this.pending.set(bytes.subarray(offset,offset+size),this.pendingLength);offset+=size;this.pendingLength+=size;if(this.pendingLength===this.pending.length)this.flush(ticket);}
 }
 queue(bytes,ticket){
  const index=this.index++;
  this.chain=this.chain.then(async()=>{
   this.current(ticket);const data=this.form();data.append('pcm',new Blob([bytes],{type:'application/octet-stream'}),'pcm');
   const result=await this.json(this.path()+'/chunks/'+index,{method:'POST',body:data,signal:this.controller.signal,timeoutMs:10000});
   this.current(ticket);if(result.accepted_index!==index)throw Error('gemini_input_invalid');
  }).finally(()=>{this.queuedBytes-=bytes.byteLength;});
  this.chain.catch(error=>this.fail(error,ticket));
 }
 flush(ticket){if(this.pendingLength){const bytes=this.pending.slice(0,this.pendingLength);this.pendingLength=0;this.queue(bytes,ticket);}}
 finish(){if(!this.active||this.finishing)return;this.capture.finalize();}
 async finishInput(ticket){
  this.current(ticket);if(this.finishing)return;this.finishing=true;this.clear(this.timer);
  if(!this.begun){await this.end();return;}
  this.flush(ticket);this.state('draining');await this.chain;this.current(ticket);
  await this.json(this.path()+'/finish',{method:'POST',body:this.form({count:this.index}),signal:this.controller.signal,timeoutMs:10000});
 }
 async poll(ticket){
  while(this.active){
   if(this.firstInputAt!==null&&this.now()-this.firstInputAt>=105000)throw Error('gemini_deadline');
   this.current(ticket);const result=await this.json(this.path()+'?after='+this.cursor,{signal:this.controller.signal,timeoutMs:10000});this.current(ticket);
   if(!Array.isArray(result.frames)||result.frames.length>12||result.next_index!==this.cursor+result.frames.length)throw Error('gemini_output_invalid');
   if(result.status==='FAILED'||result.status==='CANCELLED')throw Object.assign(Error(result.code||'gemini_transport'),{code:result.code});
   for(const frame of result.frames){
    if(frame.index!==this.cursor||!Number.isInteger(frame.generation)||frame.generation<0)throw Error('gemini_output_invalid');
    if(frame.type==='reset'){
     if(frame.generation!==this.generation+1)throw Error('gemini_output_invalid');this.generation=frame.generation;this.player.cancel();
    }else if(frame.type==='audio'&&frame.generation===this.generation&&typeof frame.pcm==='string'&&frame.pcm.length<=12800){
     const raw=Uint8Array.from(atob(frame.pcm),ch=>ch.charCodeAt(0));this.player.push(raw);
     if(!this.outputSeen){this.outputSeen=true;try{this.onTiming({first_pcm_received_ms:Math.max(0,this.now()-this.firstInputAt)});}catch{}}
    }else throw Error('gemini_output_invalid');
    this.cursor++;
   }
   if(typeof result.translated_text!=='string'||result.translated_text.length>4000)throw Error('gemini_output_invalid');
   this.onText(result.translated_text);
   if(result.output_closed){
    if(result.status!=='COMPLETED'||!Number.isInteger(result.total_frames)||result.total_frames<this.cursor)throw Error('gemini_tail_incomplete');
    if(this.cursor===result.total_frames){await this.player.drain();this.current(ticket);await this.end();return;}
   }
   await new Promise((resolve,reject)=>{const timer=this.schedule(()=>{this.controller.signal.removeEventListener('abort',cancel);resolve();},200);const cancel=()=>{this.clear(timer);reject(abort());};this.controller.signal.addEventListener('abort',cancel,{once:true});});
  }
 }
 closeRemote(id){if(this.endOwned)return this.endOwned(id);return this.json('/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/end',{method:'POST',body:this.form(),keepalive:true,timeoutMs:10000}).catch(()=>{});}
 fail(error,ticket){if(ticket!==this.version||error?.name==='AbortError')return;try{this.onError(error);}finally{this.end();}}
 async end(){
  const id=this.id;this.id=null;this.active=false;this.version++;this.controller?.abort();this.clear(this.timer);
  try{this.capture.cancel();}catch{}try{this.player.cancel();}catch{}this.state('ended');
  if(id)await this.closeRemote(id);else this.onIdle();
 }
}
