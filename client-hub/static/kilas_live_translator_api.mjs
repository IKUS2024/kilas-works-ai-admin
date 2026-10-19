import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
// Each utterance is submitted once. Recovery cancels that key, never regenerates it.
const aborted=()=>new DOMException(t('Sesi dijeda.'),'AbortError');
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
    const timer=schedule(()=>{finish(reject,error('request_timeout',t('Koneksi belum merespons. Ucapan ini tidak diulang otomatis.')));controller.abort();},timeoutMs);
    signal?.addEventListener('abort',cancel,{once:true});
    (async()=>{
      try{
        const response=await fetcher(url,{...rest,signal:controller.signal,credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':csrf}});
        if(controller.signal.aborted)return;
        if(response.redirected)throw error('auth_required',t('Sesi akun berakhir. Masuk kembali.'));
        let body;try{body=await response.json();}catch{throw error('response_invalid',t('Layanan belum merespons dengan benar. Ucapan ini tidak diulang otomatis.'));}
        if(!response.ok){const failure=error(body.code||(response.status===401||response.status===403?'auth_required':'request_failed'),body.error||t('Layanan belum tersedia.'));failure.status=response.status;throw failure;}
        finish(resolve,body);
      }catch(e){finish(reject,e);}
    })();
  });
}

