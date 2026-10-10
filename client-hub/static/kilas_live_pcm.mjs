// Standalone mono PCM WAV files, rather than non-independent WebM timeslices.
export function wav16(samples,rate=16000) {
  const buffer=new ArrayBuffer(44+samples.length*2),v=new DataView(buffer);
  const ascii=(at,value)=>[...value].forEach((c,i)=>v.setUint8(at+i,c.charCodeAt(0)));
  ascii(0,'RIFF');v.setUint32(4,36+samples.length*2,true);ascii(8,'WAVE');ascii(12,'fmt ');
  v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);
  v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);ascii(36,'data');v.setUint32(40,samples.length*2,true);
  samples.forEach((s,i)=>v.setInt16(44+i*2,s,true));return buffer;
}

export class PCMChunks {
  constructor({rate=16000,seconds=10,emit,meter}) {Object.assign(this,{rate,seconds,emit,meter});this.samples=new Int16Array(rate*seconds);this.at=0;this.phase=0;this.peak=0;this.meterAt=0;}
  push(channels,inputRate) {
    if(!channels.length)return;
    for(let i=0;i<channels[0].length;i++) {
      let value=0;for(const channel of channels)value+=channel[i]||0;value/=channels.length;
      this.peak=Math.max(this.peak,Math.abs(value));this.phase+=this.rate;
      if(this.phase>=inputRate) {
        this.phase-=inputRate;const clipped=Math.max(-1,Math.min(1,value));this.samples[this.at++]=Math.round(clipped*(clipped<0?32768:32767));
        if(++this.meterAt>=3200){this.meter?.(Math.min(1,this.peak));this.meterAt=0;this.peak=0;}
        if(this.at===this.samples.length){const buffer=wav16(this.samples,this.rate);this.at=0;this.emit(buffer);}
      }
    }
  }
  clear(){this.samples.fill(0);this.at=0;this.phase=0;this.peak=0;}
}
