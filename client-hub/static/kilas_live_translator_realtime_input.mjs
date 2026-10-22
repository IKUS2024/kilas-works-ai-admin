import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';
const failure=code=>{
  const detail={realtime_queue_full:t('Koneksi input tertinggal terlalu lama. Sesi dijeda agar ucapan tidak dipotong.'),
    realtime_protocol:t('Layanan belum mengonfirmasi input suara.'),
    realtime_turn_busy:t('Ucapan sebelumnya belum selesai dikirim.'),
    realtime_chunk_invalid:t('Urutan input suara belum terkonfirmasi.'),
    realtime_no_speech:t('Input ucapan belum lengkap.')}[code]||t('Input suara terputus.');
  return Object.assign(Error(detail+t(' Ucapan ini tidak diulang dalam mode lain.')),{code,inputStage:'upload'});
};
const MAX_CHUNK_BYTES=4*32000; // Negotiated coalescing; the total backlog stays8s.
const MAX_BACKLOG_BYTES=8*32000; // Bounded startup/jitter buffer; total utterance cap is unchanged.
const abort=()=>new DOMException(t('Sesi dijeda.'),'AbortError');
export class RealtimeInput {
  constructor({json,csrf,holdToTalk=false,now=()=>performance.now(),onTiming=()=>{}}){Object.assign(this,{json,csrf,holdToTalk,now,onTiming});this.current=null;}
  path(id,key){return '/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/turns/'+encodeURIComponent(key);}
  form(){const data=new FormData();data.append('csrf_token',this.csrf);return data;}
  push(id,key,bytes,signal){
    if(signal.aborted)return Promise.reject(abort());
    if(!(bytes instanceof Uint8Array)||!bytes.byteLength||bytes.byteLength>32000||bytes.byteLength%2)return Promise.reject(failure('realtime_chunk_invalid'));
    let turn=this.current;
    if(!turn){
      turn={id,key,signal,index:0,queued:0,total:0,finishing:false,prepareMs:0,httpMs:0,maxQueued:0,maxChunk:32000,pumping:false,pending:new Uint8Array(MAX_BACKLOG_BYTES),length:0};this.current=turn;
      turn.cancel=()=>{if(!turn.cancelPromise)turn.cancelPromise=this.json(this.path(id,key)+'/cancel',{method:'POST',body:this.form(),keepalive:true,timeoutMs:10000}).catch(()=>null);return turn.cancelPromise;};
      signal.addEventListener('abort',turn.cancel,{once:true});
      const start=this.form();start.append('chunk_transport','pcm-coalesce-v1');if(this.clauses)start.append('capture_mode','clauses-v1');else if(this.holdToTalk)start.append('capture_mode','hold-v1');
      const admissionBegan=this.now();
      turn.chain=this.json(this.path(id,key)+'/input/start',{method:'POST',body:start,signal,timeoutMs:15000}).then(result=>{if(result.input_mode!=='realtime-v1')throw failure('realtime_protocol');if(result.max_chunk_bytes!==undefined){if(![32000,MAX_CHUNK_BYTES].includes(result.max_chunk_bytes))throw failure('realtime_protocol');turn.maxChunk=result.max_chunk_bytes;}try{this.onTiming({input_admission_http_ms:Math.max(0,this.now()-admissionBegan)});}catch{}});
    }
    if(turn.id!==id||turn.key!==key||turn.signal!==signal||turn.finishing)return Promise.reject(failure('realtime_turn_busy'));
    if(turn.queued+bytes.byteLength>MAX_BACKLOG_BYTES||turn.total+bytes.byteLength>180*32000||turn.index>=2000){turn.failure=failure('realtime_queue_full');return this.settleFailure(turn,turn.failure);}
    turn.queued+=bytes.byteLength;turn.total+=bytes.byteLength;turn.maxQueued=Math.max(turn.maxQueued,turn.queued);
    turn.pending.set(bytes,turn.length);turn.length+=bytes.byteLength;
    this.flush(turn);
    return turn.chain.catch(e=>this.settleFailure(turn,e));
  }
  flush(turn){
    // One HTTP writer owns ordering. Choose its payload only when the previous
    // ACK arrives, coalescing unsent PCM instead of prebuilding a1s request chain.
    // Healthy capture keeps1s batches; release drains the final tail immediately.
    if(turn.pumping||!turn.length||(!turn.finishing&&turn.index>0&&turn.length<32000))return;
    turn.pumping=true;
    turn.chain=turn.chain.then(async()=>{
      try{
        while(turn.length&&(turn.finishing||turn.index===0||turn.length>=32000)){
          const {id,key,signal}=turn;
          if(signal.aborted)throw abort();if(turn.failure)throw turn.failure;
          const index=turn.index++,count=Math.min(turn.length,turn.maxChunk),copy=turn.pending.slice(0,count);
          turn.pending.copyWithin(0,count,turn.length);turn.length-=count;
          try{
            const prepareBegan=this.now(),data=this.form();data.append('pcm',new Blob([copy],{type:'application/octet-stream'}),'pcm');turn.prepareMs+=Math.max(0,this.now()-prepareBegan);
            const httpBegan=this.now();
            const result=await this.json(this.path(id,key)+'/input/chunks/'+index,{method:'POST',body:data,signal,timeoutMs:10000});
            turn.httpMs+=Math.max(0,this.now()-httpBegan);
            if(result.accepted_index!==index)throw failure('realtime_chunk_invalid');
          }finally{turn.queued-=count;}
        }
      }finally{turn.pumping=false;}
    });
  }
  async finish(id,key,signal,onCommit=()=>{}){
    const turn=this.current;
    if(!turn||turn.id!==id||turn.key!==key||turn.signal!==signal||turn.finishing)throw failure('realtime_no_speech');
    turn.finishing=true;this.flush(turn);
    try{
      const drainBegan=this.now();await turn.chain;try{this.onTiming({release_upload_drain_ms:Math.max(0,this.now()-drainBegan),pcm_prepare_ms:turn.prepareMs,pcm_http_total_ms:turn.httpMs,pcm_chunks:turn.index,pcm_max_backlog_ms:turn.maxQueued/32});}catch{}
      if(signal.aborted)throw abort();if(turn.failure)throw turn.failure;const data=this.form();data.append('count',String(turn.index));
      try{onCommit();}catch{}
      const commitBegan=this.now();
      await this.json(this.path(id,key)+'/input/commit',{method:'POST',body:data,signal,timeoutMs:10000});
      try{this.onTiming({commit_http_ms:Math.max(0,this.now()-commitBegan)});}catch{}
    }catch(e){
      await this.settleFailure(turn,e);
    }finally{signal.removeEventListener('abort',turn.cancel);if(this.current===turn)this.current=null;}
  }
  async settleFailure(turn,error){
    // One cancellation and one bounded read sequence shared by every failed PCM
    // callback. No start/chunk/commit retry and no alternate ASR submission.
    if(!turn.failurePromise)turn.failurePromise=(async()=>{
      turn.failure??=error;
      try{this.onTiming({input_failed_backlog_ms:turn.queued/32,input_failed_chunks:turn.index});}catch{}
      let state=await turn.cancel();
      if(state?.status==='FAILED'&&!state.code&&!turn.signal.aborted){
        try{state=await this.json(this.path(turn.id,turn.key),{signal:turn.signal,timeoutMs:3000});}catch{state=null;}
      }
      for(let n=0;state?.input_settled===false&&n<12&&!turn.signal.aborted;n++){
        await new Promise(resolve=>setTimeout(resolve,250));
        try{state=await this.json(this.path(turn.id,turn.key),{signal:turn.signal,timeoutMs:3000});}catch{state=null;break;}
      }
      error.turnSettled=Boolean(state&&state.input_settled!==false&&['CANCELLED','FAILED','COMPLETED'].includes(state.status));
      const transient=['request_timeout','realtime_transport','realtime_input_idle','realtime_commit_timeout','realtime_worker_unavailable','realtime_queue_full'];
      if(state?.status==='FAILED'&&state.code){error.code=state.code;error.message=state.error||error.message;}
      error.recoverable=!turn.signal.aborted&&error.turnSettled&&(state?.status==='FAILED'?state.recoverable===true:transient.includes(error.code));
      if(error.recoverable)error.message=t('Input suara terputus. Silakan bicara kembali.');
      throw error;
    })();
    return turn.failurePromise;
  }
  reset(){const turn=this.current;if(turn){turn.signal.removeEventListener('abort',turn.cancel);this.current=null;}}
}
