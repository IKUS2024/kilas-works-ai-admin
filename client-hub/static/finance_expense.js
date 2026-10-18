(() => {
  'use strict';
  const t=(message,values={})=>window.KilasUI?window.KilasUI.t(message,values):message.replace(/\{(\w+)\}/g,(_,key)=>values[key]??'');
  document.addEventListener('change',event=>{if(event.target.matches('[data-finance-instant-filter]'))event.target.form.requestSubmit();});
  const dialog=document.getElementById('add-expense-dialog');
  document.addEventListener('click',event=>{
    const launch=event.target.closest('[data-transaction-direction="EXPENSE"], [data-entry-direction="EXPENSE"]');
    if(!launch||!dialog)return;
    event.preventDefault();event.stopImmediatePropagation();
    document.getElementById('add-transaction-dialog')?.close();dialog.showModal();
  },true);
  for(const form of document.querySelectorAll('[data-expense-form]')){
    const split=form.querySelector('[data-expense-split-toggle]'),rows=form.querySelector('[data-expense-splits]'),single=form.querySelector('[data-expense-single]'),add=form.querySelector('[data-expense-add-split]');
    function picker(box,initial){
      const parent=box.querySelector('[data-expense-parent]'),child=box.querySelector('[data-expense-child]'),label=box.querySelector('[data-expense-child-label]');
      function update(){let count=0;for(const option of child.options){if(!option.value||option.value==='__add__')continue;option.hidden=option.disabled=option.dataset.parent!==parent.value;if(!option.disabled)count++;}label.hidden=false;child.disabled=!parent.value;child.required=!!count;const empty=box.querySelector('[data-expense-empty-child]');if(empty)empty.disabled=!!parent.value;if(child.selectedOptions[0]?.disabled)child.value='';}
      if(initial){const leaf=[...child.options].find(o=>o.value===String(initial));parent.value=leaf?leaf.dataset.parent:String(initial);if(leaf)child.value=String(initial);}
      async function create(field,isChild){
        const original=field.dataset.previous||'';field.value=original;
        if(isChild&&!parent.value)return;
        const name=window.prompt(t(isChild?'Nama subkategori':'Nama kategori'));if(!name?.trim())return;
        const data=new FormData();data.append('csrf_token',form.elements.csrf_token.value);data.append('direction','EXPENSE');data.append('action','create');data.append('name',name.trim());if(isChild)data.append('parent_category_id',parent.value);
        field.disabled=true;
        try{
          const response=await fetch(form.dataset.categoryUrl,{method:'POST',body:data,credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}});const result=await response.json();if(!response.ok)throw Error(result.error||t('Kategori belum dapat disimpan.'));
          for(const target of form.querySelectorAll('[data-expense-picker]')){
            const a=target.querySelector('[data-expense-parent]'),b=target.querySelector('[data-expense-child]'),av=a.value,bv=b.value;
            a.replaceChildren(new Option(t('Pilih kategori'),''));b.replaceChildren(new Option(t('Pilih subkategori'),''));
            for(const option of result.options){const node=new Option(option.name,String(option.id));if(option.parent_category_id)node.dataset.parent=String(option.parent_category_id);(option.parent_category_id?b:a).append(node);}
            a.append(new Option(t('Tambah kategori…'),'__add__'));b.append(new Option(t('Tambah subkategori…'),'__add__'));a.value=av;b.value=bv;
          }
          field.value=String(result.category.id);if(!isChild)child.value='';update();field.dataset.previous=field.value;
        }catch(error){window.alert(error.message||t('Kategori belum dapat disimpan.'));}finally{refresh();}
      }
      for(const [field,isChild] of [[parent,false],[child,true]])field.addEventListener('change',()=>{if(field.value==='__add__'){create(field,isChild);return;}field.dataset.previous=field.value;if(!isChild){child.value='';child.dataset.previous='';}update();});
      box.refreshExpensePicker=update;update();parent.dataset.previous=parent.value;child.dataset.previous=child.value;
    }
    picker(single,form.dataset.initialCategory);
    function row(value){if(rows.children.length>=20)return;const fragment=form.querySelector('template').content.cloneNode(true),box=fragment.firstElementChild;rows.append(box);picker(box,value?.category_id);if(value){const input=box.querySelector('[name="split_amount"]');input.value=(BigInt(value.amount_minor)/100n).toString()+'.'+(BigInt(value.amount_minor)%100n).toString().padStart(2,'0');}box.querySelector('[data-expense-remove-split]').onclick=()=>{if(rows.children.length>2)box.remove();};}
    function refresh(){rows.hidden=add.hidden=!split.checked;single.hidden=split.checked;for(const control of single.querySelectorAll('select'))control.disabled=split.checked;if(!split.checked)single.refreshExpensePicker();for(const control of rows.querySelectorAll('input,select'))control.disabled=!split.checked;if(split.checked)for(const box of rows.children)box.refreshExpensePicker();}
    const initial=JSON.parse(form.dataset.initialSplits||'[]');for(const value of initial)row(value);if(initial.length)split.checked=true;while(rows.children.length<2)row();
    split.addEventListener('change',refresh);add.onclick=()=>row();refresh();
    // Restore selected leaf categories after initialization (refresh filters child lists).
    if(initial.length)[...rows.children].forEach((box,i)=>{const leaf=box.querySelector('[data-expense-child]');if([...leaf.options].some(o=>o.value===String(initial[i].category_id)))leaf.value=String(initial[i].category_id);});
    const account=form.querySelector('[data-expense-account]');function currency(){form.querySelector('[data-expense-currency]').textContent=account.selectedOptions[0]?.dataset.currency||'';}account.addEventListener('change',currency);currency();
    form.querySelector('[data-expense-photo]').addEventListener('change',event=>{form.querySelector('[data-expense-photo-name]').textContent=event.target.files[0]?.name||'';});
    const installment=form.querySelector('[data-installment-toggle]'),fields=form.querySelector('[data-installment-fields]');
    if(installment){
      const input=name=>form.elements[name];
      function installments(){fields.hidden=fields.disabled=!installment.checked;const custom=input('installment_frequency').value==='CUSTOM';form.querySelector('[data-installment-custom]').hidden=!custom;input('installment_dates').disabled=!custom;
        const months=Number(input('installment_duration').value)*(input('installment_unit').value==='YEARS'?12:1),step={MONTHLY:1,QUARTERLY:3,YEARLY:12}[input('installment_frequency').value];
        const count=custom?input('installment_dates').value.split(/\r?\n/).filter(v=>v.trim()).length:Math.ceil(months/step);input('installment_count').value=Number.isFinite(count)?count:'';
        let preview='';try{const raw=input('amount').value.trim().replaceAll(' ','');if(/^[0-9]+(?:[.,][0-9]{1,2})?$/.test(raw)&&count>=2){const [whole,fraction='']=raw.split(/[.,]/),total=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0')),manual=input('installment_amount').value.trim().replaceAll(' ',''),parts=manual.split(/[.,]/),per=manual&&/^[0-9]+(?:[.,][0-9]{1,2})?$/.test(manual)?BigInt(parts[0])*100n+BigInt((parts[1]||'').padEnd(2,'0')):total/BigInt(count),last=total-per*BigInt(count-1);if(per>0n&&last>0n)preview=t('Cicilan terakhir: {amount}',{amount:(account.selectedOptions[0]?.dataset.currency||'')+' '+(last/100n)+'.'+(last%100n).toString().padStart(2,'0')});}}catch{}
        form.querySelector('[data-installment-preview]').textContent=preview;
      }
      installment.addEventListener('change',installments);for(const control of fields.querySelectorAll('input,select,textarea'))control.addEventListener('input',installments);input('amount').addEventListener('input',installments);installments();
    }
    form.addEventListener('submit',event=>{if(form.dataset.pending==='true'){event.preventDefault();return;}form.dataset.pending='true';form.setAttribute('aria-busy','true');});
    window.addEventListener('pageshow',()=>{delete form.dataset.pending;form.removeAttribute('aria-busy');});
  }
})();
