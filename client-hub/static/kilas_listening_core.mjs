// Injectable lifecycle boundary. No encoder, recording, persistence or provider transport.
export function displayCapture({enabled=false, mediaDevices=globalThis.navigator?.mediaDevices}={}) {
  return ({userGesture=false}={}) => {
    if (!enabled) return Promise.reject(new Error('real_disabled'));
    if (!userGesture) return Promise.reject(new Error('gesture_required'));
    if (!mediaDevices?.getDisplayMedia) return Promise.reject(new Error('unsupported'));
    // Invoked directly from the future click handler, before asynchronous work.
    return mediaDevices.getDisplayMedia({video:{displaySurface:'browser'},audio:true,
      systemAudio:'exclude',selfBrowserSurface:'exclude',surfaceSwitching:'exclude'});
  };
}

export function syntheticStream() {
  const tracks=['audio','video'].map(kind => Object.assign(new EventTarget(), {
    kind,readyState:'live',stop(){this.readyState='ended';},
    getSettings(){return kind==='video'?{displaySurface:'browser'}:{};}
  }));
  return {getTracks:()=>tracks,getAudioTracks:()=>tracks.filter(t=>t.kind==='audio'),
    getVideoTracks:()=>tracks.filter(t=>t.kind==='video')};
}

export class ListeningSession {
  constructor({selectStream,onState=()=>{},onSegment=()=>{},schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),cancel=id=>globalThis.clearTimeout(id)}) {
    Object.assign(this,{selectStream,onState,onSegment,schedule,cancel});
    this.state='idle';this.generation=0;this.stream=null;this.timer=null;this.listeners=[];
  }
  report(state,reason='') {this.state=state;this.onState({state,reason});}
  async start({consent=false,userGesture=false,segments=[]}={}) {
    if (['starting','active'].includes(this.state)) return;
    if (!consent) {this.report('error','consent_required');return;}
    const generation=++this.generation;
    this.report('starting');
    try {
      const stream=await this.selectStream({userGesture});
      if(generation!==this.generation) {stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      if (!stream.getAudioTracks().length) throw new Error('audio_missing');
      if (!stream.getVideoTracks().length || stream.getVideoTracks().some(t=>t.getSettings?.().displaySurface!=='browser')) throw new Error('tab_required');
      if (stream.getTracks().some(t=>t.readyState==='ended')) throw new Error('source_ended');
      for(const track of stream.getTracks()) {
        const ended=()=>this.stop('disconnected');
        track.addEventListener('ended',ended);this.listeners.push([track,ended]);
      }
      this.report('active');
      let index=0;
      const emit=()=>{
        this.timer=null;
        if(generation!==this.generation || this.state!=='active') return;
        if(index<segments.length) {
          try {this.onSegment({...segments[index],sequence:index+1});index++;}
          catch {this.cleanup();this.report('error','stream_failed');return;}
          this.timer=this.schedule(emit,index===segments.length?5000:900);
        } else this.stop('complete');
      };
      this.timer=this.schedule(emit,250);
    } catch(error) {
      if(generation!==this.generation) return;
      this.cleanup();
      this.report('error',error.name==='NotAllowedError'?'permission_denied':error.message);
    }
  }
  cleanup() {
    if(this.timer!==null) {this.cancel(this.timer);this.timer=null;}
    for(const [track,listener] of this.listeners) track.removeEventListener('ended',listener);
    this.listeners=[];
    this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;
  }
  stop(reason='stopped') {++this.generation;this.cleanup();this.report('idle',reason);}
}
