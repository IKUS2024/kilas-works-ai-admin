import {uiText as t} from './ui_i18n.mjs?v=app-language-20261015';

// Native click covers touch, mouse, Space and Enter. Pointer release does not
// stop recording. The existing engine still owns PCM, commit and cost fences.
export function bindRecordToggle({button,session,window,document,now=()=>performance.now()}){
  const cleanup=[];let last=-Infinity;
  const on=(node,type,fn)=>{node.addEventListener(type,fn);cleanup.push(()=>node.removeEventListener?.(type,fn));};
  const cancel=()=>{if(['opening','listening'].includes(session.state))session.release({cancel:true});};
  on(button,'click',event=>{
    event.preventDefault();
    if(button.disabled||event.detail>1||now()-last<300)return;
    if(session.state==='ready'){last=now();session.press();}
    else if(['opening','listening'].includes(session.state)){last=now();session.release();}
  });
  on(button,'keydown',event=>{if(event.repeat&&[' ','Enter'].includes(event.key))event.preventDefault();});
  on(button,'contextmenu',event=>event.preventDefault());
  on(window,'blur',cancel);on(window,'pagehide',cancel);
  on(document,'visibilitychange',()=>{if(document.hidden)cancel();});
  return {arm(){last=now();},reset(){last=-Infinity;},destroy(){cancel();cleanup.splice(0).forEach(fn=>fn());}};
}

// Initial Start must request permission in its own gesture, before asynchronous
// session admission. No recorder/worklet/provider starts until admission succeeds.
// Subsequent Start clicks use the existing capture adapter directly.
export class TranslatorMicrophone {
  constructor(devices,{schedule=(fn,ms)=>setTimeout(fn,ms),clear=id=>clearTimeout(id)}={}){Object.assign(this,{devices,schedule,clear});this.slot=null;}
  stop(stream){for(const track of stream?.getTracks?.()||[]){try{track.stop();}catch{}}}
  prime(){
    this.cancel();const slot={stream:null,cancelled:false,adopted:false,error:null};this.slot=slot;
    slot.promise=new Promise((resolve,reject)=>{
      slot.reject=reject;
      slot.timer=this.schedule(()=>{
        slot.error=Object.assign(Error(t('Mikrofon belum siap. Periksa izin browser lalu tekan Lanjutkan.')),{code:'microphone_permission_timeout'});
        slot.cancelled=true;this.stop(slot.stream);reject(slot.error);
      },20000);
      try{Promise.resolve(this.devices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}})).then(stream=>{
        if(slot.cancelled){this.stop(stream);return;}
        slot.stream=stream;if(slot.adopted)this.clear(slot.timer);resolve(stream);
      },error=>{slot.error=error;this.clear(slot.timer);reject(error);});}
      catch(error){slot.error=error;this.clear(slot.timer);reject(error);}
    });
    // Admission may fail before capture consumes a denied permission result.
    slot.promise.catch(()=>{});return slot.promise;
  }
  getUserMedia(constraints){
    const slot=this.slot;if(!slot)return this.devices.getUserMedia(constraints);
    this.slot=null;slot.adopted=true;this.clear(slot.timer);
    return slot.error?Promise.reject(slot.error):slot.promise;
  }
  cancel(){
    const slot=this.slot;this.slot=null;if(!slot)return;
    slot.cancelled=true;this.clear(slot.timer);this.stop(slot.stream);
    slot.reject(new DOMException(t('Sesi berakhir.'),'AbortError'));
  }
}
