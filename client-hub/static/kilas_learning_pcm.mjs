// Continuous mono downsampling: phase carries across worklet buffers.
export class PCMEncoder {
  constructor(rate,frames=4000){this.rate=rate;this.frames=frames;this.phase=0;this.sum=0;this.count=0;this.output=[];}
  push(samples){
    const chunks=[];
    for(const value of samples){
      this.sum+=value;this.count++;this.phase+=16000;
      if(this.phase>=this.rate){const sample=Math.max(-1,Math.min(1,this.sum/this.count));this.output.push(Math.round(sample*(sample<0?32768:32767)));this.phase-=this.rate;this.sum=0;this.count=0;}
      if(this.output.length===this.frames){chunks.push(this.pack());}
    }
    return chunks;
  }
  pack(){const pcm=new Uint8Array(this.output.length*2),view=new DataView(pcm.buffer);let power=0;
    this.output.forEach((sample,index)=>{view.setInt16(index*2,sample,true);power+=(sample/32768)**2;});
    const rms=Math.sqrt(power/this.output.length);this.output=[];return {pcm,rms};
  }
}
