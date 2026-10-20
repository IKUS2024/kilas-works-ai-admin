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
      const parent=box.querySelector('[data-expense-parent]'),child=box.querySelector('[data-expense-child]'),label=box.querySelector('[data-expense-child-label]'),summary=box.querySelector('[data-expense-cascade]'),panel=box.querySelector('[data-expense-cascade-panel]');let retainedParent=null;
      const close=()=>{panel.hidden=true;summary.setAttribute('aria-expanded','false');};
      function icon(option){return (box.querySelector('[data-expense-category-icons]').content.querySelector('[data-category-icon-id="'+option.value+'"]')||box.querySelector('[data-expense-category-icons]').content.querySelector('[data-category-icon-default]')).cloneNode(true);}
      function choice(container,text,fn,option){
        const button=document.createElement('button');button.type='button';
        if(option){const glyph=icon(option);if(glyph)button.append(glyph);button.dataset.expenseChoice=option.value;button.setAttribute('aria-pressed',String(option.value===(child.value||parent.value)));}
        const copy=document.createElement('span');copy.textContent=text;button.append(copy);
        button.onclick=event=>{event.stopPropagation();fn();};container.append(button);return button;
      }
      function show(){
        panel.replaceChildren();panel.hidden=false;summary.setAttribute('aria-expanded','true');
        for(const option of parent.options){
          if(!option.value||option.value==='__add__')continue;
          const children=[...child.options].filter(o=>o.value&&o.value!=='__add__'&&o.dataset.parent===option.value);
          const group=document.createElement('details'),head=document.createElement('summary');group.dataset.expenseGroup=option.value;group.open=parent.value===option.value;
          const glyph=icon(option);if(glyph)head.append(glyph);
          const name=document.createElement('strong');name.textContent=option.textContent;head.append(name);
          const selected=document.createElement('span');selected.className='expense-category-selected';selected.textContent=parent.value===option.value?'✓':'';selected.setAttribute('aria-hidden','true');head.append(selected);
          const chevron=document.createElement('span');chevron.className='finance-category-chevron';chevron.textContent='›';head.append(chevron);group.append(head);
          const body=document.createElement('div');body.className='expense-category-children';group.append(body);
          head.addEventListener('click',()=>{if(parent.value!==option.value){parent.value=option.value;parent.dispatchEvent(new Event('change'));}for(const other of panel.querySelectorAll('details')){if(other!==group)other.open=false;}});
          for(const leaf of children)choice(body,leaf.textContent,()=>{parent.value=option.value;update();child.value=leaf.value;child.dispatchEvent(new Event('change'));close();summary.focus();},leaf);
          if(!children.length)choice(body,'Choose this category',()=>{parent.value=option.value;parent.dispatchEvent(new Event('change'));close();summary.focus();},option);
          choice(body,'Add subcategory…',()=>{parent.value=option.value;update();close();create(child,true);});panel.append(group);
        }
        choice(panel,'Add category…',()=>{close();create(parent,false);});
      }
      summary.onclick=()=>panel.hidden?show():close();box.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){event.preventDefault();event.stopPropagation();close();summary.focus();}});document.addEventListener('click',event=>{if(!box.contains(event.target))close();});
      function update(){for(const group of panel.querySelectorAll('[data-expense-group]'))group.querySelector('.expense-category-selected').textContent=group.dataset.expenseGroup===parent.value?'✓':'';for(const button of panel.querySelectorAll('[data-expense-choice]'))button.setAttribute('aria-pressed',String(button.dataset.expenseChoice===(child.value||parent.value)));let count=0;for(const option of child.options){if(!option.value||option.value==='__add__')continue;option.hidden=option.disabled=option.dataset.parent!==parent.value;if(!option.disabled)count++;}label.hidden=true;child.disabled=!parent.value;parent.required=child.required=false;summary.textContent=parent.value?(parent.selectedOptions[0]?.textContent||''):'Choose a category';box.dataset.childRequired=String(!!count&&parent.value!==retainedParent);const empty=box.querySelector('[data-expense-empty-child]');if(empty)empty.disabled=!!parent.value;if(child.selectedOptions[0]?.disabled)child.value='';const display=box.querySelector('[data-expense-subcategory-display]');display.textContent=child.value?child.selectedOptions[0].textContent:display.dataset.emptyText;display.classList.toggle('is-empty',!child.value);summary.textContent=parent.value?(parent.selectedOptions[0]?.textContent||''):'Choose a category';}
      if(initial){const leaf=[...child.options].find(o=>o.value===String(initial));parent.value=leaf?leaf.dataset.parent:String(initial);if(!leaf)retainedParent=String(initial);if(leaf)child.value=String(initial);}
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
            a.append(new Option('Add category…','__add__'));b.append(new Option('Add subcategory…','__add__'));a.value=av;b.value=bv;
          }
          field.value=String(result.category.id);if(!isChild)child.value='';update();field.dataset.previous=field.value;if(!isChild)show();
        }catch(error){window.alert(error.message||t('Kategori belum dapat disimpan.'));}finally{refresh();}
      }
      for(const [field,isChild] of [[parent,false],[child,true]])field.addEventListener('change',()=>{if(field.value==='__add__'){create(field,isChild);return;}field.dataset.previous=field.value;if(!isChild){child.value='';child.dataset.previous='';}update();});
      box.refreshExpensePicker=update;box.openExpensePicker=show;update();parent.dataset.previous=parent.value;child.dataset.previous=child.value;
    }
    picker(single,form.dataset.initialCategory);
    if(form.hasAttribute('data-expense-category-only')){form.addEventListener('submit',event=>{const a=single.querySelector('[data-expense-parent]'),b=single.querySelector('[data-expense-child]');if(!a.value||(single.dataset.childRequired==='true'&&!b.value)){event.preventDefault();single.openExpensePicker();summaryFocus();}});function summaryFocus(){single.querySelector('[data-expense-cascade]').focus();}continue;}
    function row(value){if(rows.children.length>=20)return;const fragment=form.querySelector('[data-expense-split-template]').content.cloneNode(true),box=fragment.firstElementChild;rows.append(box);picker(box,value?.category_id);if(value){const input=box.querySelector('[name="split_amount"]');input.value=(BigInt(value.amount_minor)/100n).toString()+'.'+(BigInt(value.amount_minor)%100n).toString().padStart(2,'0');}box.querySelector('[data-expense-remove-split]').onclick=()=>{if(rows.children.length>2)box.remove();};}
    function refresh(){if(!split){single.refreshExpensePicker();return;}rows.hidden=add.hidden=!split.checked;single.hidden=split.checked;for(const control of single.querySelectorAll('select,button'))control.disabled=split.checked;if(!split.checked)single.refreshExpensePicker();for(const control of rows.querySelectorAll('input,select,button'))control.disabled=!split.checked;if(split.checked)for(const box of rows.children)box.refreshExpensePicker();}
    const initial=JSON.parse(form.dataset.initialSplits||'[]');for(const value of initial)row(value);if(initial.length)split.checked=true;while(rows.children.length<2)row();
    split.addEventListener('change',refresh);add.onclick=()=>row();refresh();
    // Restore selected leaf categories after initialization (refresh filters child lists).
    if(initial.length)[...rows.children].forEach((box,i)=>{const leaf=box.querySelector('[data-expense-child]');if([...leaf.options].some(o=>o.value===String(initial[i].category_id))){leaf.value=String(initial[i].category_id);box.refreshExpensePicker();}});
    const account=form.querySelector('[data-expense-account]');function currency(){form.querySelector('[data-expense-currency]').textContent=account.selectedOptions[0]?.dataset.currency||'';}account.addEventListener('change',currency);currency();
    const photo=form.querySelector('[data-expense-photo]'),photoName=form.querySelector('[data-expense-photo-name]'),photoPlaceholder=form.querySelector('[data-expense-photo-placeholder]'),photoClear=form.querySelector('[data-expense-photo-clear]'),photoError=form.querySelector('[data-expense-photo-error]');
    let photoPreview=form.querySelector('[data-expense-photo-preview]'),photoURL=null,photoPending=null,photoRevision=0;
    const photoInvalid='Gunakan foto struk JPG, PNG, atau WebP yang valid, maksimal 20 MiB.';
    function clearPhoto(empty=true,message=''){
      photoRevision++;
      if(photoPending){photoPending.onload=photoPending.onerror=null;photoPending.removeAttribute('src');photoPending=null;}
      photoPreview.removeAttribute('src');photoPreview.hidden=true;
      if(photoURL){URL.revokeObjectURL(photoURL);photoURL=null;}
      if(empty)photo.value='';photo.setCustomValidity('');
      photoName.textContent='';photoPlaceholder.hidden=false;photoClear.hidden=true;photoError.textContent=message?t(message):'';photoError.hidden=!message;
    }
    photo.addEventListener('change',async()=>{
      const file=photo.files[0];clearPhoto(false);if(!file)return;
      const revision=photoRevision,current=()=>revision===photoRevision&&form.isConnected&&photo.files[0]===file;
      photoName.textContent=file.name;photoClear.hidden=false;
      if(!/\.(jpe?g|png|webp)$/i.test(file.name)||!file.size||file.size>20*1024*1024){clearPhoto(true,photoInvalid);return;}
      try{
        // Inspect only12 bytes; never copy the complete photo into a data URL.
        const bytes=new Uint8Array(await file.slice(0,12).arrayBuffer());if(!current())return;
        const jpeg=bytes[0]===255&&bytes[1]===216&&bytes[2]===255,png=[137,80,78,71,13,10,26,10].every((v,i)=>bytes[i]===v),webp=[82,73,70,70].every((v,i)=>bytes[i]===v)&&[87,69,66,80].every((v,i)=>bytes[i+8]===v);
        if(!(/\.jpe?g$/i.test(file.name)?jpeg:/\.png$/i.test(file.name)?png:webp)){clearPhoto(true,photoInvalid);return;}
        const url=photoURL=URL.createObjectURL(file),image=new Image();photoPending=image;image.alt=photoPreview.alt;image.dataset.expensePhotoPreview='';image.decoding='async';image.hidden=true;
        image.onload=()=>{
          if(!current())return;
          if(!image.naturalWidth||image.naturalWidth*image.naturalHeight>80000000){clearPhoto(true,photoInvalid);return;}
          image.onload=image.onerror=null;photoPending=null;photoPreview.replaceWith(image);photoPreview=image;image.hidden=false;photoPlaceholder.hidden=true;
        };
        image.onerror=()=>{if(current())clearPhoto(true,photoInvalid);};image.src=url;
      }catch{if(current())clearPhoto(true,photoInvalid);}
    });
    photoClear.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();if(form.dataset.pending==='true'||form.dataset.submitting==='true')return;clearPhoto();photo.focus();});
    form.addEventListener('reset',()=>clearPhoto());form.closest('dialog')?.addEventListener('close',()=>clearPhoto());window.addEventListener('pagehide',()=>clearPhoto());
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
    form.addEventListener('submit',event=>{for(const box of (split.checked?[...rows.children]:[single])){const a=box.querySelector('[data-expense-parent]'),b=box.querySelector('[data-expense-child]');if(!a.value||(box.dataset.childRequired==='true'&&!b.value)){event.preventDefault();box.openExpensePicker();box.querySelector('[data-expense-cascade]').focus();return;}}if(form.dataset.pending==='true'){event.preventDefault();return;}form.dataset.pending='true';photoClear.disabled=true;form.setAttribute('aria-busy','true');});
    window.addEventListener('pageshow',()=>{delete form.dataset.pending;photoClear.disabled=false;form.removeAttribute('aria-busy');});
  }
})();
