// Conservative local reference check, in addition to browser echo cancellation.
// Only a near-identical delayed/scaled playback frame is classified as echo.
// Uncertain or mixed speech is retained; this is not a device-AEC guarantee.
const RATE=4000,DELAY=.6;
export class PlaybackEcho {
 constructor({getContext}){this.getContext=getContext;this.reset();}
 reset(){this.segments=[];}
 remember(buffer,at){
  const samples=buffer.getChannelData(0),step=buffer.sampleRate/RATE;
  if(!Number.isInteger(step)||step<1)return;
  const values=new Float32Array(Math.floor(samples.length/step));
  for(let i=0;i<values.length;i++){let sum=0;for(let j=0;j<step;j++)sum+=samples[i*step+j];values[i]=sum/step;}
  const now=this.getContext()?.currentTime||0;
  this.segments=this.segments.filter(item=>item.at+item.values.length/RATE>=now-1);
  this.segments.push({at,values});
 }
 hold(at){
  this.segments=this.segments.filter(item=>item.at<at).map(item=>({at:item.at,values:item.values.subarray(0,Math.max(0,Math.min(item.values.length,Math.floor((at-item.at)*RATE))))}));
 }
 matches(raw){
  const context=this.getContext();if(!context||!this.segments.length||raw.length<32)return false;
  const count=Math.floor(raw.length/8),input=new Float32Array(count),view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength);
  let energy=0;
  for(let i=0;i<count;i++){let sum=0;for(let j=0;j<4;j++)sum+=view.getInt16((i*4+j)*2,true)/32768;input[i]=sum/4;energy+=input[i]**2;}
  if(energy/count<.003**2)return false;
  const delay=Math.ceil(DELAY*RATE),reference=new Float32Array(count+delay),start=context.currentTime-count/RATE-DELAY;
  for(const item of this.segments){
   const offset=Math.round((item.at-start)*RATE),first=Math.max(0,-offset),last=Math.min(item.values.length,reference.length-offset);
   if(last>first)reference.set(item.values.subarray(first,last),offset+first);
  }
  for(let offset=0;offset<=delay;offset+=20){
   let dot=0,other=0;for(let i=0;i<count;i++){const value=reference[offset+i];dot+=input[i]*value;other+=value**2;}
   if(other<1e-8||dot<=0)continue;
   const gain=dot/other;
   if(gain>=.05&&gain<=10&&dot*dot/(energy*other)>=.96)return true;
  }
  return false;
 }
}
