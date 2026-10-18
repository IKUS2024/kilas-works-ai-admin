// Pointer/keyboard intent only. The engine owns capture, paid-turn fences and End.
export function bindHoldToTalk({button,session,window,document}){
  let pointer=null,key=null;const cleanup=[];
  const on=(node,type,fn)=>{node.addEventListener(type,fn);cleanup.push(()=>node.removeEventListener?.(type,fn));};
  function release(cancel=false){
    if(pointer===null&&key===null)return;
    const old=pointer;pointer=null;key=null;
    session.release({cancel});
    if(old!==null){try{if(button.hasPointerCapture?.(old))button.releasePointerCapture(old);}catch{}}
  }
  on(button,'pointerdown',event=>{
    if(button.disabled||pointer!==null||key!==null||event.isPrimary===false||(event.button!==undefined&&event.button!==0))return;
    event.preventDefault();pointer=event.pointerId;try{button.setPointerCapture(pointer);}catch{}
    session.press();
  });
  on(window,'pointerup',event=>{if(event.pointerId===pointer){event.preventDefault();release();}});
  on(window,'pointercancel',event=>{if(event.pointerId===pointer)release(true);});
  on(button,'lostpointercapture',event=>{if(event.pointerId===pointer)release(true);});
  on(button,'keydown',event=>{
    if(![' ','Enter'].includes(event.key))return;event.preventDefault();
    if(button.disabled||event.repeat||key!==null||pointer!==null)return;
    key=event.key;session.press();
  });
  on(window,'keyup',event=>{if(event.key===key){event.preventDefault();release();}});
  on(button,'contextmenu',event=>{event.preventDefault();release(true);});
  on(button,'click',event=>event.preventDefault());
  on(window,'blur',()=>release(true));on(window,'pagehide',()=>release(true));
  on(document,'visibilitychange',()=>{if(document.hidden)release(true);});
  return {reset:()=>release(true),destroy(){release(true);cleanup.splice(0).forEach(fn=>fn());}};
}
