(()=>{'use strict';for(const form of document.querySelectorAll('[data-bill-today]')){
 const cadence=form.elements.cadence,mode=form.elements.end_mode,end=form.elements.end_on,begin=form.elements.begin_next_month,due=form.elements.next_due_on;
 if(!cadence||!mode||!end||!begin||!due)continue;
 function update(){const once=cadence.value==='ONCE';mode.disabled=once;mode.closest('label').hidden=once;end.hidden=end.disabled=once||mode.value!=='DATE';end.required=!end.disabled;}
 cadence.addEventListener('change',update);mode.addEventListener('change',update);update();
 begin.addEventListener('change',()=>{if(!begin.checked)return;const today=form.dataset.billToday;if(!due.value||due.value.slice(0,7)<=today.slice(0,7)){
  const [year,month]=today.split('-').map(Number),day=Number((due.value||today).slice(-2)),next=month===12?1:month+1,ny=year+(month===12?1:0),last=new Date(Date.UTC(ny,next,0)).getUTCDate();due.value=String(ny)+'-'+String(next).padStart(2,'0')+'-'+String(Math.min(day,last)).padStart(2,'0');
 }});
}})();
