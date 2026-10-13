import {SilenceGate} from './kilas_learning_engine.mjs?v=learning-continuity-v6-20261013';

// Server owns the paid WebSocket. This client sends PCM as the learner speaks,
// never a completed recording, never a provider API key or a reusable token.
export class RealtimeMic {
  constructor({api,session,id,openMicrophone,onOpened,now=()=>performance.now(),setTimer=(fn,ms)=>globalThis.setTimeout(fn,ms),clearTimer=timer=>globalThis.clearTimeout(timer)}) {
    Object.assign(this,{api,session,id,openMicrophone,onOpened,now,setTimer,clearTimer});this.generation=0;
  }
  async permission(signal){
    this.permissionController?.abort();const control=new AbortController();this.permissionController=control;
    const abort=()=>control.abort();signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
    try{const stop=await this.openMicrophone(null,control.signal);stop();}
    finally{signal?.removeEventListener('abort',abort);}
  }
  async start(onResult,onError){
    this.cancel();const ticket=this.generation;this.onResult=onResult;this.onError=onError;this.queue=[];this.pre=[];this.index=0;this.turn=null;this.finishing=false;this.open=false;this.pumping=false;
    this.controller=new AbortController();this.gate=new SilenceGate(this.now);this.firstSpeech=null;
    this.idle=this.setTimer(()=>this.fail('Belum terdengar ucapan. Mikrofon dijeda tanpa membuka stream berbayar.'),15000);
    const stop=await this.openMicrophone(chunk=>this.chunk(chunk,ticket),this.controller.signal);
    if(ticket!==this.generation||this.finishing){stop();return;}this.stopMicrophone=stop;
  }
  chunk({pcm,rms},ticket){
    if(ticket!==this.generation||this.finishing)return;
    const end=this.gate.sample(rms);
    if(!this.turn){
      this.pre.push(pcm);if(this.pre.length>4)this.pre.shift();
      if(!this.gate.spoke)return;
      this.clearTimer(this.idle);this.firstSpeech=this.now();this.turn='learn-'+this.id();this.onOpened(this.turn);
      this.queue.push(...this.pre);this.pre=[];
      const sid=this.session(),turn=this.turn;
      this.api.begin(sid,turn,this.controller.signal).then(()=>{if(ticket!==this.generation)return;this.open=true;void this.pump(ticket);}).catch(error=>{if(ticket===this.generation)this.fail(error.message);});
    }else this.queue.push(pcm);
    if(this.queue.length>12){this.fail('Pengiriman audio tertunda terlalu lama. Stream dijeda tanpa mengulang audio.');return;}
    if(end||this.now()-this.firstSpeech>=23000){
      this.finishing=true;this.stopMicrophone?.();this.stopMicrophone=null;
    }
    if(this.open)void this.pump(ticket);
  }
  async pump(ticket){
    if(this.pumping||ticket!==this.generation)return;this.pumping=true;
    try{
      while(this.queue.length&&ticket===this.generation){
        // Coalesce only PCM already captured: 1–4 quarter-second frames per ACK.
        // This drains normal HTTP round-trip latency without waiting for a whole
        // recording, changing sample order, retries, or the three-second queue cap.
        const parts=this.queue.splice(0,4),pcm=new Uint8Array(parts.reduce((n,part)=>n+part.length,0));let offset=0;
        for(const part of parts){pcm.set(part,offset);offset+=part.length;}
        await this.api.chunk(this.session(),this.turn,this.index++,pcm,this.controller.signal);
      }
      if(this.finishing&&ticket===this.generation){
        const state=await this.api.commit(this.session(),this.turn,this.controller.signal);
        if(ticket!==this.generation)return;
        this.turn=null;this.cancel();this.onResult(state);
      }
    }catch(error){if(ticket===this.generation)this.fail(error.message);}
    finally{if(ticket===this.generation)this.pumping=false;}
  }
  fail(message){this.cancel();this.onError?.(message||'Stream terputus. Tekan Lanjutkan; rekaman tidak dikirim ulang.');}
  cancel(){
    ++this.generation;this.permissionController?.abort();this.controller?.abort();this.clearTimer(this.idle);this.stopMicrophone?.();this.stopMicrophone=null;this.queue=[];this.pre=[];
    const turn=this.turn;this.turn=null;
    if(turn)void this.api.cancel(this.session(),turn).catch(()=>{});
  }
}

export async function microphone(onChunk,signal){
  if(!navigator.mediaDevices?.getUserMedia||!window.AudioWorkletNode)throw Error('Mikrofon streaming belum didukung. Gunakan Chrome atau Safari terbaru.');
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
  let context,input,node,gain,stopped=false;
  const stop=()=>{if(stopped)return;stopped=true;signal?.removeEventListener('abort',stop);stream.getTracks().forEach(t=>t.stop());if(node)node.port.onmessage=null;input?.disconnect();node?.disconnect();gain?.disconnect();if(context)void context.close().catch(()=>{});};
  const check=()=>{if(signal?.aborted||stopped){stop();throw new DOMException('Aborted','AbortError');}};
  signal?.addEventListener('abort',stop,{once:true});check();
  if(!onChunk)return stop;
  try{
    context=new(window.AudioContext||window.webkitAudioContext)({sampleRate:16000});
    await context.audioWorklet.addModule(new URL('./kilas_learning_pcm_worklet.mjs',import.meta.url));check();await context.resume();check();
    input=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'kilas-learning-pcm');gain=context.createGain();gain.gain.value=0;
    node.port.onmessage=event=>onChunk({pcm:new Uint8Array(event.data.pcm),rms:event.data.rms});input.connect(node).connect(gain).connect(context.destination);
    return stop;
  }catch(error){stop();throw error;}
}
