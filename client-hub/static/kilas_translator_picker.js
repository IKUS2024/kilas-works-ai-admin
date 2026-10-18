/* Native select remains the sole submitted value and no-JS fallback. */
(() => {
  const t=message=>window.KilasUI?.t(message)||message;
  const locale=document.documentElement.lang||'en';
  const fold=value=>String(value).normalize('NFD').replace(/\p{M}/gu,'').toLocaleLowerCase(locale).trim();
  let serial=0;
  for(const select of document.querySelectorAll('select[data-translator-language]')) {
    const wrapper=document.createElement('span');wrapper.className='translator-picker';
    select.before(wrapper);wrapper.append(select);select.tabIndex=-1;
    const label=[...(select.closest('label')?.childNodes||[])].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join(' ').trim();
    const button=document.createElement('button');button.type='button';button.setAttribute('aria-label',label);button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
    const popup=document.createElement('span');popup.className='translator-picker-popup';popup.hidden=true;
    const search=document.createElement('input');search.type='search';search.autocomplete='off';search.placeholder=t('Cari bahasa');search.setAttribute('aria-label',t('Cari bahasa'));search.setAttribute('role','combobox');search.setAttribute('aria-expanded','true');search.setAttribute('aria-autocomplete','list');
    const list=document.createElement('span');list.className='translator-picker-list';list.id='translator-language-list-'+(++serial);list.setAttribute('role','listbox');list.setAttribute('aria-label',label);search.setAttribute('aria-controls',list.id);button.setAttribute('aria-controls',list.id);
    popup.append(search,list);wrapper.append(button,popup);
    const rows=[...select.options].map(option=>{
      const english=option.dataset.searchName||option.textContent;const name=option.textContent;let autonym=english;
      if(option.value&&option.value!=='auto') {
        try{autonym=new Intl.DisplayNames([option.value],{type:'language',fallback:'none'}).of(option.value)||english;}catch{}
      }
      return {option,name,key:fold([name,english,autonym,option.value,...(option.value==='id'?['in','ind']:option.value==='zh'?['cmn','zho','zh-Hans','zh-Hant']:[])].join(' '))};
    });
    let visible=[],active=-1;
    function close(focus=false){popup.hidden=true;button.setAttribute('aria-expanded','false');search.removeAttribute('aria-activedescendant');if(focus)button.focus();}
    function highlight(index){active=index;visible.forEach((item,i)=>item.button.dataset.active=String(i===index));const row=visible[index];if(row){search.setAttribute('aria-activedescendant',row.button.id);row.button.scrollIntoView({block:'nearest'});}}
    function choose(row){if(row.option.disabled)return;select.value=row.option.value;select.dispatchEvent(new Event('change',{bubbles:true}));sync();close(true);}
    function render(){
      list.replaceChildren();visible=[];const query=fold(search.value);
      for(const row of rows.filter(row=>row.option.value && !row.option.hidden && (!query||row.key.includes(query)))) {
        const option=document.createElement('button');option.type='button';option.tabIndex=-1;option.setAttribute('role','option');option.id=list.id+'-'+row.option.index;option.textContent=row.name;option.disabled=row.option.disabled;option.setAttribute('aria-selected',String(row.option.value===select.value));option.addEventListener('click',()=>choose(row));list.append(option);
        if(!option.disabled)visible.push({...row,button:option});
      }
      if(!list.children.length){const empty=document.createElement('span');empty.className='translator-picker-empty';empty.textContent=t('Bahasa tidak ditemukan.');empty.setAttribute('role','status');list.append(empty);}
      highlight(visible.findIndex(row=>row.option.value===select.value));
    }
    function sync(){button.textContent=rows.find(row=>row.option.value===select.value)?.name||t('Belum tersedia');button.disabled=select.disabled||!select.options.length;if(button.disabled)close();else if(!popup.hidden)render();}
    function open(){if(button.disabled)return;search.value='';popup.hidden=false;button.setAttribute('aria-expanded','true');popup.style.top='calc(100% + 5px)';popup.style.bottom='auto';render();const rect=popup.getBoundingClientRect();if(rect.bottom>innerHeight-8&&wrapper.getBoundingClientRect().top>rect.height+8){popup.style.top='auto';popup.style.bottom='calc(100% + 5px)';}search.focus();}
    button.addEventListener('click',()=>popup.hidden?open():close());button.addEventListener('keydown',event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open();highlight(event.key==='ArrowDown'?0:visible.length-1);}});
    search.addEventListener('input',render);search.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();close(true);}else if(event.key==='Tab')close();else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();highlight(event.key==='Home'?0:event.key==='End'?visible.length-1:Math.max(0,Math.min(visible.length-1,active+(event.key==='ArrowDown'?1:-1))));}else if(event.key==='Enter'){event.preventDefault();if(visible[active])choose(visible[active]);else if(visible.length===1)choose(visible[0]);}});
    select.addEventListener('change',sync);select.form?.addEventListener('reset',()=>queueMicrotask(sync));new MutationObserver(sync).observe(select,{attributes:true,subtree:true,attributeFilter:['disabled','selected','hidden']});document.addEventListener('pointerdown',event=>{if(!wrapper.contains(event.target))close();});sync();
  }
})();
