// Each utterance is submitted once. Recovery cancels that key, never regenerates it.
const aborted=()=>new DOMException('Sesi dijeda.','AbortError');
const error=(code,message)=>Object.assign(Error(message),{code});

// Window timers need their native receiver, even when stored on an adapter instance.
const scheduleNative=(fn,ms)=>globalThis.setTimeout(fn,ms);
const clearNative=id=>globalThis.clearTimeout(id);

export async function requestJSON(url,{csrf,fetcher=(...args)=>fetch(...args),schedule=scheduleNative,clear=clearNative,...options}){
  const {signal,timeoutMs=15000,...rest}=options,controller=new AbortController();
  if(signal?.aborted)throw aborted();
  return new Promise((resolve,reject)=>{
    let settled=false;
    const finish=(fn,value)=>{if(settled)return;settled=true;clear(timer);signal?.removeEventListener('abort',cancel);fn(value);};
    const cancel=()=>{finish(reject,aborted());controller.abort();};
    const timer=schedule(()=>{finish(reject,error('request_timeout','Koneksi belum merespons. Ucapan ini tidak diulang otomatis.'));controller.abort();},timeoutMs);
    signal?.addEventListener('abort',cancel,{once:true});
    (async()=>{
      try{
        const response=await fetcher(url,{...rest,signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':csrf}});
        if(controller.signal.aborted)return;
        if(response.redirected)throw error('auth_required','Sesi akun berakhir. Masuk kembali.');
        let body;try{body=await response.json();}catch{throw error('response_invalid','Layanan belum merespons dengan benar. Ucapan ini tidak diulang otomatis.');}
        if(!response.ok){const failure=error(body.code||(response.status===401||response.status===403?'auth_required':'request_failed'),body.error||'Layanan belum tersedia.');failure.status=response.status;throw failure;}
        finish(resolve,body);
      }catch(e){finish(reject,e);}
    })();
  });
}

export class TranslatorTurns {
  constructor({json,csrf,now=()=>performance.now(),schedule=scheduleNative,clear=clearNative,pollMs=250,turnMs=180000}){
    Object.assign(this,{json,csrf,now,schedule,clear,pollMs,turnMs});
  }
  path(id,key){return '/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/turns/'+encodeURIComponent(key);}
  pause(signal){return new Promise((resolve,reject)=>{
    const cancel=()=>{this.clear(timer);signal.removeEventListener('abort',cancel);reject(aborted());};
    const timer=this.schedule(()=>{signal.removeEventListener('abort',cancel);resolve();},this.pollMs);signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
  });}
  cancel(id,key){const data=new FormData();data.append('csrf_token',this.csrf);return this.json(this.path(id,key)+'/cancel',{method:'POST',body:data,timeoutMs:10000,keepalive:true});}
  async resume(id,key,signal){
    if(key){await this.cancel(id,key);if(signal.aborted)throw aborted();}
    const state=await this.json('/kilas-translator/live/sessions/'+encodeURIComponent(id),{signal,timeoutMs:10000});
    if(state.status!=='ACTIVE')throw error('session_ended','Sesi ini sudah diakhiri. Tekan End untuk menutup tampilan ini.');
    if(state.processing)throw error('turn_busy','Ucapan sebelumnya belum terkonfirmasi selesai. Periksa lagi saat koneksi siap.');
  }
  async turn(id,key,blob,signal,onSegment=null){
    const url=this.path(id,key),data=new FormData();data.append('recording',blob,'recording');data.append('csrf_token',this.csrf);
    // A definite unsupported endpoint disables streaming for NEW speech in this
    // session. An uncertain paid request never triggers an alternate submission.
    if(this.disabledStreamSession===id)onSegment=null;
    if(onSegment)data.append('stream_output','sentences-v1');let played=0,announced=null;const identities=[];
    const controller=new AbortController(),cancel=()=>controller.abort();signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
    try{
      await this.json(url,{method:'POST',body:data,signal:controller.signal,timeoutMs:30000});const deadline=this.now()+this.turnMs;let playbackMs=0;
      while(!controller.signal.aborted){
        const result=await this.json(url,{signal:controller.signal,timeoutMs:15000});
        if(onSegment&&result.stream_output==='sentences-v1'&&['PROCESSING','COMPLETED'].includes(result.status)){
          let newlyPlayed=false,totalMs=0;
          if(!Number.isInteger(result.total_segments)||result.total_segments<1||result.total_segments>8||!Array.isArray(result.segments)||result.segments.length>result.total_segments||result.segments.length<played)throw error('stream_invalid','Urutan audio tidak valid.');
          if(announced!==null&&announced!==result.total_segments)throw error('stream_invalid','Jumlah segmen berubah.');announced=result.total_segments;
          for(let index=0;index<result.segments.length;index++){
            const part=result.segments[index];
            if(part.index!==index||part.audio_url!==url+'/audio/segments/'+index||!Number.isInteger(part.duration_ms)||part.duration_ms<=0||part.duration_ms>600000||typeof part.translated_text!=='string'||part.translated_text.length>4000)throw error('stream_invalid','Segmen audio tidak valid.');
            totalMs+=part.duration_ms;if(totalMs>600000)throw error('stream_invalid','Audio melebihi batas durasi.');
            const identity=JSON.stringify([part.audio_url,part.duration_ms,part.translated_text]);
            if(identities[index]&&identities[index]!==identity)throw error('stream_invalid','Segmen audio berubah.');identities[index]=identity;
          }
          for(let index=played;index<result.segments.length;index++){
            const part=result.segments[index];if(controller.signal.aborted)throw aborted();
            const began=this.now();try{await onSegment(part);}catch(e){e.segmentPlayback=true;throw e;}finally{playbackMs+=Math.max(0,this.now()-began);}
            if(controller.signal.aborted)throw aborted();played++;
            newlyPlayed=true;
          }
          if(result.status==='COMPLETED'){
            if(played!==result.total_segments)throw error('stream_invalid','Audio belum lengkap.');
            return {...result,streamed:true};
          }
          // Playback may outlive the old PROCESSING snapshot. Re-read completion
          // before timing out; audio already heard is never replayed.
          if(newlyPlayed)continue;
        }else if(result.status==='COMPLETED')return result;
        if(result.status==='FAILED'){
          if(result.code==='stream_unavailable')this.disabledStreamSession=id;
          const failure=error(result.code||'processing_failed',result.error||'Ucapan belum berhasil diproses.');
          failure.recoverable=Boolean(result.recoverable);failure.turnSettled=result.code!=='processing_interrupted';throw failure;
        }
        if(result.status==='CANCELLED')throw error('turn_cancelled','Ucapan ini dibatalkan dan tidak diulang otomatis.');
        if(this.now()>=deadline+playbackMs)throw error('turn_timeout','Ucapan ini belum selesai. Silakan bicara kembali setelah pemulihan.');
        await this.pause(controller.signal);
      }
      throw aborted();
    }catch(e){
      if(signal.aborted)throw e;
      // Confirm a scoped cancellation/tombstone before allowing another recording.
      if(!e.turnSettled){
        try{
          const state=await this.cancel(id,key);if(signal.aborted)throw aborted();
          if(!['CANCELLED','FAILED','COMPLETED'].includes(state.status))throw error('cancel_unconfirmed','Pembatalan ucapan belum terkonfirmasi.');
          if(state.status==='COMPLETED'&&!e.segmentPlayback&&!played){
            const completed=await this.json(url,{signal:controller.signal,timeoutMs:15000});
            if(completed.status==='COMPLETED')return completed;
          }
          if(state.status==='FAILED'){
            const failed=await this.json(url,{signal:controller.signal,timeoutMs:15000});
            if(failed.status!=='FAILED')throw error('cancel_unconfirmed','Status ucapan belum terkonfirmasi.');
            e.code=failed.code||'processing_failed';e.message=failed.error||'Ucapan belum berhasil diproses.';e.recoverable=Boolean(failed.recoverable);
            if(e.code==='stream_unavailable')this.disabledStreamSession=id;
          }
          e.turnSettled=true;
          if(['request_timeout','response_invalid','turn_timeout','turn_cancelled','service_busy'].includes(e.code)||!e.code)e.recoverable=true;
        }catch{e.recoverable=false;}
      }
      throw e;
    }finally{controller.abort();signal.removeEventListener('abort',cancel);}
  }
}
