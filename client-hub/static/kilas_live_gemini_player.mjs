// Bounded PCM24k mono queue. No provider, network or microphone work on import.
export class GeminiPlayer {
 constructor({getContext,now=()=>performance.now(),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id),onError=()=>{},onStarted=()=>{},onTiming=()=>{},onScheduled=()=>{},onHold=()=>{},onPlaying=()=>{},maxBufferedSeconds=8}){
  Object.assign(this,{getContext,now,schedule,clear,onError,onStarted,onTiming,onScheduled,onHold,onPlaying,maxBufferedSeconds});this.version=0;this.reset();
 }
 reset(){
  for(const waiter of this.waiters||[])waiter.reject(new DOMException('Aborted','AbortError'));
  this.version++;this.clear?.(this.timer);this.timer=null;
  for(const node of this.nodes||[]){node.onended=null;try{node.stop();node.disconnect();}catch{}}
  this.nodes=new Set();this.ends=new Map();this.deadlines=new Map();this.entries=new Map();this.queue=[];this.pendingSamples=0;this.nextAt=0;this.closed=false;
  this.lastClock=null;this.lastProgress=this.now();this.waiters=[];this.failed=null;this.first=true;this.holding=false;
 }
 cancel(){this.reset();}
 fail(code){
  if(this.failed)return;const error=Object.assign(Error(code),{code});this.failed=error;
  const waiters=this.waiters;this.waiters=[];this.clear(this.timer);this.timer=null;
  for(const node of this.nodes){node.onended=null;try{node.stop();node.disconnect();}catch{}}
  this.nodes.clear();this.ends.clear();this.deadlines.clear();this.entries.clear();this.queue=[];this.pendingSamples=0;
  for(const waiter of waiters)waiter.reject(error);this.onError(error);
 }
 push(raw,scope=null){
  if(this.closed||this.failed)throw this.failed||Error('gemini_player_closed');
  if(!(raw instanceof Uint8Array)||!raw.byteLength||raw.byteLength%2||raw.byteLength>9600)throw Error('gemini_pcm_invalid');
  const context=this.getContext();if(!context||context.state!=='running')throw Error('audio_context');
  const samples=raw.byteLength/2;
  if(this.pendingSamples+samples>this.maxBufferedSeconds*24000)throw Error('gemini_playback_backlog');
  const buffer=context.createBuffer(1,samples,24000),channel=buffer.getChannelData(0),view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);
  for(let i=0;i<samples;i++)channel[i]=view.getInt16(i*2,true)/32768;
  this.queue.push({buffer,scope});this.pendingSamples+=samples;
  if(this.holding)return;
  if(this.first&&this.pendingSamples<.3*24000){
   if(this.timer===null)this.timer=this.schedule(()=>{this.timer=null;this.pump();},300);
  }else this.pump();
 }
 pump(){
  if(this.failed||this.holding)return;this.clear(this.timer);this.timer=null;
  const context=this.getContext();if(!context||context.state!=='running'){this.fail('audio_stalled');return;}
  const ticket=this.version;
  while(this.queue.length){
   const entry=this.queue.shift(),{buffer}=entry,node=context.createBufferSource();node.buffer=buffer;node.connect(context.destination);
   const at=Math.max(context.currentTime+.02,this.nextAt);
   if(!this.first){try{this.onTiming({schedule_gap_ms:Math.max(0,(at-this.nextAt)*1000)});}catch{}}
   this.nextAt=at+buffer.duration;entry.at=at;
   this.nodes.add(node);this.ends.set(node,at+buffer.duration);this.deadlines.set(node,this.now()+Math.max(0,at+buffer.duration-context.currentTime)*1000+5000);this.entries.set(node,entry);node.onended=()=>{
    if(ticket!==this.version||this.failed)return;
    if(context.currentTime+.05<at+buffer.duration){this.fail('audio_stalled');return;}
    if(!this.nodes.delete(node))return;this.ends.delete(node);this.deadlines.delete(node);this.entries.delete(node);this.pendingSamples-=buffer.length;try{node.disconnect();}catch{}this.complete(entry);
   };
   try{node.start(at);this.onScheduled(buffer,at);this.onPlaying();}catch{this.fail('audio_start');return;}
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
   for(const [node,end] of this.ends){
    if(this.now()>=this.deadlines.get(node)&&context.currentTime<end){this.fail('audio_stalled');return;}
    if(context.currentTime>=end+.25||(this.now()>=this.deadlines.get(node)&&context.currentTime>=end))node.onended?.();
   }
   if(this.nodes.size)this.watch(ticket);this.complete();
  },250);
 }
 complete(entry=null){
  if(this.failed)return;
  const pending=[];for(const waiter of this.waiters){if(entry)waiter.entries.delete(entry);if(!waiter.entries.size)waiter.resolve();else pending.push(waiter);}this.waiters=pending;
  if(!this.nodes.size&&!this.queue.length){this.clear(this.timer);this.timer=null;}
 }
 checkpoint(){
  if(this.failed)return Promise.reject(this.failed);
  const entries=new Set([...this.queue,...this.entries.values()]);
  if(!entries.size)return Promise.resolve();
  const promise=new Promise((resolve,reject)=>this.waiters.push({resolve,reject,entries}));this.pump();return promise;
 }
 hold(){
  if(this.holding||this.failed)return;this.holding=true;this.clear(this.timer);this.timer=null;
  const context=this.getContext(),now=context?.currentTime||0,retained=[];
  for(const [node,entry] of this.entries){
   node.onended=null;try{node.stop();node.disconnect();}catch{}
   const offset=Math.max(0,Math.min(entry.buffer.length,Math.floor((now-entry.at)*24000)));
   this.pendingSamples-=offset;
   if(offset<entry.buffer.length){
    if(offset){const buffer=context.createBuffer(1,entry.buffer.length-offset,24000);buffer.getChannelData(0).set(entry.buffer.getChannelData(0).subarray(offset));entry.buffer=buffer;}
    retained.push(entry);
   }else this.complete(entry);
  }
  this.queue=[...retained,...this.queue];this.nodes.clear();this.ends.clear();this.deadlines.clear();this.entries.clear();this.nextAt=now;
  this.lastClock=null;this.lastProgress=this.now();this.onHold(now);
 }
 release(){if(this.failed)return;this.holding=false;if(this.queue.length)this.pump();}
 drain(){this.closed=true;this.release();return this.checkpoint();}
 interrupt(scope){
  // Provider barge-in invalidates only this physical turn's generation. Audio
  // accepted from the preceding turn keeps its place on the same audio clock.
  const removed=new Set();this.queue=this.queue.filter(entry=>{if(entry.scope!==scope)return true;removed.add(entry);this.pendingSamples-=entry.buffer.length;return false;});
  for(const [node,entry] of this.entries){if(entry.scope!==scope)continue;removed.add(entry);node.onended=null;try{node.stop();node.disconnect();}catch{}this.nodes.delete(node);this.ends.delete(node);this.deadlines.delete(node);this.entries.delete(node);this.pendingSamples-=entry.buffer.length;}
  const pending=[];for(const waiter of this.waiters){if([...removed].some(entry=>waiter.entries.has(entry)))waiter.reject(new DOMException('Aborted','AbortError'));else pending.push(waiter);}this.waiters=pending;
  const context=this.getContext();this.nextAt=Math.max(context?.currentTime||0,...this.ends.values());this.complete();
 }
}
