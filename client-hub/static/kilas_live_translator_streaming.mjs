import {TranslatorSession} from './kilas_live_translator_engine.mjs?v=clauses-20261022';
import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
const problem=()=>Object.assign(Error(t('Input dan audio tertinggal. Sesi dijeda; ucapan tidak diulang otomatis.')),{code:'clause_backpressure'});
// Capture and output have independent lifetimes. A supplier lease is finite;
// renewing it never closes the physical microphone or replays source bytes.
export class StreamingTranslatorSession extends TranslatorSession {
 constructor(options){super(options);this.streaming=true;this.lease=null;this.buffer=[];this.bufferBytes=0;}
 async listen(ticket,held=false){
  if(this.capture.supportsDuplex===false)this.streaming=false;
  if(this.inputMode!=='realtime-v1'||!this.streaming)return super.listen(ticket,held);
  if(ticket!==this.version)return;
  if(!this.running){this.held=false;this.stateTo('ready');return;}
  this.held=true;this.buffer=[];this.bufferBytes=0;this.lastVoice=null;this.lease=null;
  const cycle=++this.captureVersion,current=()=>ticket===this.version&&cycle===this.captureVersion;
  this.api.input.reset();this.api.input.clauses=true;this.stateTo('opening');
  try{
   await this.startup(ticket,'microphone_start',()=>this.capture.start({inputMode:this.inputMode,duplex:true,
    ready:()=>{if(current())this.stateTo('listening');},
    pcm:(bytes,meta)=>{if(current())this.accept(bytes,meta?.rms??0,ticket);},
    level:()=>{},blob:()=>{if(current()){this.stopping=false;this.finishInput(ticket);}},
    error:error=>{if(current())this.pause(error);}
   }),45000,t('Mikrofon belum siap. Periksa izin mikrofon lalu tekan Lanjutkan.'));
  }catch(error){
   // Only a pre-dispatch capability failure may use the existing turn fallback.
   if(current()&&error.code==='duplex_unavailable'&&!this.pendingKey){
    this.streaming=false;this.api.input.clauses=false;this.capture.cancel();return super.listen(ticket,held);
   }
   throw error;
  }
 }
 accept(bytes,rms,ticket){
  if(ticket!==this.version||(!this.held&&!this.stopping))return;
  if(this.stopping&&(!this.lease||this.lease.finishing))return;
  const voiced=rms>=.015;
  if(voiced)this.lastVoice=this.now();
  if(!this.lease){
   if(!voiced&&!this.buffer.length)return; // No paid silence connection.
   const key='live-'+this.key();this.pendingKey=key;
   this.lease={key,bytes:0,finishing:false,index:0,playing:false};
  }
  const lease=this.lease;
  if(lease.finishing){
   if(this.bufferBytes+bytes.byteLength>8*32000){this.pause(problem());return;}
   this.buffer.push({bytes:bytes.slice(),rms});this.bufferBytes+=bytes.byteLength;return;
  }
  lease.bytes+=bytes.byteLength;
  const pushed=this.api.input.push(this.id,lease.key,bytes,this.controller.signal);
  pushed.catch(error=>{if(ticket===this.version)this.pause(error);});
  if(!lease.polling){lease.polling=true;pushed.then(()=>this.poll(lease,ticket)).catch(()=>{});}
  // Lease rotation is below existing 180s input limit; capture stays alive.
  // Short pauses commit phrases on the relay, not the supplier session. Close
  // genuinely idle input after 10s to bound paid silence; Stop closes at once.
  if(lease.bytes>=120*32000||(!voiced&&this.lastVoice!==null&&this.now()-this.lastVoice>=10000))this.finishInput(ticket);
 }
 async finishInput(ticket){
  const lease=this.lease;
  if(!lease){if(!this.running&&ticket===this.version)this.stateTo('ready');return;}
  if(lease.finishing)return;
  lease.finishing=true;
  try{await this.api.input.finish(this.id,lease.key,this.controller.signal);}
  catch(error){if(ticket===this.version)this.pause(error);}
 }
 async poll(lease,ticket){
  try{
   while(ticket===this.version&&!this.controller.signal.aborted&&this.lease===lease){
    const state=await this.api.clauses.read(this.id,lease.key,this.controller.signal);
    if(!Array.isArray(state.clauses)||state.clauses.length>2)throw problem();
    const next=state.clauses.find(item=>item.index===lease.index);
    if(next&&!lease.playing){
     if(!/^live-[a-f0-9]{32}$/.test(next.key))throw problem();
     lease.playing=true;
     // Do not await playback here: read heartbeats and input keep running.
     this.playClause(lease,next,ticket).catch(error=>{if(ticket===this.version)this.pause(error);});
    }
    if(state.status==='COMPLETED'&&!state.clauses.length&&!lease.playing){
     this.pendingKey=null;this.lease=null;this.api.input.reset();
     if(!this.running){this.buffer=[];this.bufferBytes=0;this.stateTo('ready');return;}
     const queued=this.buffer;this.buffer=[];this.bufferBytes=0;
     for(const frame of queued){if(ticket!==this.version)return;this.accept(frame.bytes,frame.rms,ticket);}
     return;
    }
    if(!['PROCESSING','COMPLETED'].includes(state.status))throw problem();
    await this.waitPoll(this.controller.signal);
   }
  }catch(error){if(ticket===this.version&&!this.controller.signal.aborted)this.pause(error);}
 }
 waitPoll(signal){return new Promise(resolve=>{
  let timer;const done=()=>{this.clear(timer);signal.removeEventListener('abort',done);resolve();};
  timer=this.schedule(done,250);signal.addEventListener('abort',done,{once:true});if(signal.aborted)done();
 });}
 async playClause(lease,item,ticket){
  const current=()=>ticket===this.version&&!this.controller.signal.aborted;
  const result=await this.api.turn(this.id,item.key,null,this.controller.signal,null,null,
   part=>{if(current())this.onResult(part);},
   this.playback.progressive?async(url,signal)=>this.playback.progressive(url,signal,current):null);
  if(!current())return;
  if(result.playbackError)throw result.playbackError;
  if(!result.streamed)await this.playback.play(result.audio_url,this.controller.signal,current);
  if(!current())return;
  this.onResult(result);
  await this.api.clauses.ack(this.id,lease.key,item.index,this.controller.signal);
  if(!current())return;
  lease.index++;lease.playing=false;
 }
 release(options={}){
  if(this.inputMode!=='realtime-v1'||!this.streaming)return super.release(options);
  // Never silently discard captured speech waiting for a lease rollover.
  // Stop cannot admit another supplier lease; report the unsent backlog instead.
  if(this.bufferBytes){this.pause(problem());return;}
  this.running=false;this.held=false;this.buffer=[];this.bufferBytes=0;
  if(options.cancel){this.pause(Object.assign(Error(''),{code:'capture_cancelled'}));return;}
  if(this.state==='opening'){++this.captureVersion;this.capture.cancel();this.stateTo('ready');return;}
  this.stateTo(this.lease?'processing':'ready');
  // Final worklet bytes were admitted before Stop; finish the existing lease.
  this.stopping=true;this.capture.finalize();
 }
 pause(error){if(this.streaming&&this.id&&this.pendingKey){try{Promise.resolve(this.api.clauses.cancel(this.id,this.pendingKey)).catch(()=>{});}catch{}}this.stopping=false;this.buffer=[];this.bufferBytes=0;super.pause(error);}
 end(){this.stopping=false;this.buffer=[];this.bufferBytes=0;this.lease=null;super.end();}
}
