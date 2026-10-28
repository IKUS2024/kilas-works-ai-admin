import {PcmEncoder} from './kilas_live_translator_pcm.mjs';

// Retain the exact remaining PCM samples at the clip boundary, including a
// partial worklet frame. This is a duration bound, not a speech detector.
export class PcmBuffer {
  constructor(limit=60*32000){this.limit=limit;this.size=0;this.chunks=[];}
  append(bytes){
    if(!(bytes instanceof ArrayBuffer)||bytes.byteLength%2)throw Error('Invalid PCM frame');
    const count=Math.min(bytes.byteLength,this.limit-this.size);
    if(count){this.chunks.push(bytes.slice(0,count));this.size+=count;}
  }
}

export class CopilotCapture {
  constructor(stream,context,onFrame){
    this.stream=stream;this.context=context;this.onFrame=onFrame;this.closed=false;this.stopped=false;
  }
  stopTracks(){if(!this.stopped){this.stopped=true;this.stream.getTracks().forEach(t=>t.stop());}}
  async start(){
    await this.context.resume();if(this.closed)throw Error('cancelled');
    this.source=this.context.createMediaStreamSource(this.stream);
    this.gain=this.context.createGain();this.gain.gain.value=0;
    if(this.context.audioWorklet&&globalThis.AudioWorkletNode){
      let timeout;
      try{
        await Promise.race([this.context.audioWorklet.addModule(new URL('./kilas_live_translator_pcm.mjs',import.meta.url)),new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('worklet_timeout')),5000);})]);
        if(this.closed)throw Error('cancelled');
        this.node=new AudioWorkletNode(this.context,'kilas-pcm',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1],processorOptions:{frameSamples:1600}});
        this.node.port.onmessage=({data})=>{
          if(this.closed)return;
          if(data.finished){this.flushed?.();return;}
          if(data.bytes)this.onFrame(data);
        };
        this.node.onprocessorerror=()=>this.failed?.(Error('microphone'));
        this.worklet=true;
      }catch(error){if(this.closed)throw error;}finally{clearTimeout(timeout);}
    }
    if(!this.node){
      this.encoder=new PcmEncoder(this.context.sampleRate,frame=>{if(!this.closed)this.onFrame(frame);},1600);
      this.node=this.context.createScriptProcessor(2048,1,1);
      this.node.onaudioprocess=event=>{
        if(this.closed||this.stopped)return;
        try{this.encoder.feed([event.inputBuffer.getChannelData(0)]);}catch{this.failed?.(Error('microphone'));}
      };
    }
    if(this.closed)throw Error('cancelled');
    this.source.connect(this.node);this.node.connect(this.gain);this.gain.connect(this.context.destination);
  }
  async finish(){
    if(this.closed)throw Error('cancelled');
    // Stop physical capture immediately; queued worklet frames precede its FIFO
    // finished acknowledgement. A failed flush never uploads a truncated clip.
    this.stopTracks();
    if(!this.worklet){this.encoder.finish();return;}
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>done(Error('microphone')),3000);
      const done=error=>{clearTimeout(timer);this.flushed=null;this.rejectFlush=null;error?reject(error):resolve();};
      this.flushed=()=>done();this.rejectFlush=done;
      this.node.port.postMessage({finish:true});
    });
  }
  close(){
    if(this.closed)return;this.closed=true;this.stopTracks();this.rejectFlush?.(Error('cancelled'));
    if(this.node){this.node.onaudioprocess=null;this.node.onprocessorerror=null;if(this.node.port)this.node.port.onmessage=null;this.node.disconnect();}
    this.source?.disconnect();this.gain?.disconnect();this.context.close().catch(()=>{});
  }
}
