// One owned logical session; bounded native turns are admitted serially, never retried.
import {GeminiPlayer} from './kilas_live_gemini_player.mjs?v=utterance-gate-20261016';
export {GeminiPlayer};
const abort=()=>new DOMException('Aborted','AbortError');
const failure=code=>Object.assign(Error(code),{code});
const INPUT_BYTES=59*32000,QUEUE_BYTES=8*32000,ENDPOINT_SAMPLES=2*16000;
export class GeminiSession {
 constructor({json,capture,player,prepare,csrf,endOwned=null,onIdle=()=>{},onAdmissionChange=()=>{},key=()=>crypto.randomUUID().replaceAll('-',''),onState=()=>{},onText=()=>{},onError=()=>{},onWarning=()=>{},onTiming=()=>{},utterancePlayback=false,isEcho=()=>false,now=()=>performance.now(),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id)}){
  Object.assign(this,{json,capture,player,prepare,csrf,endOwned,onIdle,onAdmissionChange,key,onState,onText,onError,onWarning,onTiming,utterancePlayback,isEcho,now,schedule,clear});this.version=0;this.id=null;this.active=false;this.admissionPending=false;
 }
 get firstInputAt(){return this.turn?.firstInputAt??null;}
 get cursor(){return this.turn?.cursor??0;}
 get queuedBytes(){return (this.turn?.queuedBytes||0)+(this.carryBytes||0);}
 state(value){try{this.onState(value);}catch{}}
 form(values={}){const data=new FormData();data.set('csrf_token',this.csrf);for(const [key,value] of Object.entries(values))data.set(key,String(value));return data;}
 path(turn=this.turn){return '/kilas-translator/live/gemini/sessions/'+encodeURIComponent(this.id)+'/turns/'+turn.operation;}
 current(ticket,turn=null){if(ticket!==this.version||!this.active||this.controller?.signal.aborted||(turn&&turn!==this.turn))throw abort();}
 async start(form){
  if(this.active||this.admissionPending)return;const ticket=++this.version;this.active=true;this.stopping=false;this.failureTask=null;this.speech={active:false,silenceSamples:0,preRoll:[]};this.controller=new AbortController();this.state('starting');
  try{
   await this.prepare(this.controller.signal,()=>ticket===this.version);this.current(ticket);
   this.admissionPending=true;let result;
   try{result=await this.json('/kilas-translator/live/gemini/sessions',{method:'POST',body:form,signal:this.controller.signal,timeoutMs:15000});}finally{this.admissionPending=false;try{this.onAdmissionChange();}catch{}}
   if(!/^[a-f0-9]{48}$/.test(result?.session_id)||result.input_mode!=='gemini-live-v1')throw failure('gemini_session_invalid');
   if(ticket!==this.version){this.closeRemote(result.session_id);return;}
   this.id=result.session_id;this.turn=null;this.usedKeys=new Set();this.carry=[];this.carryBytes=0;this.stopping=false;this.player.reset();this.speech={active:false,silenceSamples:0,preRoll:[]};
   if(this.utterancePlayback)this.player.hold();
   await this.capture.start({ready:()=>{if(ticket===this.version)this.state('listening');},level:()=>{},
    pcm:bytes=>{try{if(this.failureEndpoint&&ticket===this.version){this.failureInput(bytes);return;}this.current(ticket);if(this.utterancePlayback)this.input(bytes,ticket);else this.push(bytes,ticket);}catch(error){this.fail(error,ticket);}},
    blob:()=>this.fail(failure('gemini_capture_stopped'),ticket),error:error=>this.fail(error,ticket)});this.current(ticket);
   this.state('listening');
  }catch(error){this.fail(error,ticket);}
 }
 newTurn(ticket){
  this.current(ticket);const operation='live-'+this.key();
  if(this.usedKeys.has(operation))throw failure('gemini_operation_invalid');this.usedKeys.add(operation);
  const turn={operation,index:0,cursor:0,totalBytes:0,queuedBytes:0,pending:new Uint8Array(16000),pendingLength:0,begun:false,finishing:false,closed:false,generation:0,firstInputAt:null,outputSeen:false};
  this.turn=turn;return turn;
 }
 input(bytes,ticket){
  this.current(ticket);if(this.stopping){this.failureInput(bytes);return;}
  if(!(bytes instanceof Uint8Array)||!bytes.byteLength||bytes.byteLength%2||bytes.byteLength>6400)throw failure('gemini_input_invalid');
  const echo=this.isEcho(bytes),raw=echo?new Uint8Array(bytes.length):bytes;
  let energy=0;const view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);
  for(let i=0;i<raw.length;i+=2)energy+=(view.getInt16(i,true)/32768)**2;
  const voice=Math.sqrt(energy/(raw.length/2))>=.015,speech=this.speech;
  if(!speech.active){
   if(!voice){
    // Keep the current paid stream alive during pauses, but never open a new
    // reservation for standby silence or recognizable playback echo.
    if(this.turn&&!this.turn.finishing){this.push(raw,ticket);if(this.turn.totalBytes>=45*32000)this.finish();}
    else{speech.preRoll.push(raw.slice());while(speech.preRoll.length>1&&speech.preRoll.reduce((total,value)=>total+value.length,0)>12800)speech.preRoll.shift();}
    return;
   }
   speech.active=true;speech.silenceSamples=0;this.player.hold();this.state('listening');
   for(const previous of speech.preRoll)this.push(previous,ticket);speech.preRoll=[];
  }
  this.push(raw,ticket);
  speech.silenceSamples=voice?0:speech.silenceSamples+raw.length/2;
  // PCM samples drive the endpoint, so brief intra-sentence pauses and a slow
  // UI clock cannot release audio early. Native100ms frames resolve at2s.
  if(speech.silenceSamples>=ENDPOINT_SAMPLES){
   speech.active=false;speech.silenceSamples=0;
   this.state(this.player.pendingSamples?'playing':'processing');this.player.release();
   // Prefer a quiet renewal near the physical bound. A speech endpoint opens
   // playout, not a new paid connection or an unconditional stream close.
   if(this.turn&&this.turn.totalBytes>=45*32000)this.finish();
  }
 }
 push(bytes,ticket){
  this.current(ticket);if(this.stopping)return;
  if(!(bytes instanceof Uint8Array)||!bytes.byteLength||bytes.byteLength%2||bytes.byteLength>6400)throw failure('gemini_input_invalid');
  if(this.queuedBytes+bytes.byteLength>QUEUE_BYTES)throw failure('gemini_backlog');
  const turn=this.turn||this.newTurn(ticket);
  if(turn.finishing||turn.closed){this.carry.push(bytes.slice());this.carryBytes+=bytes.byteLength;return;}
  const length=Math.min(bytes.byteLength,INPUT_BYTES-turn.totalBytes);
  if(length)this.append(bytes.subarray(0,length),ticket,turn);
  if(turn.totalBytes===INPUT_BYTES)this.finishInput(ticket,turn).catch(error=>{if(!this.stopping)this.fail(error,ticket);});
  if(length<bytes.byteLength){const carry=bytes.slice(length);this.carry.push(carry);this.carryBytes+=carry.byteLength;}
 }
 append(bytes,ticket,turn){
  turn.totalBytes+=bytes.byteLength;turn.queuedBytes+=bytes.byteLength;
  if(!turn.begun){
   turn.begun=true;turn.firstInputAt=this.now();const path=this.path(turn);
   // Server reserves each physical turn before connecting its provider socket.
   turn.chain=this.json(path,{method:'POST',body:this.form(),signal:this.controller.signal,timeoutMs:15000}).then(result=>{
    this.current(ticket,turn);if(result.input_mode!=='gemini-live-v1')throw failure('gemini_protocol');
    this.poll(ticket,turn,path).catch(error=>this.fail(error,ticket));
   });
   turn.timer=this.schedule(()=>this.finishInput(ticket,turn).catch(error=>{if(!this.stopping)this.fail(error,ticket);}),59000);
   this.queue(bytes.slice(),ticket,turn,path);return;
  }
  let offset=0;
  while(offset<bytes.length){const size=Math.min(bytes.length-offset,turn.pending.length-turn.pendingLength);turn.pending.set(bytes.subarray(offset,offset+size),turn.pendingLength);offset+=size;turn.pendingLength+=size;if(turn.pendingLength===turn.pending.length)this.flush(ticket,turn);}
 }
 queue(bytes,ticket,turn,path=this.path(turn)){
  const index=turn.index++;
  turn.chain=turn.chain.then(async()=>{
   this.current(ticket,turn);if(this.stopping)throw abort();const data=this.form();data.append('pcm',new Blob([bytes],{type:'application/octet-stream'}),'pcm');
   const result=await this.json(path+'/chunks/'+index,{method:'POST',body:data,signal:this.controller.signal,timeoutMs:10000});
   this.current(ticket,turn);if(result.accepted_index!==index)throw failure('gemini_input_invalid');
  }).finally(()=>{turn.queuedBytes-=bytes.byteLength;});
  turn.chain.catch(error=>{if(!this.stopping)this.fail(error,ticket);});
 }
 flush(ticket,turn){if(turn.pendingLength){const bytes=turn.pending.slice(0,turn.pendingLength);turn.pendingLength=0;this.queue(bytes,ticket,turn);}}
 finish(){if(this.active&&!this.stopping&&this.turn){const ticket=this.version;this.finishInput(ticket,this.turn).catch(error=>{if(!this.stopping)this.fail(error,ticket);});}}
 async finishInput(ticket,turn=this.turn){
  this.current(ticket,turn);if(!turn||turn.finishing||turn.closed||this.stopping)return;turn.finishing=true;this.clear(turn.timer);
  // Keep the same capture/worklet alive: its partial PCM belongs to the next turn.
  this.flush(ticket,turn);this.state(this.utterancePlayback?(this.speech.active?'listening':this.player.pendingSamples?'playing':'processing'):'renewing');await turn.chain;this.current(ticket,turn);if(this.stopping)throw abort();
  await this.json(this.path(turn)+'/finish',{method:'POST',body:this.form({count:turn.index}),signal:this.controller.signal,timeoutMs:10000});this.current(ticket,turn);
 }
 async pause(ticket,turn){
  this.current(ticket,turn);const signal=this.controller.signal;
  await new Promise((resolve,reject)=>{const cancel=()=>{this.clear(timer);signal.removeEventListener('abort',cancel);reject(abort());};const timer=this.schedule(()=>{signal.removeEventListener('abort',cancel);resolve();},200);signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();});
 }
 async poll(ticket,turn,path){
  while(this.active){
   this.current(ticket,turn);if(this.now()-turn.firstInputAt>=90000)throw failure('gemini_deadline');
   const result=await this.json(path+'?after='+turn.cursor,{signal:this.controller.signal,timeoutMs:10000});this.current(ticket,turn);
   if(!Array.isArray(result.frames)||result.frames.length>12||result.next_index!==turn.cursor+result.frames.length)throw failure('gemini_output_invalid');
   // A terminal status may carry the final accepted PCM. Validate and consume it first.
   for(const frame of result.frames){
    if(frame.index!==turn.cursor||!Number.isInteger(frame.generation)||frame.generation<0)throw failure('gemini_output_invalid');
    if(frame.type==='reset'){
     if(frame.generation!==turn.generation+1)throw failure('gemini_output_invalid');turn.generation=frame.generation;
     // An interpreter keeps all accepted translated PCM. New input must not
     // silently erase the sentence already waiting for the speaker to finish.
     if(!this.utterancePlayback)this.player.interrupt?.(turn);
    }else if(frame.type==='audio'&&frame.generation===turn.generation&&typeof frame.pcm==='string'&&frame.pcm.length<=12800){
     const raw=Uint8Array.from(atob(frame.pcm),ch=>ch.charCodeAt(0));this.player.push(raw,turn);
     if(!turn.outputSeen){turn.outputSeen=true;try{this.onTiming({first_pcm_received_ms:Math.max(0,this.now()-turn.firstInputAt)});}catch{}}
    }else throw failure('gemini_output_invalid');
    turn.cursor++;
   }
   if(typeof result.translated_text!=='string'||result.translated_text.length>4000)throw failure('gemini_output_invalid');
   this.onText(result.translated_text);
   const failed=result.status==='FAILED'||result.status==='CANCELLED';
   if(failed&&!this.stopping){this.stopping=true;if(!this.utterancePlayback)this.capture.cancel();this.clear(turn.timer);this.state('draining');}
   if(result.output_closed){
    if(!['COMPLETED','FAILED','CANCELLED'].includes(result.status)||!Number.isInteger(result.total_frames)||result.total_frames<turn.cursor)throw failure('gemini_tail_incomplete');
    if(turn.cursor===result.total_frames){
     turn.closed=true;this.clear(turn.timer);
     if(failed){this.fail(failure(result.code||'gemini_transport'),ticket);return;}
     if(!turn.finishing||typeof result.tail_confirmed!=='boolean'||!['turn_complete','bounded_drain'].includes(result.completion_kind)||(result.tail_confirmed!==(result.completion_kind==='turn_complete')))throw failure('gemini_tail_incomplete');
     if(!result.tail_confirmed){try{this.onWarning({code:result.tail_code||'gemini_tail_unconfirmed',completion_kind:result.completion_kind,tail_confirmed:false});}catch{}}
     this.current(ticket,turn);
     // Old provider output is closed and fully cursor-consumed. Keep its accepted
     // PCM scheduled on the same player while the next reserved turn opens.
     this.turn=null;const carry=this.carry;this.carry=[];this.carryBytes=0;this.state(this.utterancePlayback&&!this.speech.active&&this.player.pendingSamples?'playing':'listening');
     const voicedCarry=carry.some(bytes=>{let energy=0;const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);for(let i=0;i<bytes.length;i+=2)energy+=(view.getInt16(i,true)/32768)**2;return Math.sqrt(energy/(bytes.length/2))>=.015;});
     if(this.utterancePlayback&&!voicedCarry){
      for(const bytes of carry){this.speech.preRoll.push(bytes);while(this.speech.preRoll.length>1&&this.speech.preRoll.reduce((total,value)=>total+value.length,0)>12800)this.speech.preRoll.shift();}
     }else for(const bytes of carry){this.current(ticket);this.push(bytes,ticket);}
     return;
    }
   }
   await this.pause(ticket,turn);
  }
 }
 closeRemote(id){if(this.endOwned)return this.endOwned(id);return this.json('/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/end',{method:'POST',body:this.form(),keepalive:true,timeoutMs:10000}).catch(()=>{});}
 failureInput(bytes){
  if(!(bytes instanceof Uint8Array)||!bytes.length||bytes.length%2||bytes.length>6400)return;
  let energy=0;const echo=this.isEcho(bytes),view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  if(!echo)for(let i=0;i<bytes.length;i+=2)energy+=(view.getInt16(i,true)/32768)**2;
  const voice=Math.sqrt(energy/(bytes.length/2))>=.015;
  if(voice){this.speech.active=true;this.speech.silenceSamples=0;this.player.hold();}
  else if(this.speech.active)this.speech.silenceSamples+=bytes.length/2;
  if(this.speech.silenceSamples>=ENDPOINT_SAMPLES){this.speech.active=false;this.speech.silenceSamples=0;this.failureEndpoint?.(true);}
 }
 fail(error,ticket){
  if(ticket!==this.version||error?.name==='AbortError'||this.failureTask)return;
  // Stop requests/admission immediately and preserve accepted PCM. The opted-in
  // gate may observe local silence briefly; End/a failed player cancels now.
  this.stopping=true;this.failureTask=true;this.controller?.abort();this.clear(this.turn?.timer);
  const waitForSpeech=this.utterancePlayback&&this.speech?.active&&!this.player.failed;
  if(!waitForSpeech){try{this.capture.cancel();}catch{}}this.state('draining');
  this.failureTask=(async()=>{
   if(waitForSpeech){
    // Failed network work cannot trigger translated speech over a speaker.
    // Observe only local silence for a bounded interval; never dispatch again.
    try{this.onError(error);}catch{}
    const quiet=await new Promise(resolve=>{this.failureEndpoint=resolve;this.failureTimer=this.schedule(()=>resolve(false),10000);});
    this.failureEndpoint=null;this.clear(this.failureTimer);this.failureTimer=null;
    if(ticket!==this.version)return;
    try{this.capture.cancel();}catch{}
    if(!quiet){await this.end();return;}
   }
   if(!this.player.failed){try{await this.player.drain();}catch{}}
   if(ticket!==this.version)return;
   try{if(!waitForSpeech)this.onError(error);}catch{}finally{await this.end();}
  })();
  this.failureTask.catch(()=>{});return this.failureTask;
 }
 async end(){
  const id=this.id;this.id=null;this.active=false;this.version++;this.controller?.abort();this.clear(this.turn?.timer);this.clear(this.failureTimer);this.failureEndpoint?.(false);this.failureEndpoint=null;this.carry=[];this.carryBytes=0;
  try{this.capture.cancel();}catch{}try{this.player.cancel();}catch{}this.state('ended');
  if(id)await this.closeRemote(id);else this.onIdle();
 }
}
