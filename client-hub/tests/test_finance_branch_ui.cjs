// Focused regression: visible category matches direction; Lainnya retains entered notes.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
test('direction changes and Lainnya visibility preserve notes',()=>{
  const input={value:'Servis mesin kopi',required:false,disabled:false};
  const other={hidden:true,querySelector:()=>input};
  const kind={value:'INCOME',addEventListener(_,callback){this.change=callback;}};
  const options=[['1','INCOME','false'],['2','INCOME','true'],['3','EXPENSE','false'],['4','EXPENSE','true']].map(([value,direction,other])=>({value,dataset:{direction,other},disabled:false,hidden:false}));
  const category={value:'1',options,get selectedOptions(){return options.filter(o=>o.value===this.value);},addEventListener(_,callback){this.change=callback;},closest(){return form;}};
  const form={querySelector:selector=>selector==='[name="direction"]'?kind:other};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/finance_branches.js'),'utf8'),{document:{querySelectorAll:()=>[category]}});
  assert.equal(options[2].disabled,true);
  assert.equal(input.disabled,true);
  category.value='2';category.change();
  assert.equal(other.hidden,false);assert.equal(input.required,true);assert.equal(input.disabled,false);
  kind.value='EXPENSE';kind.change();
  assert.equal(category.value,'3');assert.equal(options[0].disabled,true);assert.equal(other.hidden,true);
  category.value='4';category.change();
  assert.equal(input.value,'Servis mesin kopi');assert.equal(input.required,true);
});


test('compact finance actions open and close bottom-sheet dialogs',()=>{
  const dialog={open:false,showModal(){this.open=true;},close(){this.open=false;},addEventListener(_,callback){this.backdrop=callback;},querySelector(){return null;}};
  const opener={dataset:{financeOpen:'branch-dialog'},addEventListener(_,callback){this.click=callback;}};
  const closer={dataset:{financeClose:'branch-dialog'},addEventListener(_,callback){this.click=callback;}};
  const document={
    querySelectorAll(selector){
      if(selector==='[data-other-category]')return [];
      if(selector==='[data-finance-open]')return [opener];
      if(selector==='[data-finance-close]')return [closer];
      if(selector==='dialog.finance-sheet')return [dialog];
      return [];
    },
    getElementById(id){return id==='branch-dialog'?dialog:null;}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/finance_branches.js'),'utf8'),{document});
  opener.click(); assert.equal(dialog.open,true);
  closer.click(); assert.equal(dialog.open,false);
});

test('dashboard uses compact management tiles and explicit transaction delete',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  assert.match(html,/data-finance-open="branch-dialog"/);
  assert.match(html,/data-finance-open="account-dialog"/);
  assert.match(html,/data-finance-open="category-dialog"/);
  assert.match(html,/data-finance-open="reset-dialog"/);
  assert.match(html,/name="confirmation"[^>]*pattern="RESET"/);
  assert.match(html,/Reset Cabang ke Rp0/);
  assert.match(html,/Hapus transaksi ini/);
  assert.doesNotMatch(html,/Pengaturan cabang, akun &amp; kategori/);
});


test('receivables operations and reports expose compact section hubs',()=>{
  const receivables=fs.readFileSync(path.join(__dirname,'../templates/finance_receivables.html'),'utf8');
  const operations=fs.readFileSync(path.join(__dirname,'../templates/finance_operations.html'),'utf8');
  const reports=fs.readFileSync(path.join(__dirname,'../templates/finance_reports.html'),'utf8');
  assert.match(receivables,/Menu Pelanggan/);
  assert.match(receivables,/Tambah Customer/);
  assert.match(operations,/Biaya Rutin/);
  assert.match(operations,/Tambah Biaya/);
  assert.match(reports,/Filter &amp; Export/);
  assert.match(reports,/Kas &amp; Rekening/);
});


test('dashboard exposes main finance icon navigation',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  for(const label of ['Menu Finance','Transaksi','Pelanggan','Penagihan','Biaya Rutin','Laporan','Bank','AI Assistant']){
    assert.match(html,new RegExp(label));
  }
  assert.doesNotMatch(html,/Alat Finance Lainnya/);
  assert.match(html,/finance-home-grid/);
});


test('dashboard keeps monthly overview compact',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  assert.match(html,/Ringkasan Bulan/);
  assert.match(html,/data-finance-open="period-dialog"/);
  assert.match(html,/data-finance-open="balance-dialog"/);
  assert.match(html,/Transaksi Terbaru/);
  assert.match(html,/Lihat Semua/);
  assert.doesNotMatch(html,/<h2>Bulan \{\{ month \}\}<\/h2>/);
  assert.doesNotMatch(html,/<h2>Uang Tersedia<\/h2>/);
});
