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
      const available = [...category.options].find(option => !option.disabled);
      if (available) category.value = available.value;
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

  const refresh=()=>{
    const parentId=String(category.value||'');
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
    if(selected && selected.value && selected.disabled)subcategory.value='';
    field.hidden=count===0;
    if(field.style)field.style.display=count===0?'none':'';
    subcategory.disabled=count===0;
    subcategory.required=count>0;
    if(count===0)subcategory.value='';
  };
  category.addEventListener('change',refresh);
  if(direction)direction.addEventListener('change',refresh);
  refresh();
}



// Manage transaction categories without leaving the transaction sheet.
// The same Finance category records feed transactions, budgets, recurring costs,
// reports, and AI Finance, so add/delete here stays consistent everywhere.
for (const quick of document.querySelectorAll('[data-category-quick-add]')) {
  const form=quick.closest('form');
  const category=quick.querySelector('[data-other-category]');
  const direction=form && form.querySelector('[name="direction"]');
  const toggle=quick.querySelector('[data-category-add-toggle]');
  const panel=quick.querySelector('[data-category-add-panel]');
  const input=quick.querySelector('[data-category-name]');
  const save=quick.querySelector('[data-category-save]');
  const cancel=quick.querySelector('[data-category-cancel]');
  const status=quick.querySelector('[data-category-status]');
  const kindLabel=quick.querySelector('[data-category-kind]');
  const list=quick.querySelector('[data-category-list]');
  if(!form||!category||!direction||!toggle||!panel||!input||!save||!cancel||!status||!list)continue;

  const labelForDirection=()=>direction.value==='INCOME'?'Pemasukan':'Pengeluaran';
  const setStatus=(message,type='')=>{
    status.textContent=message||'';
    status.classList.remove('error','success');
    if(type)status.classList.add(type);
  };
  const isOtherName=name=>['Lainnya','Pendapatan Lain','Pengeluaran Lain'].includes(name);

  const renderList=()=>{
    list.replaceChildren();
    const visible=[...category.options].filter(option=>option.dataset.direction===direction.value);
    for(const option of visible){
      const row=document.createElement('div');
      row.className='finance-category-quick-row';
      row.dataset.categoryRow='';
      row.dataset.categoryId=option.value;
      const label=document.createElement('span');
      label.textContent=option.textContent;
      const remove=document.createElement('button');
      remove.type='button';
      remove.className='finance-category-quick-delete';
      remove.dataset.categoryDelete='';
      remove.textContent='Hapus';
      row.append(label,remove);
      list.appendChild(row);
    }
  };

  const applyOptions=(rows,preferredId='')=>{
    const currentDirection=direction.value;
    const preserved=[...category.options].filter(option=>option.dataset.direction!==currentDirection);
    category.replaceChildren(...preserved);
    for(const item of Array.isArray(rows)?rows:[]){
      const option=document.createElement('option');
      option.value=String(item.id);
      option.textContent=item.name;
      option.dataset.direction=item.direction;
      option.dataset.other=isOtherName(item.name)?'true':'false';
      category.appendChild(option);
    }
    const preferred=[...category.options].find(option=>option.value===String(preferredId) && option.dataset.direction===currentDirection);
    const available=preferred||[...category.options].find(option=>option.dataset.direction===currentDirection);
    if(available)category.value=available.value;
    category.dispatchEvent(new Event('change',{bubbles:true}));
    renderList();
  };

  const request=async(payload)=>{
    const endpoint=quick.dataset.categoryCreateUrl;
    if(!endpoint)throw new Error('Kategori belum bisa diubah dari halaman ini.');
    const body=new FormData();
    const csrf=form.querySelector('input[name="csrf_token"]');
    if(csrf)body.set('csrf_token',csrf.value);
    const branchId=quick.dataset.categoryBranch;
    if(branchId && branchId!=='None')body.set('branch_id',branchId);
    body.set('direction',direction.value);
    Object.entries(payload).forEach(([key,value])=>body.set(key,String(value)));
    const response=await fetch(endpoint,{
      method:'POST',
      body,
      credentials:'same-origin',
      headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}
    });
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||'Kategori belum bisa diubah.');
    return data;
  };

  const syncKind=()=>{
    if(kindLabel)kindLabel.textContent=labelForDirection();
    input.placeholder=direction.value==='INCOME'?'Contoh: Pendapatan Konten':'Contoh: Perawatan';
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
    closePanel();
    category.focus({preventScroll:true});
  });
  direction.addEventListener('change',syncKind);
  input.addEventListener('keydown',event=>{
    if(event.key==='Enter'){
      event.preventDefault();
      save.click();
    }
  });
  save.addEventListener('click',async()=>{
    const name=String(input.value||'').trim();
    if(!name){
      setStatus('Nama kategori wajib diisi.','error');
      input.focus({preventScroll:true});
      return;
    }
    save.disabled=true;
    cancel.disabled=true;
    setStatus('Menambahkan kategori…');
    try{
      const data=await request({action:'create',name});
      if(!data.category)throw new Error('Kategori belum bisa dimuat.');
      applyOptions(data.options,data.category.id);
      input.value='';
      setStatus(data.message||'Kategori ditambahkan dan langsung dipilih.','success');
    }catch(error){
      setStatus(error && error.message?error.message:'Kategori belum bisa ditambahkan. Coba lagi.','error');
    }finally{
      save.disabled=false;
      cancel.disabled=false;
    }
  });
  list.addEventListener('click',async event=>{
    const button=event.target.closest('[data-category-delete]');
    if(!button)return;
    const row=button.closest('[data-category-row]');
    const categoryId=row && row.dataset.categoryId;
    const name=row && row.querySelector('span')?.textContent;
    if(!categoryId)return;
    if(!window.confirm('Hapus kategori "'+(name||'ini')+'" dari daftar aktif? Riwayat lama tetap aman.'))return;
    button.disabled=true;
    setStatus('Menghapus kategori…');
    const keep=category.value===String(categoryId)?'':category.value;
    try{
      const data=await request({action:'delete',category_id:categoryId});
      applyOptions(data.options,keep);
      const globalRow=document.querySelector('[data-finance-category-record="'+categoryId+'"]');
      if(globalRow)globalRow.remove();
      setStatus(data.message||'Kategori dihapus dari daftar aktif.','success');
    }catch(error){
      button.disabled=false;
      setStatus(error && error.message?error.message:'Kategori belum bisa dihapus.','error');
    }
  });
  syncKind();
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
