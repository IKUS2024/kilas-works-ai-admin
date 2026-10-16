// Conservative local reference check, in addition to browser echo cancellation.
// Only a near-identical delayed/scaled playback frame is classified as echo.
// Uncertain or mixed speech is retained; this is not a device-AEC guarantee.
const RATE=16000,SOURCE_RATE=24000,DELAY=.6,CANDIDATES=8,PROBES=128,RADIUS=8,PHASES=1024;
const kernels=new Map();
function interpolate(samples,at){
 let left=Math.floor(at),phase=Math.round((at-left)*PHASES);
 if(phase===PHASES){left++;phase=0;}if(!phase)return samples[left]||0;
 let weights=kernels.get(phase);
 if(!weights){
  weights=new Float64Array(RADIUS*2);let sum=0;
  for(let i=0;i<weights.length;i++){const distance=phase/PHASES-(i-RADIUS+1),angle=Math.PI*distance;weights[i]=Math.sin(angle)/angle*Math.sin(angle/RADIUS)/(angle/RADIUS);sum+=weights[i];}
  for(let i=0;i<weights.length;i++)weights[i]/=sum;kernels.set(phase,weights);
 }
 let value=0;for(let i=0;i<weights.length;i++)value+=(samples[left+i-RADIUS+1]||0)*weights[i];return value;
}
export class PlaybackEcho {
 constructor({getContext}){this.getContext=getContext;this.reset();}
 reset(){this.segments=[];}
 remember(buffer,at){
  if(buffer.sampleRate!==SOURCE_RATE)return;
  const values=buffer.getChannelData(0);
  const now=this.getContext()?.currentTime||0;
  this.segments=this.segments.filter(item=>item.at+item.values.length/SOURCE_RATE>=now-1);
  this.segments.push({at,values});
 }
 hold(at){
  this.segments=this.segments.filter(item=>item.at<at).map(item=>({at:item.at,values:item.values.subarray(0,Math.max(0,Math.min(item.values.length,Math.floor((at-item.at)*SOURCE_RATE))))}));
 }
 matches(raw){
  const context=this.getContext();if(!context||!this.segments.length||raw.length<32)return false;
  const count=Math.floor(raw.length/2),input=new Float32Array(count),view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);
  let energy=0;
  for(let i=0;i<count;i++){input[i]=view.getInt16(i*2,true)/32768;energy+=input[i]**2;}
  if(energy/count<.003**2)return false;
  const delay=Math.ceil(DELAY*RATE),start=context.currentTime-count/RATE-DELAY;
  const source=new Float32Array(Math.ceil((count+delay)*SOURCE_RATE/RATE)+RADIUS*2+2),sourceStart=start-RADIUS/SOURCE_RATE;
  for(const item of this.segments){
   const offset=Math.round((item.at-sourceStart)*SOURCE_RATE),first=Math.max(0,-offset),last=Math.min(item.values.length,source.length-offset);
   if(last>first)source.set(item.values.subarray(first,last),offset+first);
  }
  if(!source.some(value=>value!==0))return false;
  // Web Audio resamples24k playback before the microphone's weighted16k
  // encoder. Reconstruct the bounded source window at that context rate,
  // then apply the same fixed averaging; coarse4k means lose this waveform.
  const captureRate=Number.isFinite(context.sampleRate)&&context.sampleRate>=RATE&&context.sampleRate<=96000?context.sampleRate:RATE;
  const ratio=captureRate/RATE,reference=new Float32Array(count+delay);
  for(let i=0;i<reference.length;i++){
   const first=i*ratio,last=(i+1)*ratio;let value=0;
   for(let j=Math.floor(first);j<last;j++){const weight=Math.min(last,j+1)-Math.max(first,j);value+=interpolate(source,RADIUS+j*SOURCE_RATE/captureRate)*weight;}
   reference[i]=value/ratio;
  }
  // Rank sample-resolution delays cheaply without averaging away frequencies.
  // These probes only select candidates; every accepted match is checked
  // against every original16k sample below, including quieter mixed speech.
  const probes=[],size=Math.min(PROBES,count);
  for(let i=0;i<size;i++)probes.push(Math.min(count-1,Math.floor((i+((i*37)%127)/127)*count/size)));
  const candidates=[],total=probes.reduce((sum,i)=>sum+input[i]**2,0);
  for(let offset=0;offset<=delay;offset++){
   let dot=0,other=0;
   for(const i of probes){const value=reference[offset+i];dot+=input[i]*value;other+=value**2;}
   if(other<1e-8||dot<=0)continue;
   const score=Math.max(0,total-dot*dot/other);
   if(candidates.length<CANDIDATES||score<candidates.at(-1).score){candidates.push({offset,score});candidates.sort((a,b)=>a.score-b.score);if(candidates.length>CANDIDATES)candidates.pop();}
  }
  const aligned=new Set(candidates.flatMap(({offset})=>offset?[offset-1,offset]:[offset]));
  for(const offset of aligned){
   let dot=0,other=0,nextDot=0,nextEnergy=0,cross=0;
   for(let i=0;i<count;i++){const value=reference[offset+i],next=offset<delay?reference[offset+i+1]:value;dot+=input[i]*value;other+=value**2;nextDot+=input[i]*next;nextEnergy+=next**2;cross+=value*next;}
   if(other<1e-8||dot<=0)continue;
   let gain=dot/other,explained=dot*dot/other;
   // A nonnegative adjacent-sample blend permits a fractional sample delay.
   // It still has to explain the full waveform within the same .003RMS floor.
   const determinant=other*nextEnergy-cross*cross;
   if(determinant>other*nextEnergy*1e-10){
    const first=(dot*nextEnergy-nextDot*cross)/determinant,second=(nextDot*other-dot*cross)/determinant;
    if(first>=0&&second>=0){gain=first+second;explained=first*dot+second*nextDot;}
   }
   const residual=Math.max(0,(energy-explained)/count);
   if(gain>=.05&&gain<=10&&explained/energy>=.96&&residual<.003**2)return true;
  }
  return false;
 }
}
