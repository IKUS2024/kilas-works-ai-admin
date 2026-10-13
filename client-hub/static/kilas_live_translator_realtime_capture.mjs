// Consent/Start scoped AudioWorklet capture. Synthetic injection supported.
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
  cancel(){this.version++;this.cleanup();}
  async start({level,pcm,blob,error}){
    this.cancel();this.error=error;this.finalizing=false;const ticket=this.version,context=this.getContext();let heard=false,preRoll=[];
    const fail=e=>{if(ticket!==this.version)return;this.cancel();error(e);};
    try{
      if(!context?.audioWorklet||!this.mediaDevices?.getUserMedia)throw Object.assign(Error('Input realtime belum didukung browser ini.'),{code:'realtime_capture_unavailable'});
      const stream=await this.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      if(ticket!==this.version){stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      stream.getTracks().forEach(track=>track.addEventListener?.('ended',()=>{if(!this.finalizing)fail(Object.assign(Error('Mikrofon terputus.'),{code:'microphone_unavailable'}));},{once:true}));
      await context.audioWorklet.addModule('/static/kilas_live_translator_pcm.mjs?v=realtime-input-20261013');
      if(ticket!==this.version)return;
      this.finalizing=false;this.done=()=>{if(ticket!==this.version)return;this.cleanup();blob(null);};
      const node=this.createNode(context);this.node=node;
      node.onprocessorerror=()=>fail(Object.assign(Error('Input audio realtime terputus.'),{code:'realtime_capture_failed'}));
      node.port.onmessage=event=>{
        if(ticket!==this.version)return;
        if(event.data?.finished){this.done();return;}
        const {bytes,rms}=event.data||{};
        if(!(bytes instanceof ArrayBuffer)||!bytes.byteLength||bytes.byteLength>6400||bytes.byteLength%2||!Number.isFinite(rms)){fail(Object.assign(Error('Input audio realtime tidak valid.'),{code:'realtime_capture_failed'}));return;}
        if(heard||rms>=.015){
          if(!heard){heard=true;this.timer=this.schedule(()=>fail(Object.assign(Error('Ucapan terlalu panjang. Sesi dijeda tanpa menerjemahkan sebagian.'),{code:'utterance_limit'})),179000);for(const previous of preRoll)pcm(new Uint8Array(previous));preRoll=[];}
          pcm(new Uint8Array(bytes));
        }else{preRoll.push(bytes);if(preRoll.length>2)preRoll.shift();}
        level(rms);
      };
      this.source=context.createMediaStreamSource(stream);this.source.connect(node);node.connect(context.destination);
      this.idleTimer=this.schedule(()=>{if(!heard)fail(Object.assign(Error(''),{code:'capture_idle',recoverable:true,silent:true}));},60000);
      // No supplier connection or silence keepalive before the first voice frame.
    }catch(e){fail(e);throw e;}
  }
  finalize(){
    if(!this.node||this.finalizing)return;this.finalizing=true;
    for(const track of this.stream?.getTracks()||[]){try{track.stop();}catch{}}
    // Worklet FIFO flush delivers the final partial PCM frame BEFORE finished.
    this.flushTimer=this.schedule(()=>{this.cancel();this.error?.(Object.assign(Error('Audio terakhir belum selesai dikirim.'),{code:'realtime_capture_failed'}));},3000);
    this.node.port.postMessage({finish:true});
  }
}
