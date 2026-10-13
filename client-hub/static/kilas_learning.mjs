import {LearningCall} from './kilas_learning_engine.mjs';
import {RealtimeMic,microphone} from './kilas_learning_realtime.mjs';
import {LearningPlayer} from './kilas_learning_player.mjs';
import {learningRequest} from './kilas_learning_transport.mjs';

const root=document.querySelector('[data-learning]');
if(root){
  const form=root.querySelector('form'),status=root.querySelector('[data-status]'),active=root.querySelector('[data-call]'),setup=root.querySelector('[data-setup]');
  const resume=root.querySelector('[data-resume]'),mute=root.querySelector('[data-mute]'),orb=root.querySelector('[data-orb]');
  const csrf=form.elements.csrf_token.value,player=new LearningPlayer();
  const request=learningRequest({csrf});
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
  const call=new LearningCall({api,capture,player,save,onSettings:settings=>{
    if(settings)for(const name of ['target','native','level','voice'])if([...form.elements[name].options].some(option=>option.value===settings[name]))form.elements[name].value=settings[name];
    root.querySelector('[data-call-settings]').textContent=settings?['target','level','voice'].map(name=>form.elements[name].selectedOptions[0]?.textContent).filter(Boolean).join(' · '):'Sesi tersimpan';
  },onState:(state,message)=>{
    const wasActive=root.dataset.active==='true',inCall=state!=='ended';root.dataset.active=String(inCall);setup.hidden=inCall;active.hidden=!inCall;orb.dataset.state=state;
    const labels={preparing:'Tutor sedang menyiapkan jawaban…',speaking:'Tutor berbicara',listening:'Giliran kamu. Silakan bicara.',muted:'Mikrofon dinonaktifkan',paused:'Sesi dijeda',ended:'Sesi berakhir'};
    status.textContent=message||labels[state];resume.hidden=state!=='paused';mute.disabled=state==='paused';
    if(inCall&&!wasActive)root.querySelector('[data-end]').focus({preventScroll:true});
    if(state==='paused')resume.focus({preventScroll:true});
    if(state==='ended'){root.querySelector('button[type=submit]').focus({preventScroll:true});mute.setAttribute('aria-pressed','false');mute.textContent='Matikan mikrofon';}
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
