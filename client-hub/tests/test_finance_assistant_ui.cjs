// Actual Assistant JS in an offline DOM harness; no browser or provider connection.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname,'../static/finance_assistant.js'),'utf8');

function setup() {
  class Element {
    constructor(id) { this.id=id; this.value=''; this.files=[]; this.children=[]; this.listeners={}; this.dataset={}; this.hidden=true; this.disabled=false; this.textContent=''; this.attrs={}; }
    addEventListener(type,fn) { (this.listeners[type] ||= []).push(fn); }
    async fire(type) { for (const fn of this.listeners[type] || []) await fn({preventDefault(){},type}); }
    dispatchEvent(event) { return this.fire(event.type); }
    append(...nodes) { for (const node of nodes) { node.parent=this; this.children.push(node); } }
    replaceChildren(...nodes) { this.children=[]; this.append(...nodes); }
    setAttribute(name,value) { this.attrs[name]=value; }
    focus() { this.focused=true; }
    remove() { if(this.parent) this.parent.children=this.parent.children.filter(n=>n!==this); }
    querySelector(selector = '[name="account_id"]') { const name=selector.match(/name="([^"]+)"/)[1]; return this.children.find(n=>n.name===name) || null; }
  }
  const ids=['assistant-camera','finance-assistant','assistant-composer','assistant-files','assistant-mode','assistant-text','assistant-status',
    'assistant-send','assistant-clear','assistant-receipt-continue','assistant-bank-continue','assistant-message','assistant-message-text',
    'assistant-file-list','assistant-clarification','assistant-clarification-title','assistant-receipt','assistant-bank',
    'assistant-analysis','assistant-operator','assistant-cancel','assistant-bank-account','operator-fields','op-preview',
    'assistant-recurring','assistant-bank-title','recurring-fields','rec-preview','rec-name','rec-amount','rec-cadence','rec-start','rec-end','rec-account','rec-category','rec-details','recurring-form','rec-status','rec-confirm','rec-cancel','op-action','op-request','op-account','op-details','op-interpretation','question','scope','answer'];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
  const choices=['receipt','bank','ask','record','notes','recurring'].map(value=>{const node=new Element(value);node.dataset.assistantChoice=value;return node;});
  const calls=[],uploads=[];
  let resolveResponse=async()=>({ok:true,json:async()=>({workflow:'NEEDS_CLARIFICATION',suggested_action:''})});
  const composer=elements['assistant-composer'];
  composer.dataset={route:'/business/1/finance/assistant/route',receipt:'/business/1/finance/receipts/analyze',bank:'/business/1/finance/bank-imports/analyze',csrf:'test-csrf'};
  elements['assistant-mode'].value='auto';
  const sandbox={FormData:class {constructor(){this.entries=[];}append(...value){this.entries.push(value);}},document:{getElementById:id=>elements[id] || null,querySelectorAll:()=>choices,createElement:tag=>new Element(tag)},
    window:{addEventListener(){},location:{reload(){}}},Event:class {constructor(type){this.type=type;}},
    HTMLFormElement:{prototype:{submit(){uploads.push({action:this.action,name:elements['assistant-files'].name,
        fileDisabled:elements['assistant-files'].disabled,account:this.querySelector()?.value,kind:this.querySelector('[name="document_kind"]')?.value});}}},
    fetch:async(url,opts)=>{calls.push({url,opts,body:typeof opts.body==='string'?JSON.parse(opts.body):opts.body});return resolveResponse();}};
  vm.runInNewContext(script,sandbox);
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  return {elements,choices,calls,uploads,tick,runRecurring(){vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/finance_assistant_recurring.js'),'utf8'),sandbox);},
    result(workflow,action='',suggestions={}){resolveResponse=async()=>({ok:true,json:async()=>({workflow,suggested_action:action,suggestions})});},
    respond(fn){resolveResponse=fn;},
    async route(){await composer.fire('submit');await tick();}};
}

test('composer routes only bounded metadata; filename displayed as text',async()=>{
  const h=setup(), e=h.elements;
  e['assistant-text'].value='tolong cek ini';e['assistant-files'].files=[{name:'<img onerror=evil>.pdf',bytes:'PRIVATE_BYTES'}];
  await e['assistant-files'].fire('change');await h.route();
  assert.equal(h.calls.length,1);assert.equal(h.calls[0].body.files[0].name,'<img onerror=evil>.pdf');
  assert.equal('bytes' in h.calls[0].body.files[0],false);
  assert.equal(e['assistant-file-list'].children[0].textContent,'<img onerror=evil>.pdf');assert.equal(h.uploads.length,0);
});

test('ambiguous files ask receipt/bank before upload',async()=>{
  const h=setup();h.elements['assistant-files'].files=[{name:'a.pdf'}];await h.route();
  assert.equal(h.elements['assistant-clarification'].hidden,false);
  assert.equal(h.choices.find(n=>n.dataset.assistantChoice==='ask').hidden,true);
  assert.equal(h.uploads.length,0);
});

test('clarification receipt choice preserves files and uses existing review endpoint once',async()=>{
  const h=setup(),e=h.elements;e['assistant-files'].files=[{name:'a.png'}];await h.route();h.result('RECEIPT');
  await h.choices[0].fire('click');await h.tick();
  assert.equal(h.calls[1].body.mode,'receipt');assert.equal(e['assistant-receipt'].hidden,false);
  await e['assistant-receipt-continue'].fire('click');await e['assistant-receipt-continue'].fire('click');
  assert.equal(h.uploads.length,1);assert.equal(h.uploads[0].action,'/business/1/finance/receipts/analyze');
  assert.equal(h.uploads[0].name,'receipt');assert.equal(h.uploads[0].fileDisabled,false);
});

test('bank proposal requires selected account before native staging upload',async()=>{
  const h=setup(),e=h.elements;h.result('BANK_STATEMENT');e['assistant-files'].files=[{name:'a.csv'}];await h.route();
  await e['assistant-bank-continue'].fire('click');assert.equal(h.uploads.length,0);
  e['assistant-bank-account'].value='12';await e['assistant-bank-continue'].fire('click');
  assert.equal(h.uploads[0].account,'12');assert.equal(h.uploads[0].name,'sources');
  assert.equal(h.uploads[0].action,'/business/1/finance/bank-imports/analyze');
});

test('double route submit has only one pending request',async()=>{
  const h=setup();let resolve;h.respond(()=>new Promise(r=>{resolve=r;}));
  await h.elements['assistant-composer'].fire('submit');await h.elements['assistant-composer'].fire('submit');
  assert.equal(h.calls.length,1);assert.equal(h.elements['assistant-send'].disabled,true);
  resolve({ok:true,json:async()=>({workflow:'NEEDS_CLARIFICATION'})});await h.tick();
  assert.equal(h.elements['assistant-send'].disabled,false);
});

test('operator proposal fills text/action but requires manual account and draft submit',async()=>{
  const h=setup(),e=h.elements;h.result('TEXT_OPERATOR','create_expense');e['assistant-text'].value='catat bensin 300 ribu';
  e['op-account'].value='99';await h.route();
  assert.equal(e['op-action'].value,'create_expense');assert.equal(e['op-request'].value,'catat bensin 300 ribu');
  assert.equal(e['op-account'].value,'');assert.equal(h.calls.length,1);assert.equal(h.uploads.length,0);
});

test('pending operator draft blocks new routing',async()=>{
  const h=setup();h.elements['op-preview'].hidden=false;await h.route();assert.equal(h.calls.length,0);
  assert.match(h.elements['assistant-status'].textContent,/Selesaikan atau batalkan/);
});

test('analyst handoff clears old answer and proposes categories without executing',async()=>{
  const h=setup(),e=h.elements;h.result('READ_ONLY_ANALYSIS');e['assistant-text'].value='pengeluaran terbesar apa?';
  e['answer'].append({textContent:'OLD'});e['answer'].hidden=false;await h.route();
  assert.equal(e['scope'].value,'categories');assert.equal(e['question'].value,e['assistant-text'].value);
  assert.equal(e['answer'].hidden,true);assert.equal(e['answer'].children.length,0);assert.equal(h.calls.length,1);
});

test('network routing failure gives clarification and does not upload',async()=>{
  const h=setup();h.respond(async()=>{throw new Error('PRIVATE ERROR');});await h.route();
  assert.equal(h.elements['assistant-clarification'].hidden,false);assert.equal(h.uploads.length,0);
  assert.equal(h.elements['assistant-status'].textContent.includes('PRIVATE ERROR'),false);
});

test('clearing transient input removes prompt, file and previous result values',async()=>{
  const h=setup(),e=h.elements;e['assistant-text'].value='PRIVATE';e['question'].value='PRIVATE';e['op-request'].value='PRIVATE';
  e['answer'].append({textContent:'PRIVATE'});await e['assistant-clear'].fire('click');
  for (const id of ['assistant-text','question','op-request']) assert.equal(e[id].value,'');
  assert.equal(e['answer'].children.length,0);assert.equal(h.calls.length,0);
});

test('editing message invalidates an earlier file proposal',async()=>{
  const h=setup(),e=h.elements;h.result('RECEIPT');e['assistant-files'].files=[{name:'a.png'}];await h.route();
  await e['assistant-text'].fire('input');await e['assistant-receipt-continue'].fire('click');assert.equal(h.uploads.length,0);
});

test('text and attachment counts are bounded before route request',async()=>{
  const h=setup();h.elements['assistant-text'].value='x'.repeat(2001);await h.route();assert.equal(h.calls.length,0);
  h.elements['assistant-text'].value='';h.elements['assistant-files'].files=Array.from({length:11},()=>({name:'a.png'}));
  await h.route();assert.equal(h.calls.length,0);
});

test('camera preserves auto mode and performs no extraction before submit',async()=>{
  const h=setup(),e=h.elements;
  e['assistant-camera'].files=[{name:'camera.jpg'}];
  await e['assistant-camera'].fire('change');
  assert.equal(e['assistant-mode'].value,'auto');
  assert.equal(e['assistant-files'].files[0].name,'camera.jpg');
  assert.equal(h.calls.length,0);assert.equal(h.uploads.length,0);
  assert.match(e['assistant-status'].textContent,/Belum ada pencatatan/);
});
test('pending review cannot be replaced by a camera selection',async()=>{
  const h=setup(),e=h.elements;e['op-preview'].hidden=false;
  e['assistant-files'].files=[{name:'original.pdf'}];
  e['assistant-camera'].files=[{name:'new.jpg'}];await e['assistant-camera'].fire('change');
  assert.equal(e['assistant-files'].files[0].name,'original.pdf');assert.equal(h.calls.length,0);
});

test('camera selection exposes Baca Struk; one explicit click uploads once with loading',async()=>{
  const h=setup(),e=h.elements;e['assistant-mode'].value='receipt';e['assistant-camera'].files=[{name:'camera.jpg'}];
  await e['assistant-camera'].fire('change');
  assert.equal(e['assistant-send'].textContent,'Baca Struk');
  assert.equal(e['assistant-send'].focused,true);
  assert.equal(h.uploads.length,0);assert.equal(h.calls.length,0);
  await h.route();await h.route();
  assert.equal(h.uploads.length,1);assert.equal(h.calls.length,0);
  assert.equal(h.uploads[0].action,'/business/1/finance/receipts/analyze');
  assert.equal(e['assistant-send'].disabled,true);
  assert.match(e['assistant-status'].textContent,/Membaca struk.*Review Hasil/);
});

test('explicit receipt file selection and mode changes update primary action without sending',async()=>{
  const h=setup(),e=h.elements;e['assistant-mode'].value='receipt';
  e['assistant-files'].files=[{name:'receipt.pdf'}];await e['assistant-files'].fire('change');
  assert.equal(e['assistant-send'].textContent,'Baca Struk');assert.equal(h.uploads.length,0);
  e['assistant-mode'].value='bank';await e['assistant-mode'].fire('input');
  assert.equal(e['assistant-send'].textContent,'Lanjut');assert.equal(h.uploads.length,0);
  e['assistant-mode'].value='receipt';await e['assistant-mode'].fire('input');
  await h.route();assert.equal(h.uploads.length,1);assert.equal(h.uploads[0].name,'receipt');
});

test('ambiguous gallery image still needs workflow choice and never auto uploads',async()=>{
  const h=setup(),e=h.elements;e['assistant-files'].files=[{name:'unknown.jpg'}];
  await e['assistant-files'].fire('change');assert.equal(e['assistant-send'].textContent,'Lanjut');
  assert.equal(h.calls.length,0);assert.equal(h.uploads.length,0);
  await h.route();assert.equal(e['assistant-clarification'].hidden,false);assert.equal(h.uploads.length,0);
});

test('analyst browser shows safe errors, never provider body or exception text',async()=>{
  for (const kind of ['http','network','json']) {
    const h=setup(),e=h.elements, Element=e['assistant-text'].constructor;
    for (const id of ['analyst-form','send','status','month']) e[id]=new Element(id);
    e.month.value='2026-09';e.question.value='Ringkas laporan';e.scope.value='summary';
    const analystScript=fs.readFileSync(path.join(__dirname,'../static/finance_analyst.js'),'utf8');
    vm.runInNewContext(analystScript,{
      document:{getElementById:id=>e[id],createElement:tag=>new Element(tag)},location:{pathname:'/analyst'},
      fetch:async()=>{
        if(kind==='network') throw new Error('PRIVATE_EXCEPTION');
        return {ok:false,json:async()=>{if(kind==='json')throw new Error('PRIVATE_JSON');return {error:'PRIVATE_PROVIDER_BODY'};}};
      }
    });
    await e['analyst-form'].fire('submit');
    assert.match(e.status.textContent,/Laporan & Export/);
    assert.equal(e.status.textContent.includes('PRIVATE'),false);assert.equal(e.send.disabled,false);
  }
});

test('auto recognition sends bounded multipart then proposes notes without writing',async()=>{
  const h=setup(),e=h.elements;e['assistant-composer'].dataset.recognize='/recognize';
  e['assistant-files'].files=[{name:'notes.png'}];
  h.respond(async()=>({ok:true,json:async()=>({workflow:h.calls.length===1?'NEEDS_CLARIFICATION':'HANDWRITTEN_NOTE'})}));
  await h.route();assert.equal(h.calls.length,2);assert.equal(h.calls[1].url,'/recognize');
  assert.equal(h.calls[1].body.entries.find(([name])=>name==='csrf_token')[1],'test-csrf');
  assert.equal(e['assistant-bank-title'].textContent,'Review catatan keuangan');assert.equal(h.uploads.length,0);
  e['assistant-bank-account'].value='12';await e['assistant-bank-continue'].fire('click');
  assert.equal(h.uploads.length,1);assert.equal(h.uploads[0].kind,'notes');assert.equal(h.uploads[0].name,'sources');
});

test('recognition failure preserves file for manual choice',async()=>{
  const h=setup(),e=h.elements;e['assistant-composer'].dataset.recognize='/recognize';e['assistant-files'].files=[{name:'notes.png'}];
  h.respond(async()=>({ok:h.calls.length===1,json:async()=>({workflow:'NEEDS_CLARIFICATION'})}));
  await h.route();assert.equal(e['assistant-clarification'].hidden,false);assert.equal(e['assistant-files'].files.length,1);
  assert.equal(h.uploads.length,0);assert.equal(e['assistant-send'].disabled,false);
});

test('recurring routing fills suggestions but leaves references and dates for review',async()=>{
  const h=setup(),e=h.elements;e['assistant-text'].value='sewa 2 juta tiap bulan';
  h.result('RECURRING_DRAFT','',{name:'sewa',amount_text:'2 juta',cadence:'MONTHLY'});
  await h.route();assert.equal(e['assistant-recurring'].hidden,false);assert.equal(e['rec-amount'].value,'2 juta');
  assert.equal(e['rec-start'].value,'');assert.equal(e['rec-account'].value,'');assert.equal(h.calls.length,1);
});

test('recurring draft blocks new routing and waits for explicit confirmation',async()=>{
  const h=setup(),e=h.elements;h.runRecurring();
  h.respond(async()=>({ok:true,json:async()=>({token:'signed-draft',preview:[['Nominal','Rp2.000.000']]})}));
  await e['recurring-form'].fire('submit');assert.equal(h.calls.length,1);assert.equal(e['rec-preview'].hidden,false);
  assert.equal(e['recurring-fields'].disabled,true);await h.route();assert.equal(h.calls.length,1);
  h.respond(async()=>({ok:true,json:async()=>({message:'Jadwal tersimpan'})}));
  await e['rec-confirm'].fire('click');await e['rec-confirm'].fire('click');
  assert.equal(h.calls.length,2);assert.equal(h.calls[1].body.token,'signed-draft');assert.equal(h.calls[1].body.confirm,true);
  assert.equal(e['rec-preview'].hidden,true);
});

test('uncertain recurring confirmation retains the same token for safe retry',async()=>{
  const h=setup(),e=h.elements;h.runRecurring();
  h.respond(async()=>({ok:true,json:async()=>({token:'same-token',preview:[]})}));await e['recurring-form'].fire('submit');
  h.respond(async()=>{throw new Error('PRIVATE');});await e['rec-confirm'].fire('click');
  assert.equal(e['rec-preview'].hidden,false);assert.equal(e['recurring-fields'].disabled,true);
  await e['rec-confirm'].fire('click');assert.equal(h.calls[1].body.token,h.calls[2].body.token);
  assert.equal(e['rec-status'].textContent.includes('PRIVATE'),false);
});
