const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

test('finance transaction ledger is compact, grouped by date, and uses a small action menu',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');
  const css=fs.readFileSync(path.join(__dirname,'../static/finance_home.css'),'utf8');
  assert.match(html,/namespace\(date=''\)/);
  assert.match(html,/finance-tx-date/);
  assert.match(html,/finance-tx-row/);
  assert.match(html,/finance-tx-description/);
  assert.match(html,/finance-tx-actions-menu/);
  assert.doesNotMatch(html,/finance-entry-actions[^\n]*🗑️ Hapus/);
  assert.match(css,/-webkit-line-clamp:2/);
  assert.match(css,/\.finance-tx-amount\{font-size:17px/);
  assert.match(css,/\.finance-tx-row\{[^}]*padding:10px 2px/);
});
