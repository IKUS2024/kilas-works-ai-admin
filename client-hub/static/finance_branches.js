'use strict';
for (const category of document.querySelectorAll('[data-other-category]')) {
  const form = category.closest('form');
  const kind = form.querySelector('[name="direction"]');
  const other = form.querySelector('[data-other-field]');
  function refresh() {
    for (const option of category.options) {
      if (kind && option.dataset.direction) {
        option.disabled = option.dataset.direction !== kind.value;
        option.hidden = option.disabled;
      }
    }
    if (!category.selectedOptions.length || category.selectedOptions[0].disabled) {
      const placeholder = [...category.options].find(option => option.value === '');
      const available = [...category.options].find(option => option.value && !option.disabled);
      if (placeholder) category.value = '';
      else if (available) category.value = available.value;
    }
    const visible = category.selectedOptions[0]?.dataset.other === 'true';
    other.hidden = !visible;
    if (other.style) other.style.display = visible ? '' : 'none';
    const otherInput = other.querySelector('input');
    otherInput.required = visible;
    otherInput.disabled = !visible;
  }
  category.addEventListener('change', refresh);
  if (kind) kind.addEventListener('change', refresh);
  refresh();
}



// A top-level category may expose one level of subcategories. Utility defaults use
// this for Listrik, Air, Internet, Telepon, Gas, Laundry, and Sampah / Kebersihan.
for (const category of document.querySelectorAll('[data-other-category]')) {
  const form=category.closest('form');
  const field=form && form.querySelector('[data-subcategory-field]');
  const subcategory=form && form.querySelector('[data-subcategory-select]');
  const direction=form && form.querySelector('[name="direction"]');
  if(!form||!field||!subcategory)continue;

  let lastParentId=String(category.value||'');
  const refresh=()=>{
    const parentId=String(category.value||'');
    const parentChanged=parentId!==lastParentId;
    const kind=direction ? direction.value : '';
    let count=0;
    for(const option of subcategory.options){
      if(!option.value)continue;
      const visible=String(option.dataset.parentId||'')===parentId &&
        (!kind || !option.dataset.direction || option.dataset.direction===kind);
      option.disabled=!visible;
      option.hidden=!visible;
      if(visible)count+=1;
    }
    const selected=subcategory.selectedOptions[0];
    if(parentChanged || (selected && selected.disabled))subcategory.selectedIndex=-1;
    field.hidden=count===0;
    if(field.style)field.style.display=count===0?'none':'';
    subcategory.disabled=count===0;
    subcategory.required=count>0;
    if(count===0){
      subcategory.selectedIndex=-1;
    }else{
      const current=subcategory.selectedOptions[0];
      if(!current || current.disabled)subcategory.selectedIndex=-1;
    }
    lastParentId=parentId;
  };
  category.addEventListener('change',refresh);
  if(direction)direction.addEventListener('change',refresh);
  refresh();
}



