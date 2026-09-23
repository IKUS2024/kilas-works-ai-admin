(()=>{
'use strict';
const form=document.getElementById('invoice-editor-form');if(!form)return;
const customer=document.getElementById('customer'),items=document.getElementById('invoice-items'),currency=document.getElementById('currency');
const prefill=()=>{const o=customer.selectedOptions[0];for(const k of ['name','phone','email','address','pic','tax_id'])form.elements['recipient_'+k].value=o?.dataset[k]||'';};
customer.addEventListener('change',prefill);
document.getElementById('new-recipient')?.addEventListener('click',()=>{customer.selectedIndex=0;prefill();form.elements.recipient_name.focus();});
const money=(v)=>`${currency.value} ${v/100n}.${String(v%100n).padStart(2,'0')}`;
const price=(v)=>{if(!/^\d+(?:[.,]\d{1,2})?$/.test(v.trim()))throw Error();const [a,b='']=v.trim().replace(',','.').split('.');return BigInt(a)*100n+BigInt(b.padEnd(2,'0'));};
const recalc=()=>{let total=0n,valid=true;for(const row of items.children){try{const q=row.querySelector('[name=quantity]').value;if(!/^\d+$/.test(q)||BigInt(q)<1n)throw Error();const line=BigInt(q)*price(row.querySelector('[name=unit_price]').value);total+=line;row.querySelector('.line-total').textContent=money(line);}catch{valid=false;row.querySelector('.line-total').textContent='—';}}document.getElementById('invoice-total').textContent=valid?money(total):'Periksa jumlah dan harga';};
form.addEventListener('input',recalc);currency.addEventListener('change',recalc);
document.getElementById('add-item')?.addEventListener('click',()=>{if(items.children.length>=100)return;const row=items.firstElementChild.cloneNode(true);row.querySelectorAll('input').forEach(n=>n.value=n.name==='quantity'?'1':n.name==='unit_price'?'0.00':'');items.append(row);recalc();});
items.addEventListener('click',e=>{if(e.target.classList.contains('remove-item')&&items.children.length>1){e.target.closest('.invoice-item').remove();recalc();}});
recalc();
})();
