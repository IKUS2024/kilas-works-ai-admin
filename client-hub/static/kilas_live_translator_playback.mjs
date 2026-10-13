// Bounded Web Audio playback. No microphone, provider calls or automatic replay.
const abortError=()=>new DOMException('Sesi berakhir.','AbortError');
const failure=(code,message)=>Object.assign(Error(message+' Audio ini tidak dibuat ulang otomatis.'),{code});
const MAX_BYTES=20*1024*1024;

export class TranslatorPlayback {
  constructor({getContext,fetchAudio=(...args)=>globalThis.fetch(...args),schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id),now=()=>performance.now()}){
    Object.assign(this,{getContext,fetchAudio,schedule,clear,now});this.operation=null;
  }
  cancel(){this.operation?.controller.abort();}
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
  async run(signal,isCurrent,work){
    this.cancel();
    const op={controller:new AbortController(),context:this.getContext(),isCurrent};this.operation=op;
    const cancel=()=>op.controller.abort();signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
    try{this.check(op);if(!op.context||op.context.state==='closed')throw failure('audio_context','Audio tidak tersedia. Periksa audio browser.');return await work(op);}
    finally{op.controller.abort();signal.removeEventListener('abort',cancel);if(this.operation===op)this.operation=null;}
  }
  async resume(op){
    if(op.context.state==='running')return;
    const error=failure('audio_resume','Audio belum diizinkan atau terputus. Periksa audio browser lalu tekan Lanjutkan.');
    try{await this.bounded(op,()=>op.context.resume(),5000,error);}catch(e){if(this.cancelled(op,e))throw e;throw error;}
    this.check(op);if(op.context.state!=='running')throw error;
  }
  prepare(signal,isCurrent){return this.run(signal,isCurrent,op=>this.resume(op));}
  play(url,signal,isCurrent){
    return this.run(signal,isCurrent,async op=>{
      if(typeof url!=='string'||!/^\/kilas-translator\/live\/sessions\/[a-f0-9]{48}\/turns\/live-[a-f0-9]{32}\/audio$/.test(url))throw failure('audio_url','Hasil audio tidak tersedia.');
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
      // Android may suspend the context while network/provider work is in flight.
      await this.resume(op);this.check(op);
      await this.bounded(op,()=>this.playBuffer(op,buffer),buffer.duration*1000+10000,failure('audio_timeout','Pemutaran audio melewati batas waktu.'));
    });
  }
  playBuffer(op,buffer){
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
      try{this.check(op);node=context.createBufferSource();node.buffer=buffer;node.connect(context.destination);node.onended=()=>{try{this.check(op);finish();}catch(e){finish(e);}};node.start();timer=this.schedule(watch,250);}
      catch(e){finish(e.name==='AbortError'?e:failure('audio_start','Audio belum dapat diputar.'));}
    });
  }
}
