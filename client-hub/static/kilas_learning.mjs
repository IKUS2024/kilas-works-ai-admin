import {LearningCall} from './kilas_learning_engine.mjs';
import {RealtimeMic,microphone} from './kilas_learning_realtime.mjs';

const root=document.querySelector('[data-learning]');
if(root){
  const form=root.querySelector('form'),status=root.querySelector('[data-status]'),active=root.querySelector('[data-call]'),setup=root.querySelector('[data-setup]');
  const resume=root.querySelector('[data-resume]'),mute=root.querySelector('[data-mute]'),orb=root.querySelector('[data-orb]');
  const csrf=form.elements.csrf_token.value,base='/kilas-learning';let context,source,stopPlayback;
  const connect=()=>{context??=new(window.AudioContext||window.webkitAudioContext)();return context;};
  const player={
    async unlock(){await connect().resume();},
    async play(raw,signal,started){
      const ctx=connect(),buffer=await ctx.decodeAudioData(raw.slice(0));if(signal.aborted)throw new DOMException('Aborted','AbortError');
      await ctx.resume();if(signal.aborted)throw new DOMException('Aborted','AbortError');
      return new Promise((resolve,reject)=>{let settled=false;source=ctx.createBufferSource();source.buffer=buffer;source.connect(ctx.destination);
        const finish=error=>{if(settled)return;settled=true;signal.removeEventListener('abort',abort);source?.disconnect();source=null;stopPlayback=null;error?reject(error):resolve();};
        const abort=()=>{try{source?.stop();}finally{finish(new DOMException('Aborted','AbortError'));}};
        stopPlayback=abort;source.onended=()=>finish();signal.addEventListener('abort',abort,{once:true});source.start();started();});
    },
    stop(){stopPlayback?.();stopPlayback=null;if(context){void context.close().catch(()=>{});context=null;}}
  };
  const request=async(path,{data,signal,binary=false,keepalive=false}={})=>{
    const response=await fetch(base+path,{method:data?'POST':'GET',body:data,signal,credentials:'same-origin',headers:data?{'X-CSRF-Token':csrf}:{},cache:'no-store',keepalive});
    if(!response.ok){const result=await response.json().catch(()=>({}));const error=Error(result.error||'Sesi belum dapat diperiksa. Coba Lanjutkan.');error.code=result.code;throw error;}
    return binary?response.arrayBuffer():response.json();
  };
  const fields=values=>{const body=new FormData();body.set('csrf_token',csrf);for(const [key,value]of Object.entries(values))body.set(key,value);return body;};
  const api={
    start:(settings,signal)=>request('/sessions',{data:fields(settings),signal}),
    current:signal=>request('/session',{signal}),
    status:(sid,turn,signal)=>request('/sessions/'+sid+(turn?'/turns/'+turn:''),{signal}),
    begin:(sid,operation_key,signal)=>request('/sessions/'+sid+'/input',{data:fields({operation_key}),signal}),
    chunk:(sid,turn,index,pcm,signal)=>request('/sessions/'+sid+'/input/'+turn+'/chunks/'+index,{data:fields({chunk:new Blob([pcm])}),signal}),
    commit:(sid,turn,signal)=>request('/sessions/'+sid+'/input/'+turn+'/commit',{data:fields({}),signal}),
    cancel:(sid,turn)=>request('/sessions/'+sid+'/input/'+turn+'/cancel',{data:fields({}),keepalive:true}),
    clip:(sid,turn,index,signal)=>request('/sessions/'+sid+'/turns/'+turn+'/clips/'+index,{signal,binary:true}),
    end:(sid,start_key)=>request('/cancel-start',{data:fields({start_key:start_key||'',session_id:sid||''}),keepalive:true}),
    milestone:(event,index)=>{performance.mark('kilas-learning-'+event+'-'+index);}
  };
  const save=value=>{try{value?sessionStorage.setItem('kilas-learning-session',JSON.stringify(value)):sessionStorage.removeItem('kilas-learning-session');}catch{}};
  const capture=new RealtimeMic({api,session:()=>call.session,id:()=>crypto.randomUUID().replaceAll('-',''),openMicrophone:microphone,onOpened:turn=>call.beginInput(turn)});
  const call=new LearningCall({api,capture,player,save,onState:(state,message)=>{
    const inCall=state!=='ended';setup.hidden=inCall;active.hidden=!inCall;orb.dataset.state=state;
    const labels={preparing:'Tutor sedang menyiapkan jawaban…',speaking:'Tutor berbicara',listening:'Giliran kamu. Silakan bicara.',muted:'Mikrofon dinonaktifkan',paused:'Sesi dijeda',ended:'Sesi berakhir'};
    status.textContent=message||labels[state];resume.hidden=state!=='paused';mute.disabled=state==='paused';
    if(state==='ended'){mute.setAttribute('aria-pressed','false');mute.textContent='Matikan mikrofon';}
  }});
  form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const values=Object.fromEntries(new FormData(form));values.consent='yes';void call.start(values);});
  mute.addEventListener('click',()=>{const value=call.mute();mute.setAttribute('aria-pressed',String(value));mute.textContent=value?'Aktifkan mikrofon':'Matikan mikrofon';});
  resume.addEventListener('click',()=>void call.resume());root.querySelector('[data-end]').addEventListener('click',()=>void call.end());
  document.addEventListener('visibilitychange',()=>{if(document.hidden)call.pause();});
  window.addEventListener('pagehide',()=>call.pause());
  try{const saved=JSON.parse(sessionStorage.getItem('kilas-learning-session')||'null');if(saved)void call.restore(saved);}catch{}
  // Discovery is read-only and never greets, records, plays or dispatches providers.
  if(!call.active)api.current().then(state=>{if(state.session_id&&!call.active)void call.restore({session:state.session_id});}).catch(()=>{});
}