// Manage categories and one-level subcategories without leaving the transaction sheet.
// The same workspace-scoped records feed transactions, budgets, recurring costs,
// reports, and (Business only) AI Finance.
for (const quick of document.querySelectorAll('[data-category-quick-add]')) {
  const form=quick.closest('form');
  const category=quick.querySelector('[data-other-category]');
  const subcategory=form && form.querySelector('[data-subcategory-select]');
  const direction=form && form.querySelector('[name="direction"]');
  const toggle=quick.querySelector('[data-category-add-toggle]');
  const panel=quick.querySelector('[data-category-add-panel]');
  const input=quick.querySelector('[data-category-name]');
  const save=quick.querySelector('[data-category-save]');
  const cancel=quick.querySelector('[data-category-cancel]');
  const status=quick.querySelector('[data-category-status]');
  const kindLabel=quick.querySelector('[data-category-kind]');
  const list=quick.querySelector('[data-category-list]');
  const level=quick.querySelector('[data-category-level]');
  const parentField=quick.querySelector('[data-category-parent-field]');
  const parentSelect=quick.querySelector('[data-category-parent]');
  if(!form||!category||!subcategory||!direction||!toggle||!panel||!input||!save||!cancel||!status||!list||!level||!parentField||!parentSelect)continue;

  const labelForDirection=()=>direction.value==='INCOME'?'Pemasukan':'Pengeluaran';
  const isOtherName=name=>['Lainnya','Pendapatan Lain','Pengeluaran Lain'].includes(name);
  const rowsByDirection=new Map([['INCOME',[]],['EXPENSE',[]]]);

  for(const option of category.options){
    if(!option.value||!option.dataset.direction)continue;
    rowsByDirection.get(option.dataset.direction)?.push({
      id:String(option.value),name:String(option.textContent||'').trim(),
      direction:option.dataset.direction,parent_category_id:null,parent_name:null
    });
  }
  for(const option of subcategory.options){
    if(!option.value||!option.dataset.direction)continue;
    const parentId=String(option.dataset.parentId||'');
    const parent=[...category.options].find(item=>String(item.value)===parentId);
    rowsByDirection.get(option.dataset.direction)?.push({
      id:String(option.value),name:String(option.textContent||'').trim(),
      direction:option.dataset.direction,parent_category_id:parentId||null,
      parent_name:parent?String(parent.textContent||'').trim():null
    });
  }

  const setStatus=(message,type='')=>{
    status.textContent=message||'';
    status.classList.remove('error','success');
    if(type)status.classList.add(type);
  };
  const currentRows=()=>rowsByDirection.get(direction.value)||[];
  const parentRows=()=>currentRows().filter(item=>!item.parent_category_id);

  const syncParentChoices=()=>{
    const previous=parentSelect.value;
    parentSelect.replaceChildren();
    for(const item of parentRows()){
      const option=document.createElement('option');
      option.value=String(item.id);
      option.textContent=item.name;
      parentSelect.appendChild(option);
    }
    if([...parentSelect.options].some(option=>option.value===previous))parentSelect.value=previous;
    parentField.hidden=level.value!=='subcategory';
    parentSelect.disabled=level.value!=='subcategory';
    parentSelect.required=level.value==='subcategory';
    save.textContent=level.value==='subcategory'?'Tambah subkategori & pilih':'Tambah kategori & pilih';
  };

  const rebuildSelectors=(preferredCategory='',preferredSubcategory='')=>{
    const categorySelection=String(preferredCategory||category.value||'');
    const subSelection=String(preferredSubcategory||subcategory.value||'');

    const mainPlaceholder=document.createElement('option');
    mainPlaceholder.value='';
    mainPlaceholder.textContent='Pilih kategori';
    mainPlaceholder.disabled=true;
    category.replaceChildren(mainPlaceholder);
    subcategory.replaceChildren();

    for(const kind of ['INCOME','EXPENSE']){
      for(const item of rowsByDirection.get(kind)||[]){
        const option=document.createElement('option');
        option.value=String(item.id);
        option.textContent=item.name;
        option.dataset.direction=kind;
        if(item.parent_category_id){
          option.dataset.parentId=String(item.parent_category_id);
          subcategory.appendChild(option);
        }else{
          option.dataset.other=isOtherName(item.name)?'true':'false';
          category.appendChild(option);
        }
      }
    }

    const preferredMain=[...category.options].find(option=>option.value===categorySelection);
    if(preferredMain&&preferredMain.value)category.value=preferredMain.value;
    else category.value='';

    if([...subcategory.options].some(option=>option.value===subSelection)){
      subcategory.value=subSelection;
    }
    category.dispatchEvent(new Event('change',{bubbles:true}));
    syncParentChoices();
    renderList();
  };

  const request=async(payload)=>{
    const endpoint=quick.dataset.categoryCreateUrl;
    if(!endpoint)throw new Error('Kategori belum bisa diubah dari halaman ini.');
    const body=new FormData();
    const csrf=form.querySelector('input[name="csrf_token"]');
    if(csrf)body.set('csrf_token',csrf.value);
    const branchId=quick.dataset.categoryBranch;
    if(branchId&&branchId!=='None')body.set('branch_id',branchId);
    body.set('direction',direction.value);
    Object.entries(payload).forEach(([key,value])=>{
      if(value!==null&&value!==undefined&&String(value)!=='')body.set(key,String(value));
    });
    const response=await fetch(endpoint,{
      method:'POST',body,credentials:'same-origin',
      headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||'Kategori belum bisa diubah.');
    return data;
  };

  const normalizeRows=rows=>(Array.isArray(rows)?rows:[]).map(item=>({
    id:String(item.id),name:String(item.name||'').trim(),direction:item.direction,
    parent_category_id:item.parent_category_id===null||item.parent_category_id===undefined?'':String(item.parent_category_id),
    parent_name:item.parent_name||null
  }));

  // The transaction sheet and the standalone Kategori sheet are two views of the
  // same workspace-scoped category records. Keep the second sheet live whenever
  // this inline editor changes Pemasukan or Pengeluaran so neither UI can drift.
  const categoryManagerRoot=document.querySelector('[data-category-manager-root]');
  const globalCategoryList=categoryManagerRoot&&categoryManagerRoot.querySelector('[data-category-record-list]');
  const globalParentSelect=categoryManagerRoot&&categoryManagerRoot.querySelector('[data-category-manager-parent]');
  const settingUrlFor=id=>{
    const template=categoryManagerRoot&&categoryManagerRoot.dataset.categorySettingUrlTemplate;
    return template ? template.replace(/\/0(?=\?|$)/,'/'+encodeURIComponent(String(id))) : '';
  };
  const globalMeta=item=>
    (item.direction==='INCOME'?'Pemasukan':'Pengeluaran')+
    (item.parent_name?' · Subkategori '+item.parent_name:'');
  const updateGlobalRow=(row,item)=>{
    if(!row)return;
    row.dataset.financeCategoryRecord=String(item.id);
    row.dataset.categoryDirection=item.direction;
    row.dataset.categoryParentId=item.parent_category_id||'';
    row.dataset.categoryParentName=item.parent_name||'';
    const name=row.querySelector('.finance-record-main strong');
    const meta=row.querySelector('.finance-record-sub');
    const input=row.querySelector('.finance-record-popover input[name="name"]');
    const formRow=row.querySelector('.finance-record-popover form');
    const deleteButton=row.querySelector('.finance-danger-soft');
    if(name)name.textContent=item.name;
    if(meta)meta.textContent=globalMeta(item);
    if(input)input.value=item.name;
    const action=settingUrlFor(item.id);
    if(formRow&&action)formRow.action=action;
    if(deleteButton){
      deleteButton.setAttribute(
        'onclick',
        'return confirm('+JSON.stringify('Hapus '+item.name+' dari daftar aktif? Riwayat lama dan transaksi yang sudah ada tetap tersimpan.')+');'
      );
    }
  };
  const syncGlobalCategoryRows=(kind,rows)=>{
    if(!globalCategoryList)return;
    const sameKind=[...globalCategoryList.querySelectorAll('[data-finance-category-record]')]
      .filter(row=>row.dataset.categoryDirection===kind);
    const activeIds=new Set(rows.map(item=>String(item.id)));
    for(const row of sameKind){
      if(!activeIds.has(String(row.dataset.financeCategoryRecord||'')))row.remove();
    }
    for(const item of rows){
      let row=[...globalCategoryList.querySelectorAll('[data-finance-category-record]')]
        .find(candidate=>String(candidate.dataset.financeCategoryRecord||'')===String(item.id));
      if(!row){
        const sample=[...globalCategoryList.querySelectorAll('[data-finance-category-record]')]
          .find(candidate=>candidate.dataset.categoryDirection===kind)
          ||globalCategoryList.querySelector('[data-finance-category-record]');
        if(sample){
          row=sample.cloneNode(true);
          const details=row.querySelector('details');
          if(details)details.removeAttribute('open');
          globalCategoryList.appendChild(row);
        }
      }
      updateGlobalRow(row,item);
    }

    if(globalParentSelect){
      const previous=globalParentSelect.value;
      for(const option of [...globalParentSelect.options]){
        if(option.dataset.direction===kind)option.remove();
      }
      for(const item of rows.filter(entry=>!entry.parent_category_id)){
        const option=document.createElement('option');
        option.value=String(item.id);
        option.dataset.direction=kind;
        option.textContent=item.name;
        globalParentSelect.appendChild(option);
      }
      if([...globalParentSelect.options].some(option=>option.value===previous)){
        globalParentSelect.value=previous;
      }
      globalParentSelect.dispatchEvent(new Event('change',{bubbles:true}));
    }
  };

  const applyResponse=(data,preferredCategory='',preferredSubcategory='')=>{
    const normalized=normalizeRows(data.options);
    rowsByDirection.set(direction.value,normalized);
    syncGlobalCategoryRows(direction.value,normalized);
    rebuildSelectors(preferredCategory,preferredSubcategory);
  };

  const beginInlineEdit=(row,item)=>{
    const wasChild=Boolean(item.parent_category_id);
    row.replaceChildren();
    row.classList.toggle('child',wasChild);

    const editor=document.createElement('div');
    editor.className='finance-category-inline-editor';
    const hint=document.createElement('small');
    hint.textContent=wasChild?'Subkategori '+(item.parent_name||''):'Kategori utama';
    const editInput=document.createElement('input');
    editInput.type='text';
    editInput.maxLength=160;
    editInput.value=item.name;
    editInput.setAttribute('aria-label','Nama kategori');
    editor.append(hint,editInput);

    const actions=document.createElement('div');
    actions.className='finance-category-quick-row-actions';
    const saveEdit=document.createElement('button');
    saveEdit.type='button';
    saveEdit.className='finance-category-quick-edit';
    saveEdit.textContent='Simpan';
    const abort=document.createElement('button');
    abort.type='button';
    abort.className='finance-category-quick-delete';
    abort.textContent='Batal';
    actions.append(saveEdit,abort);
    row.append(editor,actions);
    editInput.focus({preventScroll:true});
    editInput.select();

    const submit=async()=>{
      const name=String(editInput.value||'').trim();
      if(!name){
        setStatus('Nama kategori wajib diisi.','error');
        editInput.focus({preventScroll:true});
        return;
      }
      saveEdit.disabled=true;abort.disabled=true;
      setStatus('Menyimpan perubahan…');
      try{
        const mainBefore=category.value;
        const subBefore=subcategory.value;
        const data=await request({action:'edit',category_id:item.id,name});
        applyResponse(data,mainBefore,subBefore);
        const globalRow=document.querySelector('[data-finance-category-record="'+item.id+'"]');
        const globalName=globalRow&&globalRow.querySelector('.finance-record-main strong');
        if(globalName)globalName.textContent=name;
        setStatus(data.message||'Nama kategori diperbarui.','success');
      }catch(error){
        saveEdit.disabled=false;abort.disabled=false;
        setStatus(error&&error.message?error.message:'Kategori belum bisa diedit.','error');
      }
    };
    saveEdit.addEventListener('click',submit);
    abort.addEventListener('click',renderList);
    editInput.addEventListener('keydown',event=>{
      if(event.key==='Enter'){event.preventDefault();submit();}
      if(event.key==='Escape'){event.preventDefault();renderList();}
    });
  };

  function renderList(){
    list.replaceChildren();
    const rows=currentRows();
    const top=rows.filter(item=>!item.parent_category_id);
    const byParent=new Map();
    for(const item of rows.filter(item=>item.parent_category_id)){
      const key=String(item.parent_category_id);
      if(!byParent.has(key))byParent.set(key,[]);
      byParent.get(key).push(item);
    }

    const appendRow=(item,isChild)=>{
      const row=document.createElement('div');
      row.className='finance-category-quick-row'+(isChild?' child':'');
      row.dataset.categoryRow='';
      row.dataset.categoryId=String(item.id);

      const copy=document.createElement('div');
      copy.className='finance-category-quick-copy';
      const label=document.createElement('span');
      label.textContent=(isChild?'↳ ':'')+item.name;
      const meta=document.createElement('small');
      meta.textContent=isChild?'Subkategori '+(item.parent_name||''):'Kategori utama';
      copy.append(label,meta);

      const actions=document.createElement('div');
      actions.className='finance-category-quick-row-actions';
      const edit=document.createElement('button');
      edit.type='button';
      edit.className='finance-category-quick-edit';
      edit.dataset.categoryEdit='';
      edit.textContent='Edit';
      const remove=document.createElement('button');
      remove.type='button';
      remove.className='finance-category-quick-delete';
      remove.dataset.categoryDelete='';
      remove.textContent='Hapus';
      actions.append(edit,remove);
      row.append(copy,actions);
      list.appendChild(row);
    };

    for(const parent of top){
      appendRow(parent,false);
      for(const child of byParent.get(String(parent.id))||[])appendRow(child,true);
    }
    const known=new Set(top.map(item=>String(item.id)));
    for(const child of rows.filter(item=>item.parent_category_id&&!known.has(String(item.parent_category_id)))){
      appendRow(child,true);
    }
    syncParentChoices();
  }

  const syncKind=()=>{
    if(kindLabel)kindLabel.textContent=labelForDirection();
    input.placeholder=level.value==='subcategory'
      ?'Contoh: Listrik'
      :(direction.value==='INCOME'?'Contoh: Pendapatan Konten':'Contoh: Perawatan');
    syncParentChoices();
    renderList();
  };
  const closePanel=()=>{
    panel.hidden=true;
    toggle.setAttribute('aria-expanded','false');
    setStatus('');
  };

  toggle.setAttribute('aria-expanded','false');
  toggle.addEventListener('click',()=>{
    panel.hidden=!panel.hidden;
    toggle.setAttribute('aria-expanded',panel.hidden?'false':'true');
    setStatus('');
    syncKind();
    if(!panel.hidden)input.focus({preventScroll:true});
  });
  cancel.addEventListener('click',()=>{
    input.value='';
    level.value='category';
    closePanel();
    category.focus({preventScroll:true});
  });
  direction.addEventListener('change',syncKind);
  level.addEventListener('change',syncKind);
  input.addEventListener('keydown',event=>{
    if(event.key==='Enter'){event.preventDefault();save.click();}
  });

  save.addEventListener('click',async()=>{
    const name=String(input.value||'').trim();
    if(!name){
      setStatus('Nama kategori wajib diisi.','error');
      input.focus({preventScroll:true});
      return;
    }
    const addingChild=level.value==='subcategory';
    const parentId=addingChild?String(parentSelect.value||''):'';
    if(addingChild&&!parentId){
      setStatus('Pilih kategori utama untuk subkategori ini.','error');
      parentSelect.focus({preventScroll:true});
      return;
    }
    save.disabled=true;cancel.disabled=true;
    setStatus(addingChild?'Menambahkan subkategori…':'Menambahkan kategori…');
    try{
      const data=await request({
        action:'create',name,
        parent_category_id:addingChild?parentId:''
      });
      if(!data.category)throw new Error('Kategori belum bisa dimuat.');
      const created=data.category;
      if(created.parent_category_id){
        applyResponse(data,String(created.parent_category_id),String(created.id));
      }else{
        applyResponse(data,String(created.id),'');
      }
      input.value='';
      setStatus(data.message||(addingChild?'Subkategori ditambahkan.':'Kategori ditambahkan.'),'success');
    }catch(error){
      setStatus(error&&error.message?error.message:'Kategori belum bisa ditambahkan. Coba lagi.','error');
    }finally{
      save.disabled=false;cancel.disabled=false;
    }
  });

  list.addEventListener('click',async event=>{
    const editButton=event.target.closest('[data-category-edit]');
    const deleteButton=event.target.closest('[data-category-delete]');
    const button=editButton||deleteButton;
    if(!button)return;
    const row=button.closest('[data-category-row]');
    const categoryId=String(row&&row.dataset.categoryId||'');
    const item=currentRows().find(entry=>String(entry.id)===categoryId);
    if(!item)return;

    if(editButton){
      beginInlineEdit(row,item);
      return;
    }

    const kind=item.parent_category_id?'subkategori':'kategori';
    if(!window.confirm('Hapus '+kind+' "'+item.name+'" dari daftar aktif? Riwayat lama tetap aman.'))return;
    deleteButton.disabled=true;
    setStatus('Menghapus '+kind+'…');
    const keepMain=category.value===categoryId?'':category.value;
    const keepSub=subcategory.value===categoryId?'':subcategory.value;
    try{
      const data=await request({action:'delete',category_id:categoryId});
      applyResponse(data,keepMain,keepSub);
      const globalRow=document.querySelector('[data-finance-category-record="'+categoryId+'"]');
      if(globalRow)globalRow.remove();
      setStatus(data.message||'Kategori dihapus dari daftar aktif.','success');
    }catch(error){
      deleteButton.disabled=false;
      setStatus(error&&error.message?error.message:'Kategori belum bisa dihapus.','error');
    }
  });

  syncKind();
}


// Category settings dialog: the same create endpoint can add either a
// top-level category or a subcategory under an active parent.
for (const form of document.querySelectorAll('[data-category-manager-form]')) {
  const direction=form.querySelector('[data-category-manager-direction]');
  const level=form.querySelector('[data-category-manager-level]');
  const parentField=form.querySelector('[data-category-manager-parent-field]');
  const parent=form.querySelector('[data-category-manager-parent]');
  const submit=form.querySelector('[data-category-manager-submit]');
  if(!direction||!level||!parentField||!parent||!submit)continue;

  const refresh=()=>{
    const wantsChild=level.value==='subcategory';
    let firstVisible=null;
    for(const option of parent.options){
      const visible=option.dataset.direction===direction.value;
      option.hidden=!visible;
      option.disabled=!visible;
      if(visible&&!firstVisible)firstVisible=option;
    }
    if(parent.selectedOptions[0]?.disabled&&firstVisible)parent.value=firstVisible.value;
    parentField.hidden=!wantsChild;
    parent.disabled=!wantsChild;
    parent.required=wantsChild;
    submit.textContent=wantsChild?'Tambah Subkategori':'Tambah Kategori';
  };
  direction.addEventListener('change',refresh);
  level.addEventListener('change',refresh);
  refresh();
}


const setCategoryDialogDirection=(dialog,kind)=>{
  if(!dialog || (kind!=='INCOME' && kind!=='EXPENSE'))return;
  for(const tab of dialog.querySelectorAll('[data-category-direction-tab]')){
    const active=tab.dataset.categoryDirectionTab===kind;
    tab.classList.toggle('active',active);
    tab.setAttribute('aria-selected',active?'true':'false');
  }
  for(const section of dialog.querySelectorAll('[data-category-direction-section]')){
    section.hidden=section.dataset.categoryDirectionSection!==kind;
  }
  const managerDirection=dialog.querySelector('[data-category-manager-direction]');
  if(managerDirection && managerDirection.value!==kind){
    managerDirection.value=kind;
    managerDirection.dispatchEvent(new Event('change',{bubbles:true}));
  }
};

for(const dialog of document.querySelectorAll('[data-category-manager-root]')){
  for(const tab of dialog.querySelectorAll('[data-category-direction-tab]')){
    tab.addEventListener('click',()=>{
      setCategoryDialogDirection(dialog,tab.dataset.categoryDirectionTab);
    });
  }
  const initial=dialog.querySelector('[data-category-direction-tab].active')?.dataset.categoryDirectionTab||'INCOME';
  setCategoryDialogDirection(dialog,initial);
}

const categoryEditor=document.querySelector('[data-category-editor]');
if(categoryEditor){
  const manager=document.querySelector('[data-category-manager-root]');
  const title=categoryEditor.querySelector('[data-category-editor-title]');
  const createForm=categoryEditor.querySelector('[data-category-create-form]');
  const editForm=categoryEditor.querySelector('[data-category-edit-form]');
  const directionInput=categoryEditor.querySelector('[data-category-editor-direction]');
  const parentField=categoryEditor.querySelector('[data-category-editor-parent-field]');
  const parent=categoryEditor.querySelector('[data-category-editor-parent]');
  const createName=categoryEditor.querySelector('[data-category-editor-create-name]');
  const nameLabel=categoryEditor.querySelector('[data-category-editor-name-label]');
  const createSubmit=categoryEditor.querySelector('[data-category-editor-submit]');
  const childChoice=categoryEditor.querySelector('[data-category-editor-child-choice]');
  const childChoiceInputs=[...categoryEditor.querySelectorAll('[data-category-editor-child-choice-input]')];
  const childBuilder=categoryEditor.querySelector('[data-category-editor-child-builder]');
  const childList=categoryEditor.querySelector('[data-category-editor-child-list]');
  const addChildRow=categoryEditor.querySelector('[data-category-editor-add-child-row]');
  const editName=categoryEditor.querySelector('[data-category-editor-edit-name]');
  let editorMode='category';

  const currentDirection=()=>manager?.querySelector('[data-category-direction-tab].active')?.dataset.categoryDirectionTab||'INCOME';
  const showEditor=()=>{
    if(typeof categoryEditor.showModal==='function')categoryEditor.showModal();
    else categoryEditor.setAttribute('open','');
  };
  const childEnabled=()=>childChoiceInputs.some(input=>input.checked&&input.value==='1');
  const updateRemoveButtons=()=>{
    if(!childList)return;
    const rows=[...childList.querySelectorAll('[data-category-editor-child-row]')];
    for(const row of rows){
      const remove=row.querySelector('[data-category-editor-remove-child]');
      if(remove)remove.hidden=rows.length===1;
    }
  };
  const updateChildBuilder=()=>{
    const enabled=editorMode==='category'&&childEnabled();
    if(childBuilder)childBuilder.hidden=!enabled;
    if(childList){
      const inputs=[...childList.querySelectorAll('[data-category-editor-child-name]')];
      for(const [index,input] of inputs.entries()){
        input.disabled=!enabled;
        input.required=enabled&&index===0;
      }
    }
  };
  const resetChildRows=()=>{
    if(!childList)return;
    const rows=[...childList.querySelectorAll('[data-category-editor-child-row]')];
    for(const row of rows.slice(1))row.remove();
    const first=childList.querySelector('[data-category-editor-child-row]');
    if(first){
      const input=first.querySelector('[data-category-editor-child-name]');
      if(input)input.value='';
    }
    const noChoice=childChoiceInputs.find(input=>input.value==='0');
    if(noChoice)noChoice.checked=true;
    updateRemoveButtons();
    updateChildBuilder();
  };
  const refreshParents=()=>{
    if(!parent)return;
    const kind=directionInput?.value||currentDirection();
    let first=null;
    for(const option of parent.options){
      const visible=option.dataset.direction===kind;
      option.hidden=!visible;
      option.disabled=!visible;
      if(visible&&!first)first=option;
    }
    if(first && (!parent.selectedOptions.length || parent.selectedOptions[0].disabled)){
      parent.value=first.value;
    }
    const directChild=editorMode==='subcategory';
    if(parentField)parentField.hidden=!directChild;
    parent.disabled=!directChild;
    parent.required=directChild;
    if(childChoice)childChoice.hidden=directChild;
    if(nameLabel)nameLabel.textContent=directChild?'Nama subkategori':'Nama kategori';
    if(createName)createName.placeholder=directChild?'Contoh: Internet':'Contoh: Operasional';
    if(createSubmit)createSubmit.textContent=directChild?'Tambah Subkategori':'Tambah Kategori';
    updateChildBuilder();
  };

  for(const input of childChoiceInputs){
    input.addEventListener('change',()=>{
      updateChildBuilder();
      if(childEnabled()){
        const first=childList?.querySelector('[data-category-editor-child-name]');
        if(first)first.focus({preventScroll:true});
      }
    });
  }

  if(addChildRow&&childList){
    addChildRow.addEventListener('click',()=>{
      const source=childList.querySelector('[data-category-editor-child-row]');
      if(!source)return;
      const row=source.cloneNode(true);
      const input=row.querySelector('[data-category-editor-child-name]');
      if(input){
        input.value='';
        input.disabled=false;
        input.required=false;
      }
      const remove=row.querySelector('[data-category-editor-remove-child]');
      if(remove)remove.hidden=false;
      childList.appendChild(row);
      updateRemoveButtons();
      if(input)input.focus({preventScroll:true});
    });
    childList.addEventListener('click',(event)=>{
      const remove=event.target.closest('[data-category-editor-remove-child]');
      if(!remove)return;
      const row=remove.closest('[data-category-editor-child-row]');
      if(!row)return;
      row.remove();
      updateRemoveButtons();
    });
  }

  for(const button of document.querySelectorAll('[data-category-create-popup]')){
    button.addEventListener('click',()=>{
      editorMode='category';
      const kind=currentDirection();
      if(title)title.textContent='Tambah Kategori';
      if(createForm)createForm.hidden=false;
      if(editForm)editForm.hidden=true;
      if(directionInput)directionInput.value=kind;
      if(createName)createName.value='';
      resetChildRows();
      refreshParents();
      showEditor();
      if(createName)createName.focus({preventScroll:true});
    });
  }

  for(const button of document.querySelectorAll('[data-category-add-child-popup]')){
    button.addEventListener('click',()=>{
      editorMode='subcategory';
      const kind=String(button.dataset.categoryDirection||currentDirection());
      const parentId=String(button.dataset.categoryParentId||'');
      const parentName=String(button.dataset.categoryParentName||'');
      if(!parentId)return;
      if(title)title.textContent='Tambah Subkategori'+(parentName?' · '+parentName:'');
      if(createForm)createForm.hidden=false;
      if(editForm)editForm.hidden=true;
      if(directionInput)directionInput.value=kind;
      if(createName)createName.value='';
      resetChildRows();
      refreshParents();
      if(parent && [...parent.options].some(option=>option.value===parentId)){
        parent.value=parentId;
      }
      showEditor();
      if(createName)createName.focus({preventScroll:true});
    });
  }

  for(const button of document.querySelectorAll('[data-category-edit-popup]')){
    button.addEventListener('click',()=>{
      const id=String(button.dataset.categoryId||'');
      const name=String(button.dataset.categoryName||'');
      const kind=String(button.dataset.categoryKind||'category');
      const template=categoryEditor.dataset.categorySettingUrlTemplate||'';
      if(!id||!template)return;
      if(title)title.textContent=kind==='subcategory'?'Edit Subkategori':'Edit Kategori';
      if(createForm)createForm.hidden=true;
      if(editForm){
        editForm.hidden=false;
        editForm.action=template.replace(/\/0(?=\?|$)/,'/'+encodeURIComponent(id));
      }
      if(editName){
        editName.value=name;
        editName.focus({preventScroll:true});
        editName.select();
      }
      showEditor();
    });
  }

  refreshParents();
}


// Account type choices are business-level preferences. Users can add or remove
// choices here without leaving the account form; existing accounts keep their
// assigned label even when that label is removed from future choices.
for (const manager of document.querySelectorAll('[data-account-type-manager]')) {
  const select=manager.querySelector('[data-account-type-select]');
  const toggle=manager.querySelector('[data-account-type-toggle]');
  const panel=manager.querySelector('[data-account-type-panel]');
  const input=manager.querySelector('[data-account-type-name]');
  const add=manager.querySelector('[data-account-type-add]');
  const list=manager.querySelector('[data-account-type-list]');
  const status=manager.querySelector('[data-account-type-status]');
  if(!select||!toggle||!panel||!input||!add||!list||!status)continue;

  const setStatus=(message,type='')=>{
    status.textContent=message||'';
    status.classList.remove('error','success');
    if(type)status.classList.add(type);
  };
  const render=(options,preferred='')=>{
    const previous=preferred||select.value;
    select.replaceChildren();
    list.replaceChildren();
    const rows=Array.isArray(options)?options:[];
    if(!rows.length){
      const empty=document.createElement('option');
      empty.value='';
      empty.textContent='Tambah tipe terlebih dahulu';
      empty.disabled=true;
      empty.selected=true;
      select.appendChild(empty);
    }
    for(const item of rows){
      const name=String(item && item.name || '').trim();
      if(!name)continue;
      const option=document.createElement('option');
      option.value=name;
      option.textContent=name;
      select.appendChild(option);

      const row=document.createElement('div');
      row.className='finance-account-type-row';
      row.dataset.accountTypeRow='';
      row.dataset.name=name;
      const label=document.createElement('span');
      label.textContent=name;
      const remove=document.createElement('button');
      remove.type='button';
      remove.className='finance-account-type-delete';
      remove.dataset.accountTypeDelete='';
      remove.textContent='Hapus';
      row.append(label,remove);
      list.appendChild(row);
    }
    const preferredOption=[...select.options].find(option=>option.value===previous);
    if(preferredOption)select.value=previous;
    else if(select.options.length && !select.options[0].disabled)select.selectedIndex=0;
  };
  const request=async(action,name)=>{
    const endpoint=panel.dataset.accountTypeUrl;
    if(!endpoint)throw new Error('Tipe tempat uang belum bisa diubah dari halaman ini.');
    const body=new FormData();
    const csrf=manager.querySelector('input[name="csrf_token"]');
    if(csrf)body.set('csrf_token',csrf.value);
    const branchId=panel.dataset.accountTypeBranch;
    if(branchId)body.set('branch_id',branchId);
    body.set('action',action);
    body.set('name',name);
    const response=await fetch(endpoint,{
      method:'POST',
      body,
      credentials:'same-origin',
      headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||'Tipe tempat uang belum bisa diubah.');
    return data;
  };

  toggle.setAttribute('aria-expanded','false');
  toggle.addEventListener('click',()=>{
    panel.hidden=!panel.hidden;
    toggle.setAttribute('aria-expanded',panel.hidden?'false':'true');
    setStatus('');
    if(!panel.hidden)input.focus({preventScroll:true});
  });
  input.addEventListener('keydown',event=>{
    if(event.key==='Enter'){
      event.preventDefault();
      add.click();
    }
  });
  add.addEventListener('click',async()=>{
    const name=String(input.value||'').trim();
    if(!name){
      setStatus('Nama tipe wajib diisi.','error');
      input.focus({preventScroll:true});
      return;
    }
    add.disabled=true;
    setStatus('Menambahkan tipe…');
    try{
      const data=await request('create',name);
      render(data.options,name);
      input.value='';
      setStatus('Tipe ditambahkan dan langsung dipilih.','success');
    }catch(error){
      setStatus(error && error.message?error.message:'Tipe belum bisa ditambahkan.','error');
    }finally{
      add.disabled=false;
    }
  });
  list.addEventListener('click',async event=>{
    const button=event.target.closest('[data-account-type-delete]');
    if(!button)return;
    const row=button.closest('[data-account-type-row]');
    const name=String(row && row.dataset.name || '').trim();
    if(!name)return;
    if(!window.confirm('Hapus tipe "'+name+'" dari pilihan akun baru? Akun lama tetap aman.'))return;
    button.disabled=true;
    setStatus('Menghapus tipe…');
    const keep=select.value===name?'':select.value;
    try{
      const data=await request('delete',name);
      render(data.options,keep);
      setStatus('Tipe dihapus dari pilihan akun baru.','success');
    }catch(error){
      button.disabled=false;
      setStatus(error && error.message?error.message:'Tipe belum bisa dihapus.','error');
    }
  });
}

for (const amount of document.querySelectorAll('[data-idr-input]')) {
  function formatAmount() {
    const signed = amount.dataset?.idrSigned === 'true';
    const negative = signed && /^\s*-/.test(String(amount.value || ''));
    let digits = String(amount.value || '').replace(/\D/g, '').slice(0, 19);
    digits = digits.replace(/^0+(?=\d)/, '');
    if (!digits) {
      amount.value = negative ? '-' : '';
      return;
    }
    amount.value = (negative ? '-' : '') + digits.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }
  amount.addEventListener('input', formatAmount);
  amount.addEventListener('blur', formatAmount);
  formatAmount();
}


// Compact Finance mobile UI: open forms/settings as bottom-sheet dialogs instead of
// keeping every form expanded in the page flow. No financial state is stored client-side.
for (const trigger of document.querySelectorAll('[data-finance-open]')) {
  const id = trigger.dataset && trigger.dataset.financeOpen;
  if (!id) continue;
  trigger.addEventListener('click', () => {
    const dialog = document.getElementById && document.getElementById(id);
    if (!dialog) return;
    const forcedDirection = trigger.dataset && trigger.dataset.transactionDirection;
    if (forcedDirection && dialog.id === 'add-transaction-dialog') {
      const kind = dialog.querySelector('[name="direction"]');
      if (kind && (forcedDirection === 'INCOME' || forcedDirection === 'EXPENSE')) {
        kind.value = forcedDirection;
        kind.dispatchEvent(new Event('change', {bubbles:true}));
      }
    }
    if(dialog.id==='category-dialog'){
      const sourceForm=trigger.closest && trigger.closest('form');
      const sourceKind=sourceForm && sourceForm.querySelector('[name="direction"]');
      if(sourceKind && (sourceKind.value==='INCOME'||sourceKind.value==='EXPENSE')){
        setCategoryDialogDirection(dialog,sourceKind.value);
      }
    }
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    const focusable = dialog.querySelector && dialog.querySelector('input:not([type="hidden"]),select,textarea,button');
    if (focusable && typeof focusable.focus === 'function') focusable.focus({preventScroll:true});
  });
}
for (const trigger of document.querySelectorAll('[data-finance-close]')) {
  const id = trigger.dataset && trigger.dataset.financeClose;
  if (!id) continue;
  trigger.addEventListener('click', () => {
    const dialog = document.getElementById && document.getElementById(id);
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  });
}
for (const dialog of document.querySelectorAll('dialog.finance-sheet')) {
  if (typeof dialog.showModal !== 'function') continue;
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
}


for (const account of document.querySelectorAll('[data-currency-account]')) {
  const form=account.closest('form');const amount=form && form.querySelector('[data-currency-amount]');
  const label=form && form.querySelector('[data-currency-label]');const help=form && form.querySelector('[data-currency-help]');
  const sync=()=>{const code=account.selectedOptions[0]?.dataset.currency||'IDR';if(label)label.textContent=code;
    if(help)help.textContent='Boleh desimal pakai titik atau koma. Contoh 1250.50 atau 1250,50; dua angka desimal disimpan.';};
  account.addEventListener('change',sync);sync();
}
for (const currency of document.querySelectorAll('[data-account-currency]')) {
  const form=currency.closest('form');const label=form && form.querySelector('[data-opening-currency]');
  const sync=()=>{if(label)label.textContent=currency.value;};currency.addEventListener('change',sync);sync();
}

for (const form of document.querySelectorAll('form[action*="/finance/exchanges"]')) {
  const from=form.querySelector('[data-fx-from]'),to=form.querySelector('[data-fx-to]');
  const fromAmount=form.querySelector('[data-fx-from-amount]'),toAmount=form.querySelector('[data-fx-to-amount]');
  const reference=form.querySelector('[data-fx-reference]'),actual=form.querySelector('[data-fx-actual]');
  if(!from||!to)continue;
  const refresh=()=>{
    const f=from.selectedOptions[0],t=to.selectedOptions[0],fc=f?.dataset.currency,tc=t?.dataset.currency;
    for(const option of to.options)option.disabled=!!option.value&&(option.value===from.value||option.dataset.currency===fc);
    if(to.selectedOptions[0]?.disabled)to.value='';
    const chosen=to.selectedOptions[0],fr=Number(f?.dataset.idrRate),tr=Number(chosen?.dataset.idrRate);
    reference.textContent=(fc&&chosen?.dataset.currency&&fr>0&&tr>0)?('Kurs referensi: 1 '+fc+' ≈ '+(fr/tr).toLocaleString(undefined,{maximumFractionDigits:6})+' '+chosen.dataset.currency+' · estimasi, bukan kurs jual/beli bank.'):'Kurs referensi akan tampil setelah dua mata uang dipilih.';
    const fa=Number(String(fromAmount.value).replace(',','.')),ta=Number(String(toAmount.value).replace(',','.'));
    actual.textContent=(fc&&chosen?.dataset.currency&&fa>0&&ta>0)?('Kurs aktual penukaran: 1 '+fc+' = '+(ta/fa).toLocaleString(undefined,{maximumFractionDigits:6})+' '+chosen.dataset.currency):'';
  };
  from.addEventListener('change',refresh);to.addEventListener('change',refresh);fromAmount.addEventListener('input',refresh);toAmount.addEventListener('input',refresh);refresh();
}


for (const card of document.querySelectorAll('[data-balance-card]')) {
  const select=card.querySelector('[data-balance-display-currency]');
  const value=card.querySelector('[data-balance-display-value]');
  const label=card.querySelector('[data-balance-display-label]');
  if(!select||!value||!label)continue;
  const totalIdr=Number(card.dataset.totalIdr);
  const symbols={IDR:'Rp',USD:'US$',SGD:'S$',MYR:'RM',EUR:'€',GBP:'£',AUD:'A$',JPY:'¥',CNY:'CN¥',HKD:'HK$',THB:'฿'};
  const format=(amount,code,decimals)=>{
    const number=new Intl.NumberFormat('id-ID',{minimumFractionDigits:decimals,maximumFractionDigits:decimals}).format(amount);
    return (symbols[code]||code+' ')+number;
  };
  const refresh=()=>{
    const option=select.selectedOptions[0],code=option?.value||'IDR';
    const rate=Number(option?.dataset.idrRate||1),decimals=Number(option?.dataset.decimals||0);
    const converted=code==='IDR'?totalIdr:(rate>0?totalIdr/rate:null);
    value.textContent=converted===null?'Kurs tidak tersedia':format(converted,code,decimals);
    label.textContent='Estimasi total dalam '+code;
  };
  select.addEventListener('change',refresh);refresh();
}


// Open the existing manual transaction form after the user chooses a concrete
// branch from the combined view. This does not store or modify Finance AI state.
if (typeof window !== 'undefined' && typeof URLSearchParams !== 'undefined') {
  try {
    const params = new URLSearchParams(window.location.search || '');
    if (params.get('open_manual') === '1') {
      const dialog = document.getElementById && document.getElementById('add-transaction-dialog');
      if (dialog) {
        const forcedDirection = params.get('direction');
        const kind = dialog.querySelector && dialog.querySelector('[name="direction"]');
        if (kind && (forcedDirection === 'INCOME' || forcedDirection === 'EXPENSE')) {
          kind.value = forcedDirection;
          kind.dispatchEvent(new Event('change', {bubbles:true}));
        }
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        const focusable = dialog.querySelector && dialog.querySelector('input:not([type="hidden"]),select,textarea,button');
        if (focusable && typeof focusable.focus === 'function') focusable.focus({preventScroll:true});
      }
      params.delete('open_manual');
      if (window.history && typeof window.history.replaceState === 'function') {
        const next = window.location.pathname + (params.toString() ? '?' + params.toString() : '') + (window.location.hash || '');
        window.history.replaceState(null, '', next);
      }
    }
  } catch (_) {}
}
