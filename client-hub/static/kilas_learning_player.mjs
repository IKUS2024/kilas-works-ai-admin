import {within} from './kilas_learning_engine.mjs';

// Local ownership fences late decode/resume/end callbacks from a newer call.
export class LearningPlayer {
  constructor(createContext=()=>new(window.AudioContext||window.webkitAudioContext)()) {
    this.createContext=createContext;this.generation=0;this.context=null;this.cancelPlayback=null;
  }
  connect(){return this.context??=this.createContext();}
  async unlock(signal){
    const generation=this.generation;this.check(signal,generation);const ctx=this.connect();
    await within(()=>ctx.resume(),signal);
    this.check(signal,generation);
  }
  check(signal,generation){
    if(signal.aborted||generation!==this.generation)throw new DOMException('Aborted','AbortError');
  }
  async prepare(raw,signal){
    const generation=this.generation;this.check(signal,generation);const ctx=this.connect();
    const buffer=await within(()=>ctx.decodeAudioData(raw.slice(0)),signal);
    this.check(signal,generation);return {buffer,generation};
  }
  async play(raw,signal,started=()=>{}){
    const prepared=raw?.buffer&&raw?.generation!==undefined?raw:await this.prepare(raw,signal);
    const {buffer,generation}=prepared;this.check(signal,generation);const ctx=this.connect();
    if(ctx.state!=='running')await within(()=>ctx.resume(),signal);
    this.check(signal,generation);
    return new Promise((resolve,reject)=>{
      const source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);let settled=false;
      const finish=error=>{
        if(settled)return;settled=true;clearTimeout(timer);signal.removeEventListener('abort',abort);
        source.onended=null;source.disconnect();if(this.cancelPlayback===abort)this.cancelPlayback=null;
        error?reject(error):resolve();
      };
      const abort=()=>{source.onended=null;try{source.stop();}catch{}finish(new DOMException('Aborted','AbortError'));};
      const timer=setTimeout(()=>{source.onended=null;try{source.stop();}catch{}finish(Error('Pemutaran terputus. Tekan Lanjutkan untuk memeriksa sesi.'));},Math.max(10000,buffer.duration*1000+10000));
      this.cancelPlayback=abort;source.onended=()=>finish();signal.addEventListener('abort',abort,{once:true});
      try{source.start();started();}catch(error){source.onended=null;try{source.stop();}catch{}finish(error);}
    });
  }
  stop(){
    ++this.generation;this.cancelPlayback?.();this.cancelPlayback=null;
    const ctx=this.context;this.context=null;if(ctx)void ctx.close().catch(()=>{});
  }
}
