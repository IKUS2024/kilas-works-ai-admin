// One owned logical session; bounded native turns are admitted serially, never retried.
import {GeminiPlayer} from './kilas_live_gemini_player.mjs?v=native-progressive-20261016';
export {GeminiPlayer};
const abort=()=>new DOMException('Aborted','AbortError');
const failure=code=>Object.assign(Error(code),{code});
const INPUT_BYTES=59*32000,QUEUE_BYTES=8*32000;
const OUTPUT_BYTES=90*48000;
export class GeminiSession {
 constructor({json,capture,player,prepare,csrf,endOwned=null,onIdle=()=>{},onAdmissionChange=()=>{},key=()=>crypto.randomUUID().replaceAll('-',''),onState=()=>{},onText=()=>{},onError=()=>{},onWarning=()=>{},onTiming=()=>{},utterancePlayback=false,waitForOutputBeforeFinish=false,endpointMs=2000,packetBytes=16000,readRetries=0,isEcho=()=>false,now=()=>performance.now(),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id)}){
  Object.assign(this,{json,capture,player,prepare,csrf,endOwned,onIdle,onAdmissionChange,key,onState,onText,onError,onWarning,onTiming,utterancePlayback,waitForOutputBeforeFinish,isEcho,now,schedule,clear});this.endpointSamples=Math.max(600,Math.min(2000,endpointMs))*16;this.packetBytes=packetBytes===3200?3200:16000;this.readRetries=Math.max(0,Math.min(2,readRetries));this.version=0;this.id=null;this.active=false;this.admissionPending=false;
 }
 get firstInputAt(){return this.turn?.firstInputAt??null;}
 get cursor(){return this.turn?.cursor??0;}
 get queuedBytes(){return (this.turn?.queuedBytes||0)+(this.carryBytes||0);}
 get queuedOutputBytes(){return (this.outputQueue||[]).reduce((total,entry)=>total+entry.raw.length,0)+(this.player.pendingSamples||0)*2+(this.turn?.output||[]).reduce((total,entry)=>total+entry.raw.length,0);}
 state(value){try{this.onState(value);}catch{}}
 form(values={}){const data=new FormData();data.set('csrf_token',this.csrf);for(const [key,value] of Object.entries(values))data.set(key,String(value));return data;}
 path(turn=this.turn){return '/kilas-translator/live/gemini/sessions/'+encodeURIComponent(this.id)+'/turns/'+turn.operation;}
 current(ticket,turn=null){if(ticket!==this.version||!this.active||this.controller?.signal.aborted||(turn&&turn!==this.turn))throw abort();}
 protocol(result){
  if(result?.input_mode!==this.inputMode)throw failure('gemini_protocol');
  if(this.twoWay&&(result.translation_mode!=='two_way'||!Array.isArray(result.streams)||result.streams.length!==2||new Set(result.streams).size!==2||result.streams.some(id=>!this.streamIds.includes(id))))throw failure('gemini_protocol');
  if(this.twoWay&&((this.progressive||result.output_order!==undefined)&&result.output_order!==this.outputOrder))throw failure('gemini_protocol');
 }
 async start(form){
  if(this.active||this.admissionPending)return;const ticket=++this.version;this.active=true;this.stopping=false;this.failureTask=null;this.outputQueue=[];this.outputTask=null;this.speech={active:false,silenceSamples:0,preRoll:[]};this.controller=new AbortController();this.state('starting');
  try{
   this.twoWay=form.get('translation_mode')==='two_way';this.progressive=this.twoWay&&form.get('output_order')==='progressive_stream_runs';
   this.inputMode=this.twoWay?(this.progressive?'gemini-live-two-way-v2':'gemini-live-two-way-v1'):'gemini-live-v1';this.outputOrder=this.progressive?'progressive_stream_runs':'stream_runs_after_close';
   this.streamIds=this.twoWay?[form.get('language_a'),form.get('language_b')]:[];
   if(this.twoWay&&(this.streamIds.some(id=>typeof id!=='string'||!id||id.length>32)||new Set(this.streamIds).size!==2))throw failure('gemini_protocol');
   await this.prepare(this.controller.signal,()=>ticket===this.version);this.current(ticket);
   this.admissionPending=true;let result;
   try{result=await this.json('/kilas-translator/live/gemini/sessions',{method:'POST',body:form,signal:this.controller.signal,timeoutMs:15000});}finally{this.admissionPending=false;try{this.onAdmissionChange();}catch{}}
   if(!/^[a-f0-9]{48}$/.test(result?.session_id))throw failure('gemini_session_invalid');
   if(ticket!==this.version){this.closeRemote(result.session_id);return;}
   this.id=result.session_id;this.protocol(result);this.turn=null;this.usedKeys=new Set();this.carry=[];this.carryBytes=0;this.stopping=false;this.player.reset();this.speech={active:false,silenceSamples:0,preRoll:[]};
   if(this.utterancePlayback)this.player.hold();
   await this.capture.start({ready:()=>{if(ticket===this.version)this.state('listening');},level:()=>{},
    pcm:bytes=>{try{if(this.failureEndpoint&&ticket===this.version){this.failureInput(bytes);return;}this.current(ticket);if(this.utterancePlayback)this.input(bytes,ticket);else this.push(bytes,ticket);}catch(error){this.fail(error,ticket);}},
    blob:()=>this.fail(failure('gemini_capture_stopped'),ticket),error:error=>this.fail(error,ticket)});this.current(ticket);
   this.state('listening');
  }catch(error){this.fail(error,ticket);}
 }
 newTurn(ticket){
  this.current(ticket);
  // At most90s can precede one admitted90s pair, bounding accepted output at
  //180s even when the speaker keeps the player held. Never reserve a new turn
  // once that prior backlog is full; its accepted PCM still drains once quiet.
  if(this.twoWay&&this.queuedOutputBytes>=OUTPUT_BYTES)throw failure('gemini_playback_backlog');
  const operation='live-'+this.key();
  if(this.usedKeys.has(operation))throw failure('gemini_operation_invalid');this.usedKeys.add(operation);
  const turn={operation,index:0,cursor:0,totalBytes:0,queuedBytes:0,pending:new Uint8Array(this.packetBytes),pendingLength:0,begun:false,finishing:false,closed:false,generation:0,firstInputAt:null,outputSeen:false};
  if(this.twoWay){turn.generations=new Map(this.streamIds.map(id=>[id,0]));turn.scopes=new Map(this.streamIds.map(id=>[id,{turn,stream_id:id}]));turn.output=[];turn.outputBytes=0;turn.seenStreams=new Set();turn.closedStreams=new Set();turn.lastStream=null;}
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
  // PCM samples drive the short phrase boundary, independent of UI timer jitter.
  // Existing clients retain their two-second boundary; the live UI uses 600ms.
  if(speech.silenceSamples>=this.endpointSamples){
   speech.active=false;speech.silenceSamples=0;
   this.state(this.player.pendingSamples?'playing':'processing');this.player.release();
   // Prefer a quiet renewal near the physical bound. A speech endpoint opens
   // playout, not a new paid connection or an unconditional stream close.
   if(this.turn&&((this.twoWay&&(!this.waitForOutputBeforeFinish||this.turn.outputSeen))||this.turn.totalBytes>=45*32000))this.finish();
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
    this.current(ticket,turn);this.protocol(result);
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
 async pause(ticket,turn,delay=200){
  this.current(ticket,turn);const signal=this.controller.signal;
  await new Promise((resolve,reject)=>{const cancel=()=>{this.clear(timer);signal.removeEventListener('abort',cancel);reject(abort());};const timer=this.schedule(()=>{signal.removeEventListener('abort',cancel);resolve();},delay);signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();});
 }
 pairSnapshot(result,turn,complete=false){
  const streams=result.streams;
  if(result.input_mode!==this.inputMode||result.translation_mode!=='two_way'||result.output_order!==this.outputOrder||!streams||Array.isArray(streams)||typeof streams!=='object'||Object.keys(streams).length!==2||Object.keys(streams).some(id=>!this.streamIds.includes(id)))throw failure('gemini_output_invalid');
  for(const id of this.streamIds){
   const stream=streams[id],generation=turn.generations.get(id);
   if(!stream||stream.target_language!==id||!Number.isInteger(stream.generation)||stream.generation<generation||typeof stream.output_closed!=='boolean'||typeof stream.tail_confirmed!=='boolean')throw failure('gemini_output_invalid');
   if(turn.closedStreams.has(id)&&!stream.output_closed)throw failure('gemini_output_invalid');
   if(stream.output_closed)turn.closedStreams.add(id);
   if(complete&&(stream.generation!==generation||!stream.output_closed||(stream.tail_confirmed&&stream.completion_kind!=='turn_complete')||(!stream.tail_confirmed&&!['bounded_drain',null].includes(stream.completion_kind))))throw failure('gemini_tail_incomplete');
  }
  if(complete&&result.tail_confirmed!==this.streamIds.every(id=>streams[id].tail_confirmed))throw failure('gemini_tail_incomplete');
 }
 queueOutput(turn){
  if(turn?.output?.length){this.outputQueue.push(...turn.output);turn.output=[];}
 }
 feedOutput(ticket){
  if(this.outputTask)return this.outputTask;
  // Player capacity is backpressure, not a failed translation. Preserve the
  // accepted raw runs and feed them in order as the audio clock frees space.
  const task=Promise.resolve().then(async()=>{
   while(this.outputQueue.length){
    if(ticket!==this.version||!this.active)throw abort();
    const entry=this.outputQueue[0];
    try{this.player.push(entry.raw,entry.scope);}
    catch(error){if(error?.message!=='gemini_playback_backlog')throw error;await this.player.checkpoint();continue;}
    this.outputQueue.shift();
   }
  });
  this.outputTask=task;
  task.then(()=>{if(this.outputTask===task){this.outputTask=null;if(this.outputQueue.length&&ticket===this.version)this.feedOutput(ticket).catch(()=>{});}},error=>{if(this.outputTask===task)this.outputTask=null;this.fail(error,ticket);});
  return task;
 }
 async readSnapshot(ticket,turn,url){
  // Read-only reconnect resumes the same cursor and paid provider session.
  // Never replay an uncertain admission, PCM POST or provider connection.
  for(let attempt=0;;attempt++){
   this.current(ticket,turn);
   try{
    const result=await this.json(url,{signal:this.controller.signal,timeoutMs:2000});
    this.current(ticket,turn);
    if(attempt)this.state(this.speech?.active?'listening':'processing');
    return result;
   }catch(error){
    this.current(ticket,turn);
    if(attempt>=this.readRetries||!(error instanceof TypeError||error?.code==='request_timeout'))throw error;
    this.state('reconnecting');await this.pause(ticket,turn,250*2**attempt);
   }
  }
 }
 async poll(ticket,turn,path){
  while(this.active){
   this.current(ticket,turn);if(this.now()-turn.firstInputAt>=90000)throw failure('gemini_deadline');
   const result=await this.readSnapshot(ticket,turn,path+'?after='+turn.cursor);this.current(ticket,turn);
   if(!Array.isArray(result.frames)||result.frames.length>12||result.next_index!==turn.cursor+result.frames.length)throw failure('gemini_output_invalid');
   if(this.twoWay){this.pairSnapshot(result,turn);if(!this.progressive&&result.frames.length&&!result.output_closed)throw failure('gemini_output_invalid');}
   // A terminal status may carry the final accepted PCM. Validate and consume it first.
   for(const frame of result.frames){
    if(frame.index!==turn.cursor||!Number.isInteger(frame.generation)||frame.generation<0)throw failure('gemini_output_invalid');
    let generation=turn.generation,scope=turn;
    if(this.twoWay){
     const id=frame.stream_id;
     if(!turn.generations.has(id)||frame.target_language!==id)throw failure('gemini_output_invalid');
     if(id!==turn.lastStream){
      if(turn.seenStreams.has(id)||(turn.lastStream&&!result.streams[turn.lastStream].output_closed))throw failure('gemini_output_invalid');
      turn.seenStreams.add(id);turn.lastStream=id;
     }
     generation=turn.generations.get(id);scope=turn.scopes.get(id);
    }
    if(frame.type==='reset'){
     if(frame.generation!==generation+1)throw failure('gemini_output_invalid');
     if(this.twoWay)turn.generations.set(frame.stream_id,frame.generation);else turn.generation=frame.generation;
     // An interpreter keeps all accepted translated PCM. New input must not
     // silently erase the sentence already waiting for the speaker to finish.
     if(!this.utterancePlayback&&!this.twoWay)this.player.interrupt?.(scope);
    }else if(frame.type==='audio'&&frame.generation===generation&&typeof frame.pcm==='string'&&frame.pcm.length<=12800){
     const raw=Uint8Array.from(atob(frame.pcm),ch=>ch.charCodeAt(0));
     if(this.twoWay){
      if(!raw.length||raw.length%2||raw.length>9600||turn.outputBytes+raw.length>OUTPUT_BYTES)throw failure('gemini_output_invalid');
      turn.outputBytes+=raw.length;turn.output.push({raw,scope});
     }else this.player.push(raw,scope);
     if(!turn.outputSeen){turn.outputSeen=true;try{this.onTiming({first_pcm_received_ms:Math.max(0,this.now()-turn.firstInputAt)});}catch{}}
    }else throw failure('gemini_output_invalid');
    turn.cursor++;
   }
   if(typeof result.translated_text!=='string'||result.translated_text.length>4000)throw failure('gemini_output_invalid');
   this.onText(result.translated_text,{operation:turn.operation,source_text:result.source_text||'',streams:this.twoWay?result.streams:null,complete:result.output_closed===true});
   // Coherent pages can play before socket closure. The local speech gate
   // keeps their accepted samples held until the speaker reaches the endpoint.
   if(this.waitForOutputBeforeFinish&&this.twoWay&&turn.outputSeen&&!this.speech.active&&!turn.finishing)this.finish();
   if(this.progressive){this.queueOutput(turn);this.feedOutput(ticket).catch(()=>{});}
   const failed=result.status==='FAILED'||result.status==='CANCELLED';
   if(failed&&!this.stopping){this.stopping=true;if(!this.utterancePlayback)this.capture.cancel();this.clear(turn.timer);this.state('draining');}
   if(result.output_closed){
    if(!['COMPLETED','FAILED','CANCELLED'].includes(result.status)||!Number.isInteger(result.total_frames)||result.total_frames<turn.cursor)throw failure('gemini_tail_incomplete');
    if(turn.cursor===result.total_frames){
     if(this.twoWay){this.pairSnapshot(result,turn,true);if(!this.progressive){this.queueOutput(turn);this.feedOutput(ticket).catch(()=>{});}}
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
     }else{
      for(const bytes of carry){this.current(ticket);this.push(bytes,ticket);}
      // A carried utterance may already have reached its endpoint while the
      // preceding pair drained. It still receives one own serial physical turn.
      if(this.twoWay&&this.turn&&!this.speech.active)this.finish();
     }
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
  if(this.speech.silenceSamples>=this.endpointSamples){this.speech.active=false;this.speech.silenceSamples=0;this.failureEndpoint?.(true);}
 }
 fail(error,ticket){
  if(ticket!==this.version||error?.name==='AbortError'||this.failureTask)return;
  // Stop requests/admission immediately and preserve accepted PCM. The opted-in
  // gate may observe local silence briefly; End/a failed player cancels now.
  this.stopping=true;this.failureTask=true;this.controller?.abort();this.clear(this.turn?.timer);
  this.queueOutput(this.turn);
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
   if(!this.player.failed){try{
    // Local speech has ended (or capture was already idle); release before a
    // capacity checkpoint, which cannot finish while its audio is held.
    this.player.release?.();
    while(this.outputQueue.length||this.outputTask){await this.feedOutput(ticket);if(ticket!==this.version)return;}
    await this.player.drain();
   }catch{}}
   if(ticket!==this.version)return;
   try{if(!waitForSpeech)this.onError(error);}catch{}finally{await this.end();}
  })();
  this.failureTask.catch(()=>{});return this.failureTask;
 }
 async end(){
  const id=this.id;this.id=null;this.active=false;this.version++;this.controller?.abort();this.clear(this.turn?.timer);this.clear(this.failureTimer);this.failureEndpoint?.(false);this.failureEndpoint=null;this.carry=[];this.carryBytes=0;this.outputQueue=[];this.outputTask=null;if(this.turn?.output)this.turn.output=[];
  try{this.capture.cancel();}catch{}try{this.player.cancel();}catch{}this.state('ended');
  if(id)await this.closeRemote(id);else this.onIdle();
 }
}
