// Bounded PCM24k mono queue. No provider, network or microphone work on import.
export class GeminiPlayer {
 constructor({getContext,now=()=>performance.now(),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id),onError=()=>{},onStarted=()=>{},onTiming=()=>{}}){
  Object.assign(this,{getContext,now,schedule,clear,onError,onStarted,onTiming});this.version=0;this.reset();
 }
 reset(){
  this.version++;this.clear?.(this.timer);this.timer=null;
  for(const node of this.nodes||[]){node.onended=null;try{node.stop();node.disconnect();}catch{}}
  this.nodes=new Set();this.ends=new Map();this.queue=[];this.pendingSamples=0;this.nextAt=0;this.closed=false;
  this.lastClock=null;this.lastProgress=this.now();this.waiters=[];this.failed=null;this.first=true;
 }
 cancel(){const waiters=this.waiters;this.reset();for(const waiter of waiters||[])waiter.reject(new DOMException('Aborted','AbortError'));}
 fail(code){
  if(this.failed)return;const error=Object.assign(Error(code),{code});this.failed=error;
  const waiters=this.waiters;this.waiters=[];this.clear(this.timer);this.timer=null;
  for(const node of this.nodes){node.onended=null;try{node.stop();node.disconnect();}catch{}}
  this.nodes.clear();this.queue=[];this.pendingSamples=0;
  for(const waiter of waiters)waiter.reject(error);this.onError(error);
 }
 push(raw){
  if(this.closed||this.failed)throw this.failed||Error('gemini_player_closed');
  if(!(raw instanceof Uint8Array)||!raw.byteLength||raw.byteLength%2||raw.byteLength>9600)throw Error('gemini_pcm_invalid');
  const context=this.getContext();if(!context||context.state!=='running')throw Error('audio_context');
  const samples=raw.byteLength/2;
  if(this.pendingSamples+samples>8*24000)throw Error('gemini_playback_backlog');
  const buffer=context.createBuffer(1,samples,24000),channel=buffer.getChannelData(0),view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);
  for(let i=0;i<samples;i++)channel[i]=view.getInt16(i*2,true)/32768;
  this.queue.push(buffer);this.pendingSamples+=samples;
  if(this.first&&this.pendingSamples<.3*24000){
   if(this.timer===null)this.timer=this.schedule(()=>{this.timer=null;this.pump();},300);
  }else this.pump();
 }
 pump(){
  if(this.failed)return;this.clear(this.timer);this.timer=null;
  const context=this.getContext();if(!context||context.state!=='running'){this.fail('audio_stalled');return;}
  const ticket=this.version;
  while(this.queue.length){
   const buffer=this.queue.shift(),node=context.createBufferSource();node.buffer=buffer;node.connect(context.destination);
   const at=Math.max(context.currentTime+.02,this.nextAt);
   if(!this.first){try{this.onTiming({schedule_gap_ms:Math.max(0,(at-this.nextAt)*1000)});}catch{}}
   this.nextAt=at+buffer.duration;
   this.nodes.add(node);this.ends.set(node,at+buffer.duration);node.onended=()=>{
    if(ticket!==this.version||this.failed)return;
    if(context.currentTime+.05<at+buffer.duration){this.fail('audio_stalled');return;}
    if(!this.nodes.delete(node))return;this.ends.delete(node);this.pendingSamples-=buffer.length;try{node.disconnect();}catch{}this.complete();
   };
   try{node.start(at);}catch{this.fail('audio_start');return;}
   if(this.first){this.first=false;this.onStarted();}
  }
  if(this.nodes.size){if(this.lastClock===null){this.lastClock=context.currentTime;this.lastProgress=this.now();}this.watch(ticket);}
  this.complete();
 }
 watch(ticket){
  this.clear(this.timer);this.timer=this.schedule(()=>{
   this.timer=null;if(ticket!==this.version||this.failed)return;
   const context=this.getContext();
   if(!context||context.state!=='running'){this.fail('audio_stalled');return;}
   if(context.currentTime>this.lastClock){this.lastClock=context.currentTime;this.lastProgress=this.now();}
   if(this.now()-this.lastProgress>=5000){this.fail('audio_stalled');return;}
   for(const [node,end] of this.ends)if(context.currentTime>=end+.25)node.onended?.();
   if(this.nodes.size)this.watch(ticket);this.complete();
  },250);
 }
 complete(){
  if(this.closed&&!this.nodes.size&&!this.queue.length&&!this.failed){
   this.clear(this.timer);this.timer=null;for(const waiter of this.waiters)waiter.resolve();this.waiters=[];
  }
 }
 drain(){
  if(this.failed)return Promise.reject(this.failed);this.closed=true;
  const promise=new Promise((resolve,reject)=>this.waiters.push({resolve,reject}));this.pump();return promise;
 }
}
