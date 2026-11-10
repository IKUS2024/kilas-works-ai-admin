// Visual input feedback only. Never gates, records or changes microphone PCM.
export function microphoneLevel(rms){
 if(!Number.isFinite(rms)||rms<=.006)return 0;
 return Math.min(1,Math.sqrt((rms-.006)/.14));
}
export class MicrophoneMeter {
 constructor({element,schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id)}){
  Object.assign(this,{element,schedule,clear});this.bars=Array.from(element.querySelectorAll('[data-mic-bar]'));this.reset();
 }
 reset(){
  this.clear(this.timer);this.timer=null;this.element.dataset.active='false';
  for(const bar of this.bars)bar.style.height='3px';
 }
 update(rms){
  if(!Number.isFinite(rms)){this.reset();return;}
  this.clear(this.timer);this.element.dataset.active='true';
  const level=microphoneLevel(rms),center=(this.bars.length-1)/2;
  this.bars.forEach((bar,index)=>{const weight=1-Math.abs(index-center)/(center+1)*.65;bar.style.height=(3+25*level*weight).toFixed(2)+'px';});
  // Don't leave stale audio on screen if frames stop before capture's watchdog.
  this.timer=this.schedule(()=>this.reset(),700);
 }
}
