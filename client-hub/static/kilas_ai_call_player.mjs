// Call-only jitter buffer. The shared Translator player remains unchanged.
import {GeminiPlayer} from './kilas_live_gemini_player.mjs?v=native-progressive-20261016';

export class CallPlayer {
 constructor({schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id),...options}){
  Object.assign(this,{schedule,clear});this.player=new GeminiPlayer({...options,schedule,clear,maxBufferedSeconds:60});
  this.waiting=false;this.timer=null;this.version=0;this.paused=false;this.pausedFrames=[];this.pausedBytes=0;this.pausedWaiters=[];
 }
 push(raw,scope='call'){
  try{return this.enqueue(raw,scope);}catch(error){if(!error.code)error.code='call_audio';throw error;}
 }
 enqueue(raw,scope='call'){
  const player=this.player,context=player.getContext();
  if(this.paused){
   if(!(raw instanceof Uint8Array)||!raw.length||raw.length%2||raw.length>9600)throw Error('call_audio');
   if(this.pausedBytes+raw.length+player.pendingSamples*2>60*48000)throw Error('call_audio');
   this.pausedFrames.push({raw:raw.slice(),scope});this.pausedBytes+=raw.length;return;
  }
  // A new answer, or an actual underrun, needs a fresh cushion. Audio already
  // scheduled ahead stays on its continuous 24k sample clock.
  const empty=!player.pendingSamples;
  const underrun=player.nextAt>0&&context?.currentTime>=player.nextAt;
  if(!this.waiting&&(empty||underrun)){
   player.hold();this.waiting=true;const ticket=++this.version;
   this.timer=this.schedule(()=>{if(ticket===this.version)this.release();},1250);
  }
  player.push(raw,scope);
  if(this.waiting&&player.pendingSamples>=.75*24000)this.release();
 }
 release(){this.clear(this.timer);this.timer=null;this.waiting=false;if(!this.paused)this.player.release();}
 checkpoint(){
  if(this.paused)return new Promise((resolve,reject)=>this.pausedWaiters.push({resolve,reject}));
  // The provider's turn-complete marker seals the tail. A short answer never
  // has to fill the jitter buffer, and every accepted sample still drains.
  this.release();return this.player.checkpoint();
 }
 suspend(){if(this.paused)return;this.paused=true;this.player.hold();}
 resume(){
  if(!this.paused)return;this.paused=false;
  const frames=this.pausedFrames;this.pausedFrames=[];this.pausedBytes=0;
  for(const {raw,scope} of frames)this.push(raw,scope);
  this.release();
  const waiters=this.pausedWaiters;this.pausedWaiters=[];
  if(waiters.length)this.player.checkpoint().then(()=>waiters.forEach(w=>w.resolve()),e=>waiters.forEach(w=>w.reject(e)));
 }
 cancel(){
  this.paused=false;this.pausedFrames=[];this.pausedBytes=0;
  for(const waiter of this.pausedWaiters)waiter.reject(new DOMException('Aborted','AbortError'));this.pausedWaiters=[];
  ++this.version;this.clear(this.timer);this.timer=null;this.waiting=false;this.player.cancel();}
}
