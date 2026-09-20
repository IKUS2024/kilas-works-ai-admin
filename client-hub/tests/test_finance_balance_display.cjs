const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

test('main cash summary never converts or combines native currency balances',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/_finance_cash_summary.html'),'utf8');
  assert.match(html,/Saldo Tersedia Sekarang/);
  assert.match(html,/row\.balance_minor\|finance_money\(row\.currency\)/);
  assert.match(html,/Tidak dikonversi atau digabung dengan kurs/);
  assert.doesNotMatch(html,/data-cash-display-value/);
  assert.doesNotMatch(html,/data-cash-display-currency/);
  assert.doesNotMatch(html,/balance_displays/);
});

test('cashflow currency navigation uses compact tabs instead of a large select',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/_finance_cash_summary.html'),'utf8');
  const script=fs.readFileSync(path.join(__dirname,'../static/finance_cashflow_switcher.js'),'utf8');
  assert.match(html,/cash-currency-tab/);
  assert.match(html,/role="tablist"/);
  assert.doesNotMatch(html,/<select[^>]*data-cashflow-currency/);
  assert.match(script,/classList\.toggle\('active'/);
  assert.match(script,/aria-selected/);
});
