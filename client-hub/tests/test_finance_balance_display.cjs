const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../static/finance_balance_display.js'),'utf8');

function setup(){
  const select={value:'IDR',addEventListener(_,fn){this.change=fn;}};
  const value={textContent:''},label={textContent:''},warning={hidden:true},rates={textContent:''};
  const data={IDR:{value:'Rp2.785.714',complete:true,estimated:true,label:'Estimasi gabungan dalam IDR',rates:'1 USD ≈ 17.857,14 IDR'},
              USD:{value:'US$156.00',complete:true,estimated:true,label:'Estimasi gabungan dalam USD',rates:'1 IDR ≈ 0.000056 USD'},
              SGD:{value:'Kurs belum lengkap',complete:false,estimated:true,label:'Estimasi gabungan dalam SGD',rates:''}};
  const source={textContent:JSON.stringify(data)};
  const nodes={'[data-cash-display-currency]':select,'[data-cash-display-value]':value,
    '[data-cash-display-label]':label,'[data-cash-display-warning]':warning,
    '[data-cash-display-rates]':rates,'[data-cash-display-data]':source};
  const card={querySelector:s=>nodes[s]};
  const field={value:'IDR'};
  const document={querySelectorAll:s=>s==='[data-cash-position-card]'?[card]:s==='[name="display_currency"]'?[field]:[]};
  const window={location:{href:'https://example.test/finance?period_mode=all'},history:{replaceState(a,b,url){this.url=url.href;}}};
  vm.runInNewContext(script,{document,window,URL});
  return {select,value,label,warning,rates,field,window};
}

test('selector switches precomputed money without doing browser arithmetic',()=>{
  const e=setup();e.select.value='USD';e.select.change();
  assert.equal(e.value.textContent,'≈ US$156.00');
  assert.equal(e.field.value,'USD');
  assert.equal(e.warning.hidden,true);
  assert.doesNotMatch(script,/Number\(|parseFloat\(|totalIdr\//);
});

test('missing FX shows incomplete warning instead of partial total',()=>{
  const e=setup();e.select.value='SGD';e.select.change();
  assert.equal(e.value.textContent,'Kurs belum lengkap');
  assert.equal(e.warning.hidden,false);
});
