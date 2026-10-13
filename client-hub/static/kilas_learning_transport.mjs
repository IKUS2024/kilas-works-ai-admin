import {within} from './kilas_learning_engine.mjs';

export function learningRequest({csrf,fetcher=fetch,timeout=15000}){
  return async(path,{data,signal,binary=false,keepalive=false}={})=>{
    const control=new AbortController(),abort=()=>control.abort();
    signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
    try{
      return await within(async()=>{
        const response=await fetcher('/kilas-learning'+path,{method:data?'POST':'GET',body:data,signal:control.signal,credentials:'same-origin',headers:data?{'X-CSRF-Token':csrf}:{},cache:'no-store',keepalive});
        if(!response.ok){const result=await response.json().catch(()=>({}));const error=Error(result.error||'Sesi belum dapat diperiksa. Tekan Lanjutkan.');error.code=result.code;throw error;}
        return binary?response.arrayBuffer():response.json();
      },control.signal,timeout);
    }finally{signal?.removeEventListener('abort',abort);control.abort();}
  };
}
