import {PCMChunks} from './kilas_live_pcm.mjs';
class TabPCM extends AudioWorkletProcessor {
  constructor(){super();this.active=true;this.chunks=new PCMChunks({emit:buffer=>this.port.postMessage({kind:'chunk',buffer},[buffer]),meter:level=>this.port.postMessage({kind:'level',level})});this.port.onmessage=()=>{this.active=false;this.chunks.clear();};}
  process(inputs,outputs){for(const channel of outputs[0]||[])channel.fill(0);if(!this.active)return false;this.chunks.push(inputs[0]||[],sampleRate);return true;}
}
registerProcessor('kilas-tab-pcm',TabPCM);
