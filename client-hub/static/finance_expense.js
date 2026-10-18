(() => {
  'use strict';
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
      function update(){let count=0;for(const option of child.options){if(!option.value)continue;option.hidden=option.disabled=option.dataset.parent!==parent.value;if(!option.disabled)count++;}label.hidden=!count;child.disabled=!count;child.required=!!count;const empty=box.querySelector('[data-expense-empty-child]');if(empty)empty.disabled=!!count;if(child.selectedOptions[0]?.disabled)child.value='';}
      if(initial){const leaf=[...child.options].find(o=>o.value===String(initial));parent.value=leaf?leaf.dataset.parent:String(initial);if(leaf)child.value=String(initial);}
      parent.addEventListener('change',()=>{child.value='';update();});box.refreshExpensePicker=update;update();
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
    form.addEventListener('submit',event=>{if(form.dataset.pending==='true'){event.preventDefault();return;}form.dataset.pending='true';form.setAttribute('aria-busy','true');});
    window.addEventListener('pageshow',()=>{delete form.dataset.pending;form.removeAttribute('aria-busy');});
  }
})();
