const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
class Element {
  constructor(){this.children=[];this.dataset={};this.value='';this.files=[];this.events={};this.classList={toggle(){}};}
  append(...items){this.children.push(...items);}
  replaceChildren(){this.children=[];}
  setAttribute(){}
  addEventListener(name,handler){this.events[name]=handler;}
  dispatchEvent(event){this.events[event.type]?.(event);}
  focus(){}
  scrollIntoView(){}
  get lastElementChild(){return this.children.at(-1);}
}
const draft={kind:'review',context:'signed-active-context',token:'signed-reviewed-token',ready:true,title:'Customer baru',
  fields:[{key:'name',value:'Wilson',required:true},{key:'phone',value:'',required:false}],preview:[['Nama','Wilson']]};
function harness(responses){
  const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const composer=get('assistant-composer');composer.dataset={message:'/message',review:'/review',confirm:'/confirm',recognize:'/recognize',document:'/document',csrf:'csrf'};
  const calls=[];
  const context={document:{getElementById:get,createElement:()=>new Element(),querySelectorAll:()=>[]},
    FormData:class {constructor(){this.data={};} append(key,value){this.data[key]=value;} set(key,value){this.data[key]=value;}},Event:class{constructor(type){this.type=type;}preventDefault(){}},
    fetch:async(url,options)=>{calls.push({url,body:typeof options.body==='string'?JSON.parse(options.body):options.body.data});return {ok:true,json:async()=>responses.shift()};}};
  vm.runInNewContext(fs.readFileSync(__dirname+'/../static/finance_assistant.js','utf8'),context);
  return {get,calls,async send(text){get('assistant-text').value=text;composer.events.submit({preventDefault(){}});await new Promise(resolve=>setImmediate(resolve));}};
}
test('typo follow-up reaches server with signed context instead of browser interpretation',async()=>{
  const h=harness([draft,{...draft,context:'updated'}]);
  await h.send('tambah customer Wilson');await h.send('nomor teleponya 082213039137');
  assert.deepEqual(h.calls[1],{url:'/message',body:{text:'nomor teleponya 082213039137',context:'signed-active-context',confirmation:'signed-reviewed-token'}});
  assert.equal(h.get('assistant-text').value,'');
});
test('typed oke sends only the active signed review and no invented fields',async()=>{
  const h=harness([draft,{kind:'success',message:'Customer disimpan'}]);
  await h.send('tambah customer Wilson');await h.send('oke');
  assert.equal(h.calls[1].body.confirmation,draft.token);assert.equal(h.calls[1].body.context,draft.context);
  assert.equal(h.calls[1].body.text,'oke');assert.equal(h.calls[1].body.values,undefined);
});
test('successful confirmation clears draft before next command',async()=>{
  const h=harness([draft,{kind:'success',message:'Disimpan'},{kind:'answer',message:'Saldo'}]);
  await h.send('tambah customer Wilson');await h.send('oke');await h.send('saldo berapa?');
  assert.deepEqual(h.calls[2].body,{text:'saldo berapa?'});
});
test('successful write carries a signed reference into the next reviewed command',async()=>{
  const h=harness([draft,{kind:'success',message:'Disimpan',query_context:'signed-record-reference'},{kind:'review',fields:[]}]);
  await h.send('buat invoice');await h.send('oke');await h.send('terbitkan yang tadi');
  assert.deepEqual(h.calls[2].body,{text:'terbitkan yang tadi',query_context:'signed-record-reference'});
});
test('ambiguous entity answers preserve the signed read plan',async()=>{
  const h=harness([{kind:'answer',message:'Yang mana?',choices:['Wilson Wijaya','Wilson Kusuma'],query_context:'signed-question'},{kind:'answer',message:'Piutang'}]);
  await h.send('piutang Wilson?');await h.send('Wilson Wijaya');
  assert.deepEqual(h.calls[1].body,{text:'Wilson Wijaya',query_context:'signed-question'});
});
test('server next field prevents an unrelated account picker during cadence question',async()=>{
  const h=harness([{kind:'review',context:'signed',ready:false,next_field:'cadence',fields:[
    {key:'account_id',value:'',type:'select',options:[{label:'BCA',value:'1'}]},
    {key:'cadence',value:'',type:'select',options:[{label:'Bulanan',value:'MONTHLY'}]}]}]);
  await h.send('biaya rutin 2 juta');
  const texts=[];const visit=e=>{if(e.textContent)texts.push(e.textContent);for(const child of e.children||[])visit(child);};
  visit(h.get('assistant-result'));assert.ok(texts.includes('Bulanan'));assert.ok(!texts.includes('BCA'));
});
test('cancel is interpreted server-side and clears active draft',async()=>{
  const h=harness([draft,{kind:'answer',state:'CANCELLED',message:'Batal'},{kind:'answer',message:'Saldo'}]);
  await h.send('tambah customer Wilson');await h.send('ga jadi');await h.send('saldo berapa?');
  assert.equal(h.calls[1].body.context,draft.context);assert.deepEqual(h.calls[2].body,{text:'saldo berapa?'});
});
test('one incomplete draft survives multiple server revisions',async()=>{
  const first={...draft,ready:false,token:undefined};const second={...first,context:'revision-two'};
  const h=harness([first,second,draft]);
  await h.send('pengeluaran 200 ribu');await h.send('pakai BCA');await h.send('kategori transport');
  assert.equal(h.calls[2].body.context,'revision-two');assert.equal(h.calls[2].body.confirmation,null);
});

