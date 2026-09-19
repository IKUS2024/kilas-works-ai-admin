// Focused regression: visible category matches direction; Lainnya retains entered notes.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
test('direction changes and Lainnya visibility preserve notes',()=>{
  const input={value:'Servis mesin kopi',required:false,disabled:false};
  const other={hidden:true,style:{display:'none'},querySelector:()=>input};
  const kind={value:'INCOME',addEventListener(_,callback){this.change=callback;}};
  const options=[['1','INCOME','false'],['2','INCOME','true'],['3','EXPENSE','false'],['4','EXPENSE','true']].map(([value,direction,other])=>({value,dataset:{direction,other},disabled:false,hidden:false}));
  const category={value:'1',options,get selectedOptions(){return options.filter(o=>o.value===this.value);},addEventListener(_,callback){this.change=callback;},closest(){return form;}};
  const form={querySelector:selector=>selector==='[name="direction"]'?kind:other};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/finance_branches.js'),'utf8'),{document:{querySelectorAll:selector=>selector==='[data-other-category]'?[category]:[]}});
  assert.equal(options[2].disabled,true);
  assert.equal(input.disabled,true);assert.equal(other.hidden,true);assert.equal(other.style.display,'none');
  category.value='2';category.change();
  assert.equal(other.hidden,false);assert.equal(other.style.display,'');assert.equal(input.required,true);assert.equal(input.disabled,false);
  kind.value='EXPENSE';kind.change();
  assert.equal(category.value,'3');assert.equal(options[0].disabled,true);assert.equal(other.hidden,true);assert.equal(other.style.display,'none');
  category.value='4';category.change();
  assert.equal(input.value,'Servis mesin kopi');assert.equal(input.required,true);
});

test('rupiah input accepts plain, dot, and comma grouping and normalizes to dots',()=>{
  const amount={value:'1000000',dataset:{},addEventListener(name,callback){this[name]=callback;}};
  const document={
    querySelectorAll(selector){return selector==='[data-idr-input]'?[amount]:[];},
    getElementById(){return null;}
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/finance_branches.js'),'utf8'),{document});
  assert.equal(amount.value,'1.000.000');
  amount.value='1,250,000';amount.input();assert.equal(amount.value,'1.250.000');
  amount.value='1250000';amount.input();assert.equal(amount.value,'1.250.000');
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
  assert.match(html,/view='transactions'/);
  assert.match(html,/if show_transactions/);
  assert.doesNotMatch(html,/<h2>Bulan \{\{ month \}\}<\/h2>/);
  assert.doesNotMatch(html,/<h2>Uang Tersedia<\/h2>/);
});


test('finance actual dates are capped at today and empty latest card is conditional',()=>{
  const dashboard=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  const edit=fs.readFileSync(path.join(__dirname,'../templates/finance_transaction_edit.html'),'utf8');
  const receipt=fs.readFileSync(path.join(__dirname,'../templates/finance_receipt.html'),'utf8');
  const invoice=fs.readFileSync(path.join(__dirname,'../templates/finance_invoice_form.html'),'utf8');
  const payment=fs.readFileSync(path.join(__dirname,'../templates/finance_invoice_detail.html'),'utf8');
  const bank=fs.readFileSync(path.join(__dirname,'../templates/finance_bank_detail.html'),'utf8');
  const bankReview=fs.readFileSync(path.join(__dirname,'../templates/_finance_bank_review_fields.html'),'utf8');
  assert.match(dashboard,/name="occurred_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(edit,/name="occurred_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(receipt,/name="occurred_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(invoice,/name="issue_date"[^>]*max="\{\{ today \}\}"/);
  assert.match(payment,/name="paid_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(bank,/name="occurred_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(bankReview,/name="transaction_date"[^>]*max="\{\{ today \}\}"/);
  assert.match(dashboard,/\{% if transactions %\}<div class="card" id="transactions">/);
});


test('finance date inputs cap actual transaction dates while schedules may be future',()=>{
  const dashboard=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  const edit=fs.readFileSync(path.join(__dirname,'../templates/finance_transaction_edit.html'),'utf8');
  const invoice=fs.readFileSync(path.join(__dirname,'../templates/finance_invoice_form.html'),'utf8');
  assert.match(dashboard,/name="occurred_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(edit,/name="occurred_on"[^>]*max="\{\{ today \}\}"/);
  assert.match(invoice,/name="issue_date"[^>]*max="\{\{ today \}\}"/);
  assert.doesNotMatch(invoice,/name="due_date"[^>]*max=/);
});

test('transaction forms expose formatted rupiah input and hide conditional details cleanly',()=>{
  const dashboard=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  const edit=fs.readFileSync(path.join(__dirname,'../templates/finance_transaction_edit.html'),'utf8');
  assert.match(dashboard,/name="amount"[^>]*data-idr-input/);
  assert.match(edit,/name="amount"[^>]*data-idr-input/);
  assert.match(dashboard,/\[data-other-field\]\[hidden\]\{display:none!important\}/);
  assert.match(edit,/\[data-other-field\]\[hidden\]\{display:none!important\}/);
  assert.match(dashboard,/1000000, 1\.000\.000, atau 1,000,000/);
});


test('period month availability follows the selected year',()=>{
  const html=fs.readFileSync(path.join(ROOT,'templates','_finance_period_selector.html'),'utf8');
  assert.match(html,/selectedYear === currentYear && optionMonth > currentMonth/);
  assert.match(html,/yearSelect\.addEventListener\('change', syncMonths\)/);
  assert.match(html,/monthSelect\.selectedOptions\[0\]\?\.disabled/);
});


test('dashboard period picker supports single range and all modes',()=>{
  const dashboard=fs.readFileSync(path.join(ROOT,'templates','finance_dashboard.html'),'utf8');
  const selector=fs.readFileSync(path.join(ROOT,'templates','_finance_dashboard_period_selector.html'),'utf8');
  assert.match(dashboard,/Ringkasan Periode/);
  assert.match(dashboard,/\*\*period_query/);
  assert.match(selector,/Satu bulan/);
  assert.match(selector,/Rentang bulan/);
  assert.match(selector,/Semua transaksi/);
  assert.match(selector,/data-period-range/);
});
