// Real Flask markup; mocked account-type responses, no browser or database writes.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {pathToFileURL} from 'node:url';

const fixturePath=process.env.KILAS_FINANCE_LOCALE_FIXTURE_PATH;
if(!fixturePath)throw Error('Render test_ui_finance_locale.py with KILAS_FINANCE_LOCALE_FIXTURE_PATH first.');
const pages=JSON.parse(readFileSync(fixturePath,'utf8'));
const directory=process.env.KILAS_UI_DOM_TOOLS||join(tmpdir(),'kilas-learning-dom');
const {JSDOM}=createRequire(pathToFileURL(join(directory,'package.json')))('jsdom');
const code=name=>readFileSync(new URL('../static/'+name,import.meta.url),'utf8');
const source=code('finance_branches.js');
const tick=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};

for(const locale of ['en','id']){
 test(`Finance ${locale} localizes default account types after AJAX while preserving canonical and custom values`,async t=>{
  const dom=new JSDOM(pages['accounts-'+locale],{url:'https://app.example.test/business/1/finance?view=accounts',runScripts:'outside-only'});
  t.after(()=>dom.window.close());const {window}=dom,{document}=window;
  window.eval(code('ui_i18n.js'));
  const manager=document.querySelector('[data-account-type-manager]');assert.ok(manager);
  const select=manager.querySelector('[data-account-type-select]'),input=manager.querySelector('[data-account-type-name]');
  const panel=manager.querySelector('[data-account-type-panel]'),status=manager.querySelector('[data-account-type-status]');
  const requests=[],confirmations=[];
  window.confirm=message=>{confirmations.push(message);return true;};
  let options=pages['type-options'].map(row=>({...row}));
  window.fetch=async(url,request)=>{
   assert.equal(url,panel.dataset.accountTypeUrl);assert.equal(request.method,'POST');assert.equal(request.credentials,'same-origin');
   const body=Object.fromEntries(request.body.entries());requests.push(body);
   assert.equal(body.csrf_token,manager.querySelector('[name="csrf_token"]').value);
   assert.equal(body.branch_id,panel.dataset.accountTypeBranch);
   if(body.action==='create')options.push({name:body.name,is_default:false});
   else if(body.action==='delete')options=options.filter(row=>row.name!==body.name);
   else assert.fail('Unexpected action');
   return {ok:true,json:async()=>({options})};
  };
  window.eval(source);
  assert.equal(requests.length,0);
  const direction=document.querySelector('#add-transaction [name="direction"]');
  if(direction){
   direction.value='INCOME';direction.dispatchEvent(new window.Event('change'));
   assert.equal(document.querySelector('#add-transaction [data-counterparty-label]').textContent,window.KilasUI.t('Sumber / Pelanggan'));
   assert.equal(document.querySelector('#add-transaction [data-counterparty-placeholder]').textContent,window.KilasUI.t('Pilih Pelanggan'));
   direction.value='EXPENSE';direction.dispatchEvent(new window.Event('change'));
   assert.equal(document.querySelector('#add-transaction [data-counterparty-label]').textContent,window.KilasUI.t('Penerima / Vendor'));
  }
  const create=document.querySelector('[data-category-create-popup]');
  if(create){
   create.click();
   assert.equal(document.querySelector('[data-category-editor-title]').textContent,window.KilasUI.t('Tambah Kategori'));
   assert.equal(document.querySelector('[data-category-editor-create-name]').placeholder,window.KilasUI.t('Contoh: Operasional'));
  }
  input.value='Profile';manager.querySelector('[data-account-type-add]').click();await tick();
  assert.equal(requests[0].name,'Profile');assert.equal(select.value,'Profile');
  assert.equal([...select.options].find(row=>row.value==='Profile').textContent,'Profile');
  assert.equal([...select.options].find(row=>row.value==='Recent').textContent,'Recent');
  assert.equal([...select.options].find(row=>row.value==='Wallet').textContent,locale==='en'?'Wallet':'Dompet');
  assert.equal(status.textContent,window.KilasUI.t('Tipe ditambahkan dan langsung dipilih.'));
  const row=manager.querySelector('[data-account-type-row][data-name="Wallet"]');
  assert.equal(row.querySelector('span').textContent,locale==='en'?'Wallet':'Dompet');
  assert.equal(row.querySelector('button').textContent,locale==='en'?'Delete':'Hapus');
  row.querySelector('button').click();await tick();
  assert.equal(requests[1].action,'delete');assert.equal(requests[1].name,'Wallet');
  assert.equal(confirmations[0],window.KilasUI.t('Hapus tipe "{name}" dari pilihan akun baru? Akun lama tetap aman.',{name:locale==='en'?'Wallet':'Dompet'}));
  assert.equal(select.value,'Profile');assert.equal(status.textContent,window.KilasUI.t('Tipe dihapus dari pilihan akun baru.'));
  assert.equal([...select.options].find(row=>row.value==='Profile').textContent,'Profile');
 });
}
