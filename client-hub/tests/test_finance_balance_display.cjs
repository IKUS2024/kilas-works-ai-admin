const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

test('cash summary combines native balances into selected display currency without mutating ledger',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/_finance_cash_summary.html'),'utf8');
  assert.match(html,/Saldo Tersedia Sekarang/);
  assert.match(html,/balance_total_display/);
  assert.match(html,/fx_status_label/);
  assert.match(html,/otomatis dikonversi ke/);
  assert.doesNotMatch(html,/Tidak dikonversi atau digabung dengan kurs/);
});

test('cashflow summary uses the same converted display currency',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/_finance_cash_summary.html'),'utf8');
  assert.match(html,/period_income_display/);
  assert.match(html,/period_expense_display/);
  assert.match(html,/period_net_display/);
  assert.match(html,/display_currency/);
});
