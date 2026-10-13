// Stateful bounded PCM16k mono encoder. No media/network merely on import.
export class PcmEncoder {
  constructor(rate,emit){
    if(!Number.isFinite(rate)||rate<16000||rate>96000)throw Error('Unsupported capture rate');
    this.ratio=rate/16000;this.remaining=this.ratio;this.sum=0;this.used=0;
    this.samples=[];this.emit=emit;this.closed=false;
  }
  sample(value){
    this.samples.push(Math.max(-32768,Math.min(32767,Math.round(value*(value<0?32768:32767)))));
    if(this.samples.length===3200)this.output();
  }
  feed(channels){
    if(this.closed)return;
    if(!Array.isArray(channels)||!channels.length||channels.length>8||channels[0].length>8192||channels.some(c=>c.length!==channels[0].length))throw Error('Invalid capture frame');
    for(let index=0;index<channels[0].length;index++){
      let value=0;for(const channel of channels){if(!Number.isFinite(channel[index]))throw Error('Invalid capture sample');value+=channel[index];}value=Math.max(-1,Math.min(1,value/channels.length));
      let available=1;
      while(available>1e-9){
        const weight=Math.min(available,this.remaining);this.sum+=value*weight;this.used+=weight;this.remaining-=weight;available-=weight;
        if(this.remaining<1e-9){this.sample(this.sum/this.used);this.remaining=this.ratio;this.sum=0;this.used=0;}
      }
    }
  }
  output(){
    if(!this.samples.length)return;const bytes=new ArrayBuffer(this.samples.length*2),view=new DataView(bytes);let sum=0;
    this.samples.forEach((value,index)=>{view.setInt16(index*2,value,true);sum+=(value/32768)**2;});
    const rms=Math.sqrt(sum/this.samples.length);this.samples=[];this.emit({bytes,rms});
  }
  finish(){if(this.closed)return;if(this.used)this.sample(this.sum/this.used);this.output();this.closed=true;}
}

// The same encoder is tested offline. Worklet output stays silent, preventing
// local microphone feedback; playback only starts after capture is detached.
if(typeof registerProcessor==='function'){
  class KilasPcm extends AudioWorkletProcessor {
    constructor(){super();this.encoder=new PcmEncoder(sampleRate,value=>this.port.postMessage(value,[value.bytes]));this.port.onmessage=event=>{if(event.data?.finish){this.encoder.finish();this.port.postMessage({finished:true});}};}
    process(inputs){if(!this.encoder.closed&&inputs[0]?.length)this.encoder.feed(inputs[0]);return !this.encoder.closed;}
  }
  registerProcessor('kilas-pcm',KilasPcm);
}