export class TranslatorTurns {
  constructor({json,csrf,now=()=>performance.now(),schedule=scheduleNative,clear=clearNative,pollMs=250,turnMs=180000,wholeUtterance=false}){
    Object.assign(this,{json,csrf,now,schedule,clear,pollMs,turnMs,wholeUtterance});
  }
  path(id,key){return '/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/turns/'+encodeURIComponent(key);}
  pause(signal){return new Promise((resolve,reject)=>{
    const cancel=()=>{this.clear(timer);signal.removeEventListener('abort',cancel);reject(aborted());};
    const timer=this.schedule(()=>{signal.removeEventListener('abort',cancel);resolve();},this.pollMs);signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
  });}
  async cancel(id,key,signal){const data=new FormData();data.append('csrf_token',this.csrf);let state=await this.json(this.path(id,key)+'/cancel',{method:'POST',body:data,timeoutMs:10000,keepalive:true});
    for(let n=0;state.input_settled===false&&n<12;n++){await this.pause(signal||new AbortController().signal);state=await this.json(this.path(id,key),{signal,timeoutMs:3000});}
    if(state.input_settled===false)throw error('cancel_unconfirmed',t('Pembatalan ucapan belum terkonfirmasi.'));return state;}
  async resume(id,key,signal,params=null,inputMode=null,onRenewed=()=>{}){
    const url='/kilas-translator/live/sessions/'+encodeURIComponent(id);
    if(key){try{await this.cancel(id,key,signal);}catch(e){if(e.code!=='session_ended')throw e;}if(signal.aborted)throw aborted();}
    const state=await this.json(url,{signal,timeoutMs:10000});
    if(state.status!=='ACTIVE'){
      if(!state.renewable||!params)throw error('session_ended',t('Sesi ini sudah diakhiri. Tekan End untuk menutup tampilan ini.'));
      const data=new FormData();for(const name of ['language_a','language_b','voice','consent'])data.append(name,params.get(name)||'');data.append('csrf_token',this.csrf);data.append('input_mode',inputMode||'');if(params.get('capture_transport'))data.append('capture_transport',params.get('capture_transport'));
      let result;
      try{result=await this.json(url+'/renew',{method:'POST',body:data,signal,timeoutMs:15000});}
      catch(e){
        if(signal.aborted||!['request_timeout','response_invalid'].includes(e.code))throw e;
        // An ambiguous renewal is a free metadata operation. Inspect its owned
        // result once; never retry the POST or re-send the old speech.
        const current=await this.json(url,{signal,timeoutMs:10000});
        if(current.status!=='ACTIVE'||current.processing)throw e;
        result={session_id:id,input_mode:inputMode};
      }
      // Deliver admission even if End raced the response, so its new ID is ended.
      await onRenewed(result);if(signal.aborted)throw aborted();return result;
    }
    if(state.processing)throw error('turn_busy',t('Ucapan sebelumnya belum terkonfirmasi selesai. Periksa lagi saat koneksi siap.'));
  }
  async turn(id,key,blob,signal,onSegment=null,onPrefetch=null,onTranslation=null,onProgressive=null){
    const url=this.path(id,key),data=new FormData();if(blob!==null)data.append('recording',blob,'recording');data.append('csrf_token',this.csrf);
    // Wait for one full result, including any already-running legacy segmented
    // turn. Never play a prefix or submit a second job to assemble its output.
    if(this.wholeUtterance)onSegment=null;
    // A definite unsupported endpoint disables streaming for NEW speech in this
    // session. An uncertain paid request never triggers an alternate submission.
    if(this.disabledStreamSession===id)onSegment=null;
    if(onSegment)data.append('stream_output','sentences-v1');let played=0,announced=null,translationIdentity=null;const identities=[];
    const controller=new AbortController(),cancel=()=>controller.abort();signal.addEventListener('abort',cancel,{once:true});if(signal.aborted)cancel();
    let completeText=null,progressiveTask=null,progressiveResult=null,progressiveError=null;
    const textIdentity=result=>{
      if(typeof result.translated_text!=='string'||!result.translated_text.trim()||result.translated_text.length>4000||typeof result.source_text!=='string'||!result.source_text.trim()||result.source_text.length>4000||typeof result.source_language!=='string'||typeof result.target_language!=='string'||!result.source_language||!result.target_language||result.source_language===result.target_language||result.translation_key!==key)throw error('stream_invalid',t('Terjemahan audio tidak valid.'));
      return JSON.stringify([result.source_text,result.translated_text,result.source_language,result.target_language]);
    };
    let available=[],playbackTask=null,playbackError=null,playbackMs=0,activeSince=null,prefetchedIndex=-1,startedClips=0;
    const prefetchNext=()=>{
      const next=available[played+1];
      if(!onPrefetch||activeSince===null||!next||prefetchedIndex===next.index||controller.signal.aborted)return;
      prefetchedIndex=next.index;
      // A failed prefetch is retained by the player and reported when consumed;
      // it cannot interrupt the preceding clip or trigger another download.
      try{Promise.resolve(onPrefetch(next,controller.signal)).catch(()=>{});}catch{}
    };
    const drain=()=>{
      if(playbackTask||playbackError||played>=available.length||controller.signal.aborted)return;
      playbackTask=(async()=>{
        while(played<available.length){
          if(controller.signal.aborted)throw aborted();
          activeSince=this.now();
          try{startedClips++;const playing=onSegment(available[played],controller.signal);prefetchNext();await playing;}
          catch(e){e.segmentPlayback=true;throw e;}
          finally{playbackMs+=Math.max(0,this.now()-activeSince);activeSince=null;}
          if(controller.signal.aborted)throw aborted();played++;
        }
      })();
      playbackTask.then(()=>{playbackTask=null;},e=>{playbackError=e;playbackTask=null;controller.abort();});
    };
    try{
      // A settled realtime input uses poll-only output, never another STT POST.
      if(blob!==null)await this.json(url,{method:'POST',body:data,signal:controller.signal,timeoutMs:30000});const deadline=this.now()+this.turnMs;
      while(!controller.signal.aborted){
        const result=await this.json(url,{signal:controller.signal,timeoutMs:15000});
        if(controller.signal.aborted)throw aborted();
        if(result.status==='PROCESSING'&&result.translation_ready===true){
          const identity=textIdentity(result);
          if(completeText!==null&&completeText!==identity)throw error('stream_invalid',t('Terjemahan audio berubah.'));
          if(completeText===null){completeText=identity;onTranslation?.(result);}
        }
        if(result.status==='COMPLETED'&&completeText!==null&&textIdentity(result)!==completeText)throw error('stream_invalid',t('Terjemahan audio berubah.'));
        if(onProgressive&&result.status==='PROCESSING'&&result.audio_progress_url){
          if(!completeText||result.audio_progress_url!==url+'/audio/progress')throw error('stream_invalid',t('Terjemahan audio tidak valid.'));
          if(!progressiveTask){startedClips++;progressiveTask=Promise.resolve(onProgressive(result.audio_progress_url,controller.signal));progressiveTask.then(value=>{progressiveResult=value;},e=>{progressiveError=e;controller.abort();});}
        }
        if(result.status==='COMPLETED'&&progressiveTask){
          await progressiveTask;if(progressiveError)throw progressiveError;if(controller.signal.aborted)throw aborted();
          if(result.audio_url!==url+'/audio'||progressiveResult?.sha256!==result.audio_sha256)throw error('stream_invalid',t('Terjemahan audio tidak valid.'));
          return {...result,streamed:true,...(progressiveResult.playbackError?{playbackError:progressiveResult.playbackError}:{})};
        }
        if(onSegment&&result.stream_output==='sentences-v1'&&['PROCESSING','COMPLETED'].includes(result.status)){
          let totalMs=0,previousText='';
          if(typeof result.translated_text!=='string'||!result.translated_text.trim()||result.translated_text.length>4000||typeof result.source_language!=='string'||typeof result.target_language!=='string'||!result.source_language||!result.target_language||result.source_language===result.target_language)throw error('stream_invalid',t('Terjemahan audio tidak valid.'));
          const translated=JSON.stringify([result.translated_text,result.source_language,result.target_language]);
          if(translationIdentity!==null&&translationIdentity!==translated)throw error('stream_invalid',t('Terjemahan audio berubah.'));translationIdentity=translated;
          if(!Number.isInteger(result.total_segments)||result.total_segments<1||result.total_segments>8||!Array.isArray(result.segments)||result.segments.length>result.total_segments||result.segments.length<identities.length)throw error('stream_invalid',t('Urutan audio tidak valid.'));
          if(announced!==null&&announced!==result.total_segments)throw error('stream_invalid',t('Jumlah segmen berubah.'));announced=result.total_segments;
          for(let index=0;index<result.segments.length;index++){
            const part=result.segments[index];
            if(part.index!==index||part.audio_url!==url+'/audio/segments/'+index||!Number.isInteger(part.duration_ms)||part.duration_ms<=0||part.duration_ms>600000||typeof part.translated_text!=='string'||part.translated_text.length>4000)throw error('stream_invalid',t('Segmen audio tidak valid.'));
            if(!part.translated_text.trim()||!part.translated_text.startsWith(previousText)||part.translated_text.length<=previousText.length||!result.translated_text.startsWith(part.translated_text))throw error('stream_invalid',t('Teks segmen tidak lengkap.'));previousText=part.translated_text;
            totalMs+=part.duration_ms;if(totalMs>600000)throw error('stream_invalid',t('Audio melebihi batas durasi.'));
            const identity=JSON.stringify([part.audio_url,part.duration_ms,part.translated_text]);
            if(identities[index]&&identities[index]!==identity)throw error('stream_invalid',t('Segmen audio berubah.'));identities[index]=identity;
          }
          if(result.status==='COMPLETED'&&(result.segments.length!==result.total_segments||previousText!==result.translated_text))throw error('stream_invalid',t('Audio belum mencakup seluruh terjemahan.'));
          available=result.segments;drain();prefetchNext();
          if(result.status==='COMPLETED'){
            if(playbackTask)await playbackTask;
            if(playbackError)throw playbackError;
            if(controller.signal.aborted)throw aborted();
            if(played!==result.total_segments)throw error('stream_invalid',t('Audio belum lengkap.'));
            return {...result,streamed:true};
          }
        }else if(result.status==='COMPLETED'){
          if(announced!==null)throw error('stream_invalid',t('Format audio berubah sebelum seluruh ucapan selesai.'));
          return result;
        }else if(announced!==null&&result.status==='PROCESSING')throw error('stream_invalid',t('Format audio streaming berubah.'));
        if(result.status==='FAILED'){
          if(result.code==='stream_unavailable')this.disabledStreamSession=id;
          const failure=error(result.code||'processing_failed',result.error||t('Ucapan belum berhasil diproses.'));
          failure.recoverable=Boolean(result.recoverable);failure.turnSettled=result.code!=='processing_interrupted'&&result.input_settled!==false;throw failure;
        }
        if(result.status==='CANCELLED')throw error('turn_cancelled',t('Ucapan ini dibatalkan dan tidak diulang otomatis.'));
        if(this.now()>=deadline+playbackMs+(activeSince===null?0:Math.max(0,this.now()-activeSince)))throw error('turn_timeout',t('Ucapan ini belum selesai. Silakan bicara kembali setelah pemulihan.'));
        await this.pause(controller.signal);
      }
      throw aborted();
    }catch(e){
      if(progressiveError)e=progressiveError;
      if(playbackError)e=playbackError;
      // Stop the scoped player/prefetch before recovery or a new utterance.
      controller.abort();
      if(signal.aborted)throw e;
      // Confirm a scoped cancellation/tombstone before allowing another recording.
      if(!e.turnSettled){
        try{
          const state=await this.cancel(id,key,signal);if(signal.aborted)throw aborted();
          if(!['CANCELLED','FAILED','COMPLETED'].includes(state.status))throw error('cancel_unconfirmed',t('Pembatalan ucapan belum terkonfirmasi.'));
          if(state.status==='COMPLETED'&&!e.segmentPlayback&&!startedClips&&e.code!=='stream_invalid'){
            const completed=await this.json(url,{signal,timeoutMs:15000});
            if(completed.status==='COMPLETED')return completed;
          }
          if(state.status==='FAILED'){
            const failed=await this.json(url,{signal,timeoutMs:15000});
            if(failed.status!=='FAILED')throw error('cancel_unconfirmed',t('Status ucapan belum terkonfirmasi.'));
            e.code=failed.code||'processing_failed';e.message=failed.error||t('Ucapan belum berhasil diproses.');e.recoverable=Boolean(failed.recoverable);
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
