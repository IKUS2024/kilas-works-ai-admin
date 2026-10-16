// Call-only jitter buffer. The shared Translator player remains unchanged.
import {GeminiPlayer} from './kilas_live_gemini_player.mjs?v=native-progressive-20261016';

export class CallPlayer {
 constructor({schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id),...options}){
  Object.assign(this,{schedule,clear});this.player=new GeminiPlayer({...options,schedule,clear,maxBufferedSeconds:60});
  this.waiting=false;this.timer=null;this.version=0;
 }
 push(raw,scope='call'){
  const player=this.player,context=player.getContext();
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
 release(){this.clear(this.timer);this.timer=null;this.waiting=false;this.player.release();}
 checkpoint(){
  // The provider's turn-complete marker seals the tail. A short answer never
  // has to fill the jitter buffer, and every accepted sample still drains.
  this.release();return this.player.checkpoint();
 }
 cancel(){++this.version;this.clear(this.timer);this.timer=null;this.waiting=false;this.player.cancel();}
}
