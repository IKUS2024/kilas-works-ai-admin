import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
// Pure, injectable session state. No microphone/network work merely on import.
const startupFailure=(value,stage)=>{
  const error=value instanceof Error?value:Error(typeof value==='string'&&value?value:t('Persiapan sesi belum berhasil. Periksa izin browser dan koneksi lalu coba kembali.'));
  error.code??=stage+'_failed';error.startupStage??=stage;return error;
};
export class SilenceGate {
  constructor({silenceMs=2000,threshold=.015}={}){this.silenceMs=silenceMs;this.threshold=threshold;this.reset();}
  reset(){this.lastVoice=null;this.finalized=false;}
  sample(rms,now){
    if(this.finalized)return false;
    if(rms>=this.threshold){this.lastVoice=now;return false;}
    if(this.lastVoice!==null&&now-this.lastVoice>=this.silenceMs){this.finalized=true;return true;}
    return false;
  }
}

export class TranslatorSession {
  constructor({api,capture,playback,pushToTalk=false,onState=()=>{},onResult=()=>{},onError=()=>{},onTiming=()=>{},now=()=>performance.now(),key=()=>crypto.randomUUID().replaceAll('-',''),schedule=(fn,ms)=>globalThis.setTimeout(fn,ms),clear=id=>globalThis.clearTimeout(id)}){
    Object.assign(this,{api,capture,playback,pushToTalk,onState,onResult,onError,onTiming,now,key,schedule,clear});this.version=0;this.captureVersion=0;this.state='ended';this.id=null;this.pendingKey=null;this.gate=new SilenceGate();this.suspended=false;
  }
  stateTo(state){this.state=state;this.onState(state);}
  report(error){try{this.onError(error.message,error);}catch{}}
  timing(values){try{this.onTiming(values);}catch{}}
  startup(ticket,stage,work,ms,message,onLate=()=>{}){
    const signal=this.controller.signal;
    return new Promise((resolve,reject)=>{
      let settled=false;
      const finish=(fn,value)=>{if(settled)return;settled=true;try{this.clear(timer);}catch{}signal.removeEventListener('abort',cancel);fn(value);};
      const cancel=()=>finish(reject,new DOMException(t('Sesi berakhir.'),'AbortError'));
      const timer=this.schedule(()=>finish(reject,Object.assign(Error(message),{code:stage+'_timeout',startupStage:stage})),ms);
      signal.addEventListener('abort',cancel,{once:true});
      if(signal.aborted||ticket!==this.version){cancel();return;}
      // Invoke now so AudioContext.resume remains inside the Start/Resume gesture.
      try{Promise.resolve(work()).then(value=>{
        if(settled||ticket!==this.version){try{Promise.resolve(onLate(value)).catch(()=>{});}catch{}return;}
        finish(resolve,value);
      },e=>finish(reject,startupFailure(e,stage)));}catch(e){finish(reject,startupFailure(e,stage));}
    });
  }
  endAdmitted(result){if(typeof result?.session_id==='string'&&/^[a-f0-9]{48}$/.test(result.session_id)){try{return Promise.resolve(this.api.end(result.session_id)).catch(()=>{});}catch{}}}
  async start(params){
    if(this.state!=='ended')return;
    const ticket=++this.version;this.suspended=false;this.controller=new AbortController();this.params=params;
    try{
      this.stateTo('preparing');
      if(this.playback.prepare)await this.startup(ticket,'audio_prepare',()=>this.playback.prepare(this.controller.signal,()=>ticket===this.version),6000,t('Audio belum siap. Periksa izin audio browser lalu tekan Start kembali.'));
      if(ticket!==this.version)return;
      this.stateTo('starting');
      this.admissionPending=ticket;
      let result;try{result=await this.startup(ticket,'session_admission',()=>this.api.start(params,this.controller.signal),32000,t('Status sesi belum terkonfirmasi. Periksa sesi saat jaringan siap sebelum memulai kembali.'),value=>this.endAdmitted(value));}finally{if(this.admissionPending===ticket)this.admissionPending=false;}
      if(ticket!==this.version){await this.endAdmitted(result);return;}
      if(typeof result?.session_id!=='string'||!(/^[a-f0-9]{48}$/).test(result.session_id))throw Object.assign(Error(t('Layanan tidak mengembalikan sesi yang valid. Periksa sesi sebelum memulai kembali.')),{code:'session_response_invalid',startupStage:'session_admission'});
      this.id=result.session_id;this.inputMode=result.input_mode==='realtime-v1'?'realtime-v1':'batch';if(this.suspended){this.pause(Error(t('Sesi dijeda saat halaman ditinggalkan. Tekan Lanjutkan.')));return;}await this.listen(ticket);
    }catch(e){if(ticket===this.version){e=startupFailure(e,this.id?'microphone_start':'audio_prepare');if(this.id)this.pause(e);else {this.report(e);this.end();}}}
  }
  async listen(ticket,held=false){
    if(ticket!==this.version)return;
    if(this.pushToTalk&&!held){this.held=false;this.stateTo('ready');return;}
    const cycle=++this.captureVersion,current=()=>ticket===this.version&&cycle===this.captureVersion;
    this.gate.reset();this.stateTo('opening');
    if(this.inputMode==='realtime-v1')this.api.input.reset();
    await this.startup(ticket,'microphone_start',()=>this.capture.start({
      inputMode:this.inputMode,
      ready:()=>{if(current()&&this.state==='opening')this.stateTo('listening');},
      level:rms=>{if(this.pushToTalk){if(current()&&rms>=this.gate.threshold){this.hadVoice=true;this.gate.lastVoice=this.now();}return;}if(current()&&this.state==='listening'&&this.gate.sample(rms,this.now())){this.stateTo('finalizing');this.capture.finalize();}},
      pcm:bytes=>{
        if(!current()||this.inputMode!=='realtime-v1'||!['listening','finalizing'].includes(this.state))return;
        if(!this.pendingKey)this.pendingKey='live-'+this.key();
        this.api.input.push(this.id,this.pendingKey,bytes,this.controller.signal).catch(e=>{if(current())this.recover(e,ticket);});
      },
      blob:blob=>{if(current())this.utterance(blob,ticket);},
      error:e=>{if(current())this.recover(e,ticket);},
    }),45000,t('Mikrofon belum siap. Periksa izin mikrofon lalu tekan Lanjutkan.'));
    if(current()&&this.state==='opening')this.stateTo('listening');
    // The adapter owns late permission cleanup; never cancel a newer session here.
  }
  async press(){
    if(!this.pushToTalk||this.state!=='ready'||!this.id)return;
    const ticket=this.version;this.held=true;this.hadVoice=false;
    try{await this.listen(ticket,true);}
    catch(error){if(ticket===this.version&&this.held)this.pause(error);}
  }
  release({cancel=false}={}){
    if(!this.pushToTalk||!this.held)return;
    this.held=false;
    if(this.state==='opening'||cancel||(!this.hadVoice&&!this.pendingKey)){
      ++this.captureVersion;try{this.capture.cancel();}catch{}
      if(this.pendingKey){this.recover(Object.assign(Error(''),{code:'capture_cancelled',recoverable:true}),this.version);}
      else this.stateTo('ready');
      return;
    }
    if(this.state==='listening'){this.stateTo('finalizing');this.capture.finalize();}
  }
  async utterance(blob,ticket){
    if(ticket!==this.version||this.state!=='finalizing')return;
    // Capture adapter releases every mic track before delivering the blob.
    // Retire its callbacks now: a queued device error from the disposed capture
    // must not interrupt this accepted utterance's processing or playback.
    ++this.captureVersion;
    this.stateTo('processing');
    try{
      const realtime=this.inputMode==='realtime-v1';
      if(realtime?!this.pendingKey:!blob?.size){const error=Error(t('Rekaman kosong. Silakan bicara kembali.'));error.code='no_speech';throw error;}
      if(!realtime)this.pendingKey='live-'+this.key();
      const speechEnd=this.gate.lastVoice??this.now();let first=false,previousClipEnd=null;
      this.timing({speech_end_to_submit_ms:Math.max(0,this.now()-speechEnd)});
      const onStarted=()=>{if(first||ticket!==this.version)return;first=true;this.timing({speech_end_to_first_playback_ms:Math.max(0,this.now()-speechEnd)});};
      if(realtime){
        const finalizeBegan=this.now();
        await this.api.input.finish(this.id,this.pendingKey,this.controller.signal,()=>this.timing({speech_end_to_commit_request_ms:Math.max(0,this.now()-speechEnd)}));
        this.timing({input_finalize_ms:Math.max(0,this.now()-finalizeBegan)});
      }
      const outputBegan=this.now();
      const result=await this.api.turn(this.id,this.pendingKey,blob,this.controller.signal,async (part,playSignal=this.controller.signal)=>{
        if(ticket!==this.version||this.controller.signal.aborted)throw new DOMException(t('Sesi dijeda.'),'AbortError');
        this.onResult(part);this.stateTo('playing');
        await this.playback.play(part.audio_url,playSignal,()=>ticket===this.version,info=>{
          onStarted();
          if(ticket===this.version&&previousClipEnd!==null){
            const gap=Math.max(0,this.now()-previousClipEnd);
            this.timing({interclip_gap_ms:gap});
            // Residual fetch/decode wait after the prior clip ended. Provider
            // publication delay and device resume are included only in gap.
            if(Number.isFinite(info?.buffer_wait_ms))this.timing({buffer_starvation_ms:Math.max(0,info.buffer_wait_ms)});
          }
        });
        if(ticket!==this.version||this.controller.signal.aborted)throw new DOMException(t('Sesi dijeda.'),'AbortError');
        previousClipEnd=this.now();this.stateTo('processing');
      },(part,playSignal)=>{
        if(ticket===this.version&&!this.controller.signal.aborted)this.playback.prefetch?.(part.audio_url,playSignal,()=>ticket===this.version);
      });
      if(ticket!==this.version)return;
      if(!result.streamed)this.timing({output_ready_ms:Math.max(0,this.now()-outputBegan)});
      this.pendingKey=null;
      this.onResult(result);
      if(!result.streamed){
        const readyAt=this.now();this.stateTo('playing');
        await this.playback.play(result.audio_url,this.controller.signal,()=>ticket===this.version,()=>{this.timing({result_to_audio_start_ms:Math.max(0,this.now()-readyAt)});onStarted();});
      }
      if(ticket!==this.version)return;
      await this.listen(ticket);
    }catch(e){
      if(ticket!==this.version||this.controller.signal.aborted)return;
      if(this.state==='playing'&&e.recoverable!==false)e.recoverable=true;
      await this.recover(e,ticket);
    }
  }
  async verify(ticket){
    if(!this.api.resume)return;
    await this.api.resume(this.id,this.pendingKey,this.controller.signal,this.params,this.inputMode,async result=>{
      if(ticket!==this.version||this.controller.signal.aborted){await this.endAdmitted(result);return;}
      if(typeof result?.session_id!=='string'||!/^[a-f0-9]{48}$/.test(result.session_id)||result.input_mode!==this.inputMode){await this.endAdmitted(result);throw Object.assign(Error(t('Input sesi berubah. Akhiri sesi lalu mulai kembali.')),{code:'input_mode_changed'});}
      this.id=result.session_id;this.pendingKey=null;
    });
  }
  async recover(error,ticket){
    if(ticket!==this.version)return;
    // Recovery owns this cycle before awaiting verification; duplicate errors
    // from the cancelled capture cannot pause or start a second recovery.
    ++this.captureVersion;
    if(error.turnSettled)this.pendingKey=null;
    try{this.capture.cancel();}catch{}try{this.playback.cancel?.();}catch{}
    if(!error.recoverable&&error.code!=='no_speech'){this.pause(error);return;}
    if(!error.silent)this.report(error);
    this.stateTo('recovering');
    try{
      if(!error.silent&&this.api.resume)await this.verify(ticket);
      if(ticket!==this.version)return;this.pendingKey=null;
      if(this.playback.recover)await this.playback.recover(error,this.controller.signal,()=>ticket===this.version);
      if(ticket!==this.version)return;await this.listen(ticket);
    }catch(e){if(ticket===this.version)this.pause(e);}
  }
  pause(error){
    if(!this.id){this.suspended=true;return;}
    this.held=false;++this.version;++this.captureVersion;this.controller?.abort();this.pauseReason=error;
    try{this.capture.cancel();}catch{}try{this.playback.cancel?.();}catch{}
    if(error?.message)this.report(error);try{this.stateTo('paused');}catch{}
  }
  suspend(){if(!['ended','paused'].includes(this.state))this.pause(Object.assign(Error(t('Sesi dijeda saat halaman ditinggalkan. Tekan Lanjutkan.')),{code:'visibility_suspend'}));}
  foreground(){if(this.state==='paused'&&(this.pauseReason?.code==='visibility_suspend'||this.pauseReason?.recoverable===true))return this.resume();}
  async resume(){
    if(this.state!=='paused'||!this.id)return;
    const ticket=++this.version;this.suspended=false;this.controller=new AbortController();this.stateTo('resuming');
    try{
      // Resume audio synchronously from the Lanjutkan click before network work.
      if(this.playback.recover)await this.startup(ticket,'audio_prepare',()=>this.playback.recover(this.pauseReason,this.controller.signal,()=>ticket===this.version),6000,t('Audio belum siap. Periksa izin audio browser lalu tekan Lanjutkan.'));
      else if(this.playback.prepare)await this.startup(ticket,'audio_prepare',()=>this.playback.prepare(this.controller.signal,()=>ticket===this.version),6000,t('Audio belum siap. Periksa izin audio browser lalu tekan Lanjutkan.'));
      if(ticket!==this.version)return;if(this.api.resume)await this.startup(ticket,'session_verify',()=>this.verify(ticket),22000,t('Status sesi belum terkonfirmasi. Periksa koneksi lalu tekan Lanjutkan.'));
      if(ticket!==this.version)return;this.pendingKey=null;await this.listen(ticket);
    }catch(e){if(ticket===this.version)this.pause(e);}
  }
  end(){
    const id=this.id;this.held=false;this.id=null;this.params=null;this.pendingKey=null;++this.version;this.controller?.abort();
    // A detached recorder/context can throw while stopping. Continue every cleanup
    // and owner End independently so a device error cannot trap the active UI.
    try{this.capture.cancel();}catch{}try{this.playback.stop();}catch{}try{this.stateTo('ended');}catch{}
    if(id){try{Promise.resolve(this.api.end(id)).catch(()=>{});}catch{}}
  }
}
