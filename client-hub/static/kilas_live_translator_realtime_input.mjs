const failure=code=>Object.assign(Error('Input suara terputus. Ucapan ini tidak diulang dalam mode lain.'),{code});
const abort=()=>new DOMException('Sesi dijeda.','AbortError');
export class RealtimeInput {
  constructor({json,csrf}){Object.assign(this,{json,csrf});this.current=null;}
  path(id,key){return '/kilas-translator/live/sessions/'+encodeURIComponent(id)+'/turns/'+encodeURIComponent(key);}
  form(){const data=new FormData();data.append('csrf_token',this.csrf);return data;}
  push(id,key,bytes,signal){
    if(signal.aborted)return Promise.reject(abort());
    if(!(bytes instanceof Uint8Array)||!bytes.byteLength||bytes.byteLength>32000||bytes.byteLength%2)return Promise.reject(failure('realtime_chunk_invalid'));
    let turn=this.current;
    if(!turn){
      turn={id,key,signal,index:0,queued:0,total:0,finishing:false,pending:new Uint8Array(32000),length:0};this.current=turn;
      turn.cancel=()=>{if(!turn.cancelPromise)turn.cancelPromise=this.json(this.path(id,key)+'/cancel',{method:'POST',body:this.form(),keepalive:true,timeoutMs:10000}).catch(()=>null);return turn.cancelPromise;};
      signal.addEventListener('abort',turn.cancel,{once:true});
      turn.chain=this.json(this.path(id,key)+'/input/start',{method:'POST',body:this.form(),signal,timeoutMs:15000}).then(result=>{if(result.input_mode!=='realtime-v1')throw failure('realtime_protocol');});
    }
    if(turn.id!==id||turn.key!==key||turn.signal!==signal||turn.finishing)return Promise.reject(failure('realtime_turn_busy'));
    if(turn.queued+bytes.byteLength>128000||turn.total+bytes.byteLength>180*32000||turn.index>=2000){turn.failure=failure('realtime_queue_full');turn.cancel();return Promise.reject(turn.failure);}
    turn.queued+=bytes.byteLength;turn.total+=bytes.byteLength;
    let offset=0;
    while(offset<bytes.byteLength){const length=Math.min(bytes.byteLength-offset,32000-turn.length);turn.pending.set(bytes.subarray(offset,offset+length),turn.length);turn.length+=length;offset+=length;if(turn.length===32000)this.flush(turn);}
    return turn.chain;
  }
  flush(turn){
    if(!turn.length)return;
    const {id,key,signal}=turn,index=turn.index++,copy=turn.pending.slice(0,turn.length);turn.length=0;
    const work=turn.chain.then(async()=>{
      if(signal.aborted)throw abort();if(turn.failure)throw turn.failure;
      const data=this.form();data.append('pcm',new Blob([copy],{type:'application/octet-stream'}),'pcm');
      const result=await this.json(this.path(id,key)+'/input/chunks/'+index,{method:'POST',body:data,signal,timeoutMs:10000});
      if(result.accepted_index!==index)throw failure('realtime_chunk_invalid');
    }).finally(()=>{turn.queued-=copy.byteLength;});
    turn.chain=work;
  }
  async finish(id,key,signal,onCommit=()=>{}){
    const turn=this.current;
    if(!turn||turn.id!==id||turn.key!==key||turn.signal!==signal||turn.finishing)throw failure('realtime_no_speech');
    turn.finishing=true;this.flush(turn);
    try{
      await turn.chain;if(signal.aborted)throw abort();if(turn.failure)throw turn.failure;const data=this.form();data.append('count',String(turn.index));
      try{onCommit();}catch{}
      await this.json(this.path(id,key)+'/input/commit',{method:'POST',body:data,signal,timeoutMs:10000});
    }catch(e){
      const state=await turn.cancel();e.turnSettled=Boolean(state&&['CANCELLED','FAILED','COMPLETED'].includes(state.status));e.recoverable=false;throw e;
    }finally{signal.removeEventListener('abort',turn.cancel);if(this.current===turn)this.current=null;}
  }
  reset(){const turn=this.current;if(turn){turn.signal.removeEventListener('abort',turn.cancel);this.current=null;}}
}
