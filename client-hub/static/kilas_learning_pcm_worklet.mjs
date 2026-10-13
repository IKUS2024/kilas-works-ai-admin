import {PCMEncoder} from './kilas_learning_pcm.mjs';
class LearningPCM extends AudioWorkletProcessor {
  constructor(){super();this.encoder=new PCMEncoder(sampleRate);}
  process(inputs){const channel=inputs[0]?.[0];if(channel)for(const {pcm,rms}of this.encoder.push(channel))this.port.postMessage({pcm:pcm.buffer,rms},[pcm.buffer]);return true;}
}
registerProcessor('kilas-learning-pcm',LearningPCM);