test('retained bank upload accepts typed account selection and resolves it on server',async()=>{
  const account={kind:'document_account',fields:[{key:'account_id',type:'select',required:true,value:'',options:[{value:'1',label:'BCA · IDR'}]}]};
  const h=harness([{workflow:'BANK_STATEMENT',document_context:'signed-file-currency'},account,{kind:'document_selection',account_id:'1'},{kind:'bank_review',ready:true,token:'bank-token'}]);
  h.get('assistant-files').files=[{name:'bank.pdf',size:10}];
  await h.send('baca mutasi ini');await h.send('pakai BCA');
  assert.equal(h.calls.length,4);assert.equal(h.calls[2].url,'/message');
  assert.equal(h.calls[2].body.document_pending,true);assert.equal(h.calls[3].url,'/document');
  assert.equal(h.calls[3].body.document_context,'signed-file-currency');
  assert.equal(h.calls[3].body.account_id,'1');assert.equal(h.calls[3].body.sources.name,'bank.pdf');
});

test('read-only interruption keeps the original draft and passes query context separately',async()=>{
  const incomplete={...draft,ready:false,token:undefined};
  const answer={kind:'answer',message:'Pengeluaran bulan ini',keep_pending:true,query_context:'signed-report'};
  const h=harness([incomplete,answer,answer,{...draft,context:'amount-updated'}]);
  await h.send('pengeluaran');await h.send('laporan pengeluaran');await h.send('kalau agustus?');await h.send('200 ribu');
  assert.deepEqual(h.calls[3].body,{text:'200 ribu',context:incomplete.context,confirmation:null,query_context:'signed-report'});
  assert.equal(h.calls[2].body.context,incomplete.context);
});
test('interrupted ready draft confirms only its original token and clears both contexts',async()=>{
  const h=harness([draft,{kind:'answer',keep_pending:true,query_context:'query-only'},
    {kind:'success',message:'Saved'},{kind:'answer',message:'Saldo'}]);
  await h.send('tambah customer Wilson');await h.send('saldo gw berapa?');await h.send('oke');await h.send('saldo?');
  assert.equal(h.calls[2].body.confirmation,draft.token);
  assert.equal(h.calls[2].body.context,draft.context);
  assert.deepEqual(h.calls[3].body,{text:'saldo?'});
});
test('new reviewed command replaces the uncommitted draft without a cancel ritual',async()=>{
  const replacement={kind:'review',context:'new-draft',ready:false,fields:[{key:'amount',value:'3 juta',required:true}]};
  const h=harness([draft,replacement,{...replacement,context:'new-draft-2'}]);
  await h.send('tambah customer Wilson');await h.send('catat pemasukan 3 juta');await h.send('ubah jadi 4 juta');
  assert.equal(h.calls[1].body.context,draft.context);
  assert.equal(h.calls[2].body.context,'new-draft');
});
