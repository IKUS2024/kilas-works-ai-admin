// Bounded Web Audio playback. No microphone, provider calls or automatic replay.
const abortError=()=>new DOMException('Sesi berakhir.','AbortError');
const failure=(code,message)=>Object.assign(Error(message+' Audio ini tidak dibuat ulang otomatis.'),{code});
const MAX_BYTES=20*1024*1024;

export class TranslatorPlayback {
  constructor({getContext,fetchAudio=(...args)=>globalThis.fetch(...args),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id),now=()=>performance.now()}){
    Object.assign(this,{getContext,fetchAudio,schedule,clear,now});this.operation=null;this.prefetched=null;
  }
  discardPrefetch(){this.prefetched?.controller.abort();this.prefetched?.cleanup?.();this.prefetched=null;}
  cancel(){this.operation?.controller.abort();this.operation?.prefetch?.controller.abort();this.discardPrefetch();}
  check(op){if(op.controller.signal.aborted||!op.isCurrent())throw abortError();}
  cancelled(op,error){return error.name==='AbortError'&&(op.controller.signal.aborted||!op.isCurrent());}
  bounded(op,work,ms,error){
    this.check(op);
    return new Promise((resolve,reject)=>{
      let settled=false;
      const finish=(fn,value)=>{if(settled)return;settled=true;this.clear(timer);op.controller.signal.removeEventListener('abort',cancel);fn(value);};
      const cancel=()=>finish(reject,abortError());
      const timer=this.schedule(()=>{finish(reject,error);op.controller.abort();},ms);
      op.controller.signal.addEventListener('abort',cancel,{once:true});
      // Call synchronously: prepare() must resume inside the Start user gesture.
      try{Promise.resolve(work()).then(value=>{try{this.check(op);finish(resolve,value);}catch(e){finish(reject,e);}},e=>finish(reject,e));}catch(e){finish(reject,e);}
    });
  }
  async run(signal,isCurrent,work,prefetch=null){
    this.operation?.controller.abort();
    const op={controller:new AbortController(),context:this.getContext(),isCurrent,prefetch};this.operation=op;
    const cancel=()=>op.controller.abort();signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
    try{this.check(op);if(!op.context||op.context.state==='closed')throw failure('audio_context','Audio tidak tersedia. Periksa audio browser.');return await work(op);}
    finally{op.controller.abort();op.prefetch?.controller.abort();op.prefetch?.cleanup?.();signal.removeEventListener('abort',cancel);if(this.operation===op)this.operation=null;}
  }
  async resume(op){
    if(op.context.state==='running')return;
    const error=failure('audio_resume','Audio belum diizinkan atau terputus. Periksa audio browser lalu tekan Lanjutkan.');
    try{await this.bounded(op,()=>op.context.resume(),5000,error);}catch(e){if(this.cancelled(op,e))throw e;throw error;}
    this.check(op);if(op.context.state!=='running')throw error;
  }
  prepare(signal,isCurrent){this.discardPrefetch();return this.run(signal,isCurrent,op=>this.resume(op));}
  async load(op,url){
      if(typeof url!=='string'||!/^\/kilas-translator\/live\/sessions\/[a-f0-9]{48}\/turns\/live-[a-f0-9]{32}\/audio(?:\/segments\/[0-7])?$/.test(url))throw failure('audio_url','Hasil audio tidak tersedia.');
      const loadError=failure('audio_fetch','Audio belum dapat dimuat. Periksa koneksi.');
      let raw;
      try{
        raw=await this.bounded(op,async()=>{
          const response=await this.fetchAudio(url,{credentials:'same-origin',signal:op.controller.signal,cache:'no-store',redirect:'error'});
          this.check(op);
          if(!response.ok||response.redirected)throw loadError;
          const size=Number(response.headers?.get('Content-Length'));if(size>MAX_BYTES)throw failure('audio_size','Audio melebihi batas.');
          const data=await response.arrayBuffer();if(!data.byteLength||data.byteLength>MAX_BYTES)throw failure('audio_size','Audio kosong atau melebihi batas.');
          return data;
        },15000,loadError);
      }catch(e){if(this.cancelled(op,e)||typeof e.code==='string')throw e;throw loadError;}
      const decodeError=failure('audio_decode','Format audio belum dapat dibaca.');let buffer;
      try{buffer=await this.bounded(op,()=>op.context.decodeAudioData(raw),10000,decodeError);}catch(e){if(this.cancelled(op,e))throw e;throw decodeError;}
      if(!Number.isFinite(buffer?.duration)||buffer.duration<=0||buffer.duration>600)throw decodeError;
      return buffer;
  }
  // At most one successor is downloaded/decoded. This never starts a source or
  // resumes the audio context, and a failed download is consumed without retry.
  prefetch(url,signal,isCurrent){
    if(this.prefetched?.url===url&&this.prefetched.signal===signal)return;
    this.discardPrefetch();
    const op={url,signal,controller:new AbortController(),context:this.getContext(),isCurrent};
    const cancel=()=>{op.controller.abort();if(this.prefetched===op)this.prefetched=null;};
    op.cleanup=()=>signal.removeEventListener('abort',cancel);
    this.prefetched=op;
    signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
    op.promise=(async()=>{
      try{this.check(op);if(!op.context||op.context.state==='closed')throw failure('audio_context','Audio tidak tersedia. Periksa audio browser.');return {buffer:await this.load(op,url)};}
      catch(error){return {error};}
    })();
  }
  play(url,signal,isCurrent,onStarted=()=>{}){
    const slot=this.prefetched?.url===url&&this.prefetched.signal===signal&&this.prefetched.context===this.getContext()?this.prefetched:null;
    if(slot)this.prefetched=null;else this.discardPrefetch();
    return this.run(signal,isCurrent,async op=>{
      const waitBegan=this.now();let buffer;
      if(slot){
        op.controller.signal.addEventListener('abort',()=>slot.controller.abort(),{once:true});
        const loaded=await this.bounded(op,()=>slot.promise,25000,failure('audio_fetch','Audio belum dapat dimuat. Periksa koneksi.'));
        this.check(op);if(loaded.error)throw loaded.error;buffer=loaded.buffer;
      }
      else buffer=await this.load(op,url);
      const bufferWaitMs=Math.max(0,this.now()-waitBegan);
      // Android may suspend the context while network/provider work is in flight.
      await this.resume(op);this.check(op);
      await this.bounded(op,()=>this.playBuffer(op,buffer,()=>onStarted({buffer_wait_ms:bufferWaitMs})),buffer.duration*1000+10000,failure('audio_timeout','Pemutaran audio melewati batas waktu.'));
    },slot);
  }
  playBuffer(op,buffer,onStarted){
    return new Promise((resolve,reject)=>{
      const context=op.context;let node=null,timer=null,settled=false,recovered=false;
      let lastTime=context.currentTime,lastProgress=this.now(),audioStart=context.currentTime;
      const finish=error=>{
        if(settled)return;settled=true;if(timer!==null)this.clear(timer);op.controller.signal.removeEventListener('abort',cancel);
        if(node){node.onended=null;try{node.stop();}catch{}try{node.disconnect();}catch{}}
        error?reject(error):resolve();
      };
      const cancel=()=>finish(abortError());op.controller.signal.addEventListener('abort',cancel,{once:true});
      const watch=async()=>{
        timer=null;
        try{
          this.check(op);
          if(context.state!=='running'){
            if(recovered||context.state==='closed')throw failure('audio_stalled','Pemutaran audio terputus.');
            recovered=true;await this.resume(op);if(settled)return;lastProgress=this.now();lastTime=context.currentTime;
          }
          if(context.currentTime>lastTime){lastTime=context.currentTime;lastProgress=this.now();}
          // A finite buffer has finished once the running audio clock passed it,
          // even if a device omitted onended. Never resume capture on a wall timer.
          if(context.currentTime-audioStart>=buffer.duration+.25){finish();return;}
          if(this.now()-lastProgress>=5000)throw failure('audio_stalled','Pemutaran audio tidak bergerak.');
          timer=this.schedule(watch,250);
        }catch(e){finish(e);}
      };
      try{
        this.check(op);node=context.createBufferSource();node.buffer=buffer;node.connect(context.destination);
        // Allow 50 ms of audio-clock rounding at the natural end, never a wall-time success.
        node.onended=()=>{try{this.check(op);if(context.currentTime-audioStart<buffer.duration-.05)throw failure('audio_stalled','Pemutaran audio berakhir sebelum ucapan selesai.');finish();}catch(e){finish(e);}};node.start();try{onStarted();}catch{}timer=this.schedule(watch,250);}
      catch(e){finish(e.name==='AbortError'?e:failure('audio_start','Audio belum dapat diputar.'));}
    });
  }
}
