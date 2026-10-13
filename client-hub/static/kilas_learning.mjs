import {LearningCall} from './kilas_learning_engine.mjs';
import {RealtimeMic,microphone} from './kilas_learning_realtime.mjs';
import {LearningPlayer} from './kilas_learning_player.mjs';
import {learningRequest} from './kilas_learning_transport.mjs';

const mounted=new WeakMap();
export function mountLearning(root,options={}){
  if(mounted.has(root))return mounted.get(root);
  const document=root.ownerDocument,window=document.defaultView;
  // The shared task row contains a Finance form before the lesson form.
  const form=root.querySelector('[data-learning-form]'),status=root.querySelector('[data-status]'),active=root.querySelector('[data-call]'),setup=root.querySelector('[data-setup]');
  const resume=root.querySelector('[data-resume]'),mute=root.querySelector('[data-mute]'),orb=root.querySelector('[data-orb]'),end=root.querySelector('[data-end]');
  const start=form?.querySelector('[data-learning-start]');
  if(!form||!status||!active||!setup||!resume||!mute||!orb||!end||!start)throw Error('learning_controls_missing');
  const field=name=>{const value=form.elements.namedItem(name);if(!value)throw Error('learning_field_missing');return value;};
  for(const name of ['csrf_token','target','native','level','voice','consent'])field(name);
  const csrf=field('csrf_token').value,player=options.player||new LearningPlayer(()=>{const Context=window.AudioContext||window.webkitAudioContext;if(!Context)throw Error('Audio browser belum didukung. Gunakan browser terbaru.');return new Context();});
  const request=options.api?null:learningRequest({csrf,fetcher:window.fetch.bind(window)});
  const fields=values=>{const body=new window.FormData();body.set('csrf_token',csrf);for(const [key,value]of Object.entries(values))body.set(key,value);return body;};
  const api=options.api||{
    start:(settings,signal)=>request('/sessions',{data:fields(settings),signal}),
    current:signal=>request('/session',{signal}),
    status:(sid,turn,signal)=>request('/sessions/'+sid+(turn?'/turns/'+turn:''),{signal}),
    begin:(sid,operation_key,signal)=>request('/sessions/'+sid+'/input',{data:fields({operation_key}),signal}),
    chunk:(sid,turn,index,pcm,signal)=>request('/sessions/'+sid+'/input/'+turn+'/chunks/'+index,{data:fields({chunk:new window.Blob([pcm])}),signal}),
    commit:(sid,turn,signal)=>request('/sessions/'+sid+'/input/'+turn+'/commit',{data:fields({}),signal}),
    cancel:(sid,turn)=>request('/sessions/'+sid+'/input/'+turn+'/cancel',{data:fields({}),keepalive:true}),
    clip:(sid,turn,index,signal)=>request('/sessions/'+sid+'/turns/'+turn+'/clips/'+index,{signal,binary:true}),
    end:(sid,start_key)=>request('/cancel-start',{data:fields({start_key:start_key||'',session_id:sid||''}),keepalive:true}),
    milestone:(event,index)=>{window.performance.mark('kilas-learning-'+event+'-'+index);}
  };
  const id=options.id||(()=>{
    if(!window.crypto?.getRandomValues)throw Error('Browser belum mendukung sesi suara yang aman. Gunakan browser terbaru.');
    if(window.crypto.randomUUID)return window.crypto.randomUUID().replaceAll('-','');
    return [...window.crypto.getRandomValues(new Uint8Array(16))].map(value=>value.toString(16).padStart(2,'0')).join('');
  });
  const save=value=>{try{value?window.sessionStorage.setItem('kilas-learning-session',JSON.stringify(value)):window.sessionStorage.removeItem('kilas-learning-session');}catch{}};
  const capture=options.capture||new RealtimeMic({api,session:()=>call.session,id,openMicrophone:microphone,onOpened:turn=>call.beginInput(turn)});
  let permitted=form.dataset.ready==='true',gateMessage='Learning belum tersedia untuk akun ini. Periksa aktivasi atau masuk kembali.';
  const updateStart=()=>{start.disabled=!permitted||!field('consent').checked||call.active;};
  const setupMessage=()=>!permitted?gateMessage:field('consent').checked?'Siap. Tekan Mulai belajar untuk mengaktifkan mikrofon dan audio.':'Setujui pemrosesan suara untuk mengaktifkan Mulai belajar.';
  const call=new LearningCall({api,capture,player,id,save,onSettings:settings=>{
    if(settings)for(const name of ['target','native','level','voice'])if([...field(name).options].some(option=>option.value===settings[name]))field(name).value=settings[name];
    root.querySelector('[data-call-settings]').textContent=settings?['target','level','voice'].map(name=>field(name).selectedOptions[0]?.textContent).filter(Boolean).join(' · '):'Sesi tersimpan';
  },onState:(state,message)=>{
    const wasActive=root.dataset.active==='true',inCall=state!=='ended';root.dataset.active=String(inCall);setup.hidden=inCall;active.hidden=!inCall;orb.dataset.state=state;
    const labels={preparing:'Tutor sedang menyiapkan jawaban…',speaking:'Tutor berbicara',listening:'Giliran kamu. Silakan bicara.',muted:'Mikrofon dinonaktifkan',paused:'Sesi dijeda',ended:'Sesi berakhir'};
    status.textContent=message||labels[state];resume.hidden=state!=='paused';mute.disabled=state==='paused';updateStart();
    if(inCall&&!wasActive)end.focus({preventScroll:true});
    if(state==='paused')resume.focus({preventScroll:true});
    if(state==='ended'){start.focus({preventScroll:true});mute.setAttribute('aria-pressed','false');mute.textContent='Matikan mikrofon';}
  }});
  const run=task=>{
    const failed=()=>{
      const message=call.active?'Learning terhenti. Tekan Lanjutkan untuk memeriksa sesi atau Akhiri sesi.':'Learning belum dapat dimulai. Periksa izin mikrofon dan audio browser, lalu coba Mulai belajar.';
      if(call.active)call.pause(message);else status.textContent=message;
    };
    try{Promise.resolve(task()).catch(failed);}catch{failed();}
  };
  form.addEventListener('submit',event=>{
    event.preventDefault();
    if(!permitted||!field('consent').checked){status.textContent=setupMessage();updateStart();return;}
    if(!form.reportValidity()){status.textContent='Lengkapi pilihan belajar sebelum mulai.';return;}
    const values=Object.fromEntries(new window.FormData(form));
    run(()=>call.start(values));
  });
  field('consent').addEventListener('change',()=>{updateStart();if(!call.active)status.textContent=setupMessage();});
  form.addEventListener('invalid',()=>{if(!call.active)status.textContent=field('consent').checked?'Lengkapi pilihan belajar sebelum mulai.':setupMessage();},true);
  mute.addEventListener('click',()=>{const value=call.mute();mute.setAttribute('aria-pressed',String(value));mute.textContent=value?'Aktifkan mikrofon':'Matikan mikrofon';});
  resume.addEventListener('click',()=>run(()=>call.resume()));end.addEventListener('click',()=>run(()=>call.end()));
  document.addEventListener('visibilitychange',()=>{if(document.hidden)call.pause();});
  window.addEventListener('pagehide',()=>call.pause());
  mounted.set(root,call);root.dataset.boot='ready';updateStart();status.textContent=setupMessage();
  root.dispatchEvent(new window.Event('kilas-learning-booted'));
  try{const saved=JSON.parse(window.sessionStorage.getItem('kilas-learning-session')||'null');if(saved)run(()=>call.restore(saved));}catch{}
  // Discovery is read-only; failure never triggers a greeting or paid retry.
  if(!call.active)api.current().then(state=>{if(state.session_id&&!call.active)run(()=>call.restore({session:state.session_id}));}).catch(error=>{
    if(call.active)return;
    if(error.httpStatus===401||error.httpStatus===403){permitted=false;gateMessage=error.message;updateStart();status.textContent=gateMessage;}
    else status.textContent='Status sesi belum dapat diperiksa. Mulai belajar akan memeriksa akun kembali.';
  });
  return call;
}

if(typeof document!=='undefined'){
  const root=document.querySelector('[data-learning]');
  if(root)try{mountLearning(root);}catch{
    root.dataset.boot='failed';const start=root.querySelector('[data-learning-start]'),status=root.querySelector('[data-status]');
    if(start)start.disabled=true;if(status)status.textContent='Kontrol Learning belum berhasil dimuat. Periksa dukungan browser dan koneksi, lalu buka kembali Learning.';
  }
}
