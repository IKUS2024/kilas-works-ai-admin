// Pure, injectable session state. No microphone/network work merely on import.
export class SilenceGate {
  constructor({silenceMs=3000,threshold=.015}={}){this.silenceMs=silenceMs;this.threshold=threshold;this.reset();}
  reset(){this.lastVoice=null;this.finalized=false;}
  sample(rms,now){
    if(this.finalized)return false;
    if(rms>=this.threshold){this.lastVoice=now;return false;}
    if(this.lastVoice!==null&&now-this.lastVoice>=this.silenceMs){this.finalized=true;return true;}
    return false;
  }
}

export class TranslatorSession {
  constructor({api,capture,playback,onState=()=>{},onError=()=>{},now=()=>performance.now(),key=()=>crypto.randomUUID().replaceAll('-','')}){
    Object.assign(this,{api,capture,playback,onState,onError,now,key});this.version=0;this.state='ended';this.id=null;this.gate=new SilenceGate();
  }
  stateTo(state){this.state=state;this.onState(state);}
  async start(params){
    if(this.state!=='ended')return;
    const ticket=++this.version;this.controller=new AbortController();this.stateTo('starting');
    try{
      const result=await this.api.start(params,this.controller.signal);
      if(ticket!==this.version){await this.api.end(result.session_id).catch(()=>{});return;}
      this.id=result.session_id;await this.listen(ticket);
    }catch(e){if(ticket===this.version){this.onError(e.message);this.end();}}
  }
  async listen(ticket){
    if(ticket!==this.version)return;
    this.gate.reset();this.stateTo('listening');
    await this.capture.start({
      level:rms=>{if(ticket===this.version&&this.state==='listening'&&this.gate.sample(rms,this.now())){this.stateTo('finalizing');this.capture.finalize();}},
      blob:blob=>this.utterance(blob,ticket),
      error:e=>{if(ticket===this.version){this.onError(e.message);this.end();}},
    });
    if(ticket!==this.version)this.capture.cancel();
  }
  async utterance(blob,ticket){
    if(ticket!==this.version||this.state!=='finalizing')return;
    // Capture adapter releases every mic track before delivering the blob.
    this.stateTo('processing');
    try{
      const result=await this.api.turn(this.id,'live-'+this.key(),blob,this.controller.signal);
      if(ticket!==this.version)return;
      this.stateTo('playing');await this.playback.play(result.audio_url,this.controller.signal,()=>ticket===this.version);
      if(ticket!==this.version)return;
      await this.listen(ticket);
    }catch(e){
      if(ticket!==this.version||e.name==='AbortError')return;
      this.onError(e.message);
      if(e.code==='no_speech')await this.listen(ticket).catch(error=>{this.onError(error.message);this.end();});else this.end();
    }
  }
  end(){
    const id=this.id;this.id=null;++this.version;this.controller?.abort();this.capture.cancel();this.playback.stop();this.stateTo('ended');
    if(id)this.api.end(id).catch(()=>{});
  }
}
