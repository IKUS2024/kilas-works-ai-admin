import {displayCapture} from './kilas_listening_core.mjs';

export class TabAudioSession {
  constructor({enabled=false,mediaDevices,Context=globalThis.AudioContext,Worklet=globalThis.AudioWorkletNode,Stream=globalThis.MediaStream,onState=()=>{},onChunk=()=>{},onLevel=()=>{},schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id)}) {
    Object.assign(this,{enabled,mediaDevices,Context,Worklet,Stream,onState,onChunk,onLevel,schedule,clear});
    this.version=0;this.state='idle';this.stream=null;this.context=null;this.node=null;this.source=null;this.sink=null;this.listeners=[];this.timer=null;
  }
  report(state,reason=''){this.state=state;this.onState({state,reason});}
  async start({consent=false,userGesture=false}={}) {
    if(['starting','active'].includes(this.state))return;
    if(!consent){this.report('error','consent_required');return;}
    const ticket=++this.version;this.report('starting');
    try {
      // Immediate chooser invocation preserves transient activation from the click.
      const stream=await displayCapture({enabled:this.enabled,mediaDevices:this.mediaDevices})({userGesture});
      if(ticket!==this.version){stream.getTracks().forEach(t=>t.stop());return;}
      this.stream=stream;
      if(!stream.getAudioTracks().length)throw Error('audio_missing');
      if(!stream.getVideoTracks().length||stream.getVideoTracks().some(t=>t.getSettings().displaySurface!=='browser'))throw Error('tab_required');
      if(stream.getTracks().some(t=>t.readyState==='ended'))throw Error('source_ended');
      for(const track of stream.getTracks()){const ended=()=>this.stop('source_ended');track.addEventListener('ended',ended);this.listeners.push([track,ended]);}
      const context=new this.Context();this.context=context;
      await context.audioWorklet.addModule(new URL('./kilas_live_worklet.mjs',import.meta.url));
      if(ticket!==this.version)return;
      this.source=context.createMediaStreamSource(new this.Stream(stream.getAudioTracks()));
      this.node=new this.Worklet(context,'kilas-tab-pcm');this.sink=context.createGain();this.sink.gain.value=0;
      let count=0;
      this.node.port.onmessage=event=>{
        if(ticket!==this.version||this.state!=='active')return;
        if(event.data.kind==='level')this.onLevel(event.data.level);
        else if(event.data.kind==='chunk') {
          if(++count>12){this.stop('limit');return;}
          try{this.onChunk({buffer:event.data.buffer,sequence:count});}catch{this.stop('processing_error');return;}
          if(count===12)this.stop('limit');
        }
      };
      this.node.onprocessorerror=()=>this.stop('processing_error');
      this.source.connect(this.node);this.node.connect(this.sink);this.sink.connect(context.destination);
      await context.resume();if(ticket!==this.version)return;
      this.report('active');this.timer=this.schedule(()=>this.stop('limit'),120000);
    } catch(error){if(ticket!==this.version)return;this.cleanup();this.report('error',error.name==='NotAllowedError'?'permission_denied':error.message);}
  }
  cleanup(){
    if(this.timer!==null)this.clear(this.timer);this.timer=null;
    for(const [track,listener] of this.listeners)track.removeEventListener('ended',listener);this.listeners=[];
    if(this.node){this.node.port.onmessage=null;this.node.port.postMessage('stop');this.node.disconnect();this.node=null;}
    this.source?.disconnect();this.source=null;this.sink?.disconnect();this.sink=null;
    this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;
    if(this.context){this.context.close().catch(()=>{});this.context=null;}
  }
  stop(reason='stopped'){++this.version;this.cleanup();this.onLevel(0);this.report('idle',reason);}
}

export class ChunkQueue {
  constructor({send,onResult,onError,maxPending=1}){Object.assign(this,{send,onResult,onError,maxPending});this.version=0;this.pending=[];this.controller=null;this.running=false;}
  push(value){if(this.running&&this.pending.length>=this.maxPending){this.onError('backpressure');this.clear();return false;}this.pending.push(value);this.drain();return true;}
  async drain(){if(this.running||!this.pending.length)return;this.running=true;const ticket=this.version;this.controller=new AbortController();const value=this.pending.shift();try{const result=await this.send(value,this.controller.signal);if(ticket===this.version)this.onResult(result);}catch(error){if(ticket===this.version)this.onError(error.message||'provider_failed');}finally{if(ticket===this.version){this.running=false;this.controller=null;this.drain();}}}
  clear(){++this.version;this.controller?.abort();this.controller=null;this.pending=[];this.running=false;}
}
