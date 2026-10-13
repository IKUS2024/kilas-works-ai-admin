// Consent/Start scoped AudioWorklet capture. Synthetic injection supported.
const failure=(code,message)=>Object.assign(Error(message),{code,startupStage:'microphone_start'});
const aborted=()=>new DOMException('Sesi berakhir.','AbortError');
export class RealtimeCapture {
  constructor({getContext,mediaDevices,createNode=(ctx)=>new AudioWorkletNode(ctx,'kilas-pcm'),schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id)}){
    Object.assign(this,{getContext,mediaDevices,createNode,schedule,clear});this.version=0;this.timer=null;this.flushTimer=null;
  }
  cleanup(){
    this.clear(this.timer);this.clear(this.flushTimer);this.clear(this.idleTimer);this.timer=null;this.flushTimer=null;this.idleTimer=null;
    if(this.node)this.node.port.onmessage=null;
    try{this.source?.disconnect();}catch{}try{this.node?.disconnect();}catch{}
    for(const track of this.stream?.getTracks()||[]){try{track.stop();}catch{}}
    this.stream=null;this.source=null;this.node=null;
  }
  cancel(reason=aborted()){this.version++;this.startupController?.abort(reason);this.startupController=null;this.cleanup();}
  bounded(signal,work,ms,timeout,onLate=()=>{}){
    return new Promise((resolve,reject)=>{
      let settled=false;
      const finish=(fn,value)=>{if(settled)return;settled=true;try{this.clear(timer);}catch{}signal.removeEventListener('abort',cancel);fn(value);};
      const cancel=()=>finish(reject,signal.reason||aborted());
      const timer=this.schedule(()=>finish(reject,timeout),ms);
      signal.addEventListener('abort',cancel,{once:true});if(signal.aborted){cancel();return;}
      try{Promise.resolve(work()).then(value=>{if(settled){try{onLate(value);}catch{}return;}finish(resolve,value);},e=>finish(reject,e));}catch(e){finish(reject,e);}
    });
  }
  async start({level,pcm,blob,error,ready:notifyReady=()=>{}}){
    this.cancel();this.error=error;this.finalizing=false;const ticket=this.version,context=this.getContext(),controller=new AbortController();this.startupController=controller;let heard=false,preRoll=[],ready=false,resolveReady;
    const fail=e=>{if(ticket!==this.version)return;this.cancel(e);if(ready)error(e);};
    try{
      if(!context?.audioWorklet||!this.mediaDevices?.getUserMedia)throw failure('realtime_capture_unavailable','Input realtime belum didukung browser ini.');
      if(context.state!=='running'){
        await this.bounded(controller.signal,()=>context.resume(),5000,failure('audio_resume','Audio belum berjalan. Tekan Lanjutkan untuk menyiapkan audio.'));
        if(context.state!=='running')throw failure('audio_resume','Audio belum berjalan. Tekan Lanjutkan untuk menyiapkan audio.');
      }
      const stopLate=stream=>{for(const track of stream?.getTracks?.()||[]){try{track.stop();}catch{}}};
      let stream;
      try{stream=await this.bounded(controller.signal,()=>this.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}}),20000,failure('microphone_permission_timeout','Izin mikrofon belum dijawab. Periksa izin browser lalu tekan Lanjutkan.'),stopLate);}
      catch(e){if(e?.name==='NotAllowedError'||e?.name==='SecurityError')throw failure('microphone_permission_denied','Izin mikrofon ditolak. Izinkan mikrofon di browser lalu tekan Lanjutkan.');throw e;}
      if(ticket!==this.version){stopLate(stream);throw aborted();}
      if(!stream?.getTracks?.().length)throw failure('microphone_unavailable','Mikrofon tidak tersedia. Periksa perangkat lalu tekan Lanjutkan.');
      this.stream=stream;
      stream.getTracks().forEach(track=>track.addEventListener?.('ended',()=>{if(!this.finalizing)fail(Object.assign(Error('Mikrofon terputus.'),{code:'microphone_unavailable'}));},{once:true}));
      await this.bounded(controller.signal,()=>context.audioWorklet.addModule('/static/kilas_live_translator_pcm.mjs?v=realtime-input-20261013'),10000,failure('realtime_module_timeout','Input audio belum dapat dimuat. Periksa koneksi lalu tekan Lanjutkan.'));
      if(ticket!==this.version)throw aborted();
      this.finalizing=false;this.done=()=>{if(ticket!==this.version)return;this.cleanup();blob(null);};
      const node=this.createNode(context);this.node=node;
      const firstFrame=this.bounded(controller.signal,()=>new Promise(resolve=>{resolveReady=resolve;}),5000,failure('realtime_input_timeout','Input mikrofon belum mengirim audio. Periksa mikrofon lalu tekan Lanjutkan.'));
      // Observe immediately: a synchronous node/connect failure must not leave a rejection unhandled.
      firstFrame.catch(()=>{});
      node.onprocessorerror=()=>fail(Object.assign(Error('Input audio realtime terputus.'),{code:'realtime_capture_failed'}));
      node.port.onmessage=event=>{
        if(ticket!==this.version)return;
        if(event.data?.finished){this.done();return;}
        const {bytes,rms}=event.data||{};
        if(!(bytes instanceof ArrayBuffer)||!bytes.byteLength||bytes.byteLength>6400||bytes.byteLength%2||!Number.isFinite(rms)){fail(Object.assign(Error('Input audio realtime tidak valid.'),{code:'realtime_capture_failed'}));return;}
        if(!ready){ready=true;notifyReady();resolveReady();}
        if(heard||rms>=.015){
          if(!heard){heard=true;this.timer=this.schedule(()=>fail(Object.assign(Error('Ucapan terlalu panjang. Sesi dijeda tanpa menerjemahkan sebagian.'),{code:'utterance_limit'})),179000);for(const previous of preRoll)pcm(new Uint8Array(previous));preRoll=[];}
          pcm(new Uint8Array(bytes));
        }else{preRoll.push(bytes);if(preRoll.length>2)preRoll.shift();}
        level(rms);
      };
      this.source=context.createMediaStreamSource(stream);this.source.connect(node);node.connect(context.destination);
      this.idleTimer=this.schedule(()=>{if(!heard)fail(Object.assign(Error(''),{code:'capture_idle',recoverable:true,silent:true}));},60000);
      // No supplier connection or silence keepalive before the first voice frame.
      await firstFrame;
    }catch(e){if(!(e instanceof Error))e=failure('realtime_capture_failed',typeof e==='string'&&e?e:'Input mikrofon belum siap. Periksa izin browser lalu tekan Lanjutkan.');if(ticket===this.version)this.cancel(e);throw e;}
  }
  finalize(){
    if(!this.node||this.finalizing)return;this.finalizing=true;
    for(const track of this.stream?.getTracks()||[]){try{track.stop();}catch{}}
    // Worklet FIFO flush delivers the final partial PCM frame BEFORE finished.
    this.flushTimer=this.schedule(()=>{this.cancel();this.error?.(Object.assign(Error('Audio terakhir belum selesai dikirim.'),{code:'realtime_capture_failed'}));},3000);
    this.node.port.postMessage({finish:true});
  }
}
