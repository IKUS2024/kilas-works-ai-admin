// Finance Assistant chat UX contract. Backend safety is covered by Python tests.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../static/finance_assistant.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../templates/finance_assistant.html'),'utf8');
const flow=fs.readFileSync(path.join(__dirname,'../finance_assistant_flow.py'),'utf8');
const customerManual=fs.readFileSync(path.join(__dirname,'../templates/finance_receivables.html'),'utf8');
const recurringManual=fs.readFileSync(path.join(__dirname,'../templates/finance_operations.html'),'utf8');
const transactionManual=fs.readFileSync(path.join(__dirname,'../templates/finance_dashboard.html'),'utf8');

test('assistant is a single chat composer, not a review-page handoff',()=>{
  assert.equal((html.match(/<textarea\b/g)||[]).length,1);
  assert.match(html,/id="assistant-result" class="assistant-chat-log"/);
  assert.match(html,/data-confirm=/);
  assert.match(html,/data-document=/);
  assert.doesNotMatch(html,/assistant-review-link/);
  assert.doesNotMatch(html,/Buka Review/);
});

test('chat understands typed confirmation, cancellation and revisions',()=>{
  assert.match(script,/confirmWords=/);
  assert.match(script,/cancelWords=/);
  assert.match(script,/confirmPending/);
  assert.doesNotMatch(script,/applyNaturalEdits/);
  assert.match(script,/context:pending.context,confirmation:pending.token/);

  assert.match(script,/token:same\.token,confirm:true/);
});

test('follow-up chat edits understand customer and operational fields',()=>{
  assert.match(script,/composer.dataset.message/);
  assert.match(script,/field.required!==false/);
  assert.doesNotMatch(script,/Saya belum menangkap bagian yang ingin diubah/);
});

test('AI and manual Finance writes share the same business fields',()=>{
  for(const name of ['name','phone','email','notes'])assert.match(customerManual,new RegExp('name="'+name+'"'));
  for(const name of ['name','account_id','amount','category_id','cadence','next_due_on','end_on','project_id','counterparty_name','description'])
    assert.match(recurringManual,new RegExp('name="'+name+'"'));
  for(const name of ['account_id','amount','occurred_on','category_id','description','project_id','customer_id','counterparty_name'])
    assert.match(transactionManual,new RegExp('name="'+name+'"'));
  for(const key of ['project_id','customer_id','counterparty_name'])assert.match(flow,new RegExp("field\\('"+key+"'"));
  assert.match(flow,/Nomor telepon/);
  assert.match(flow,/Vendor \/ penerima/);
  assert.match(flow,/Pihak terkait/);
});

test('messages append as chat turns and successful writes answer in chat',()=>{
  assert.match(script,/appendUser/);
  assert.match(script,/appendAssistant/);
  assert.match(script,/assistant-turn-user/);
  assert.match(script,/assistant-turn-success/);
  assert.match(script,/title:'Berhasil'/);
  assert.doesNotMatch(script,/window\.location/);
});

test('documents stay inline including uncertain classification and bank PDFs',()=>{
  assert.match(script,/BANK_STATEMENT/);
  assert.match(script,/HANDWRITTEN_NOTE/);
  assert.match(script,/needs_document_choice/);
  assert.match(script,/processDocument/);
  assert.match(html,/\.pdf,\.csv/);
});

test('composer clears sent text and supports enter-to-send',()=>{
  assert.match(script,/text\.value=''/);
  assert.match(script,/event\.key==='Enter'/);
  assert.match(script,/!event\.shiftKey/);
});

test('read-only chat carries signed conversation context between turns',()=>{
  assert.match(script,/queryContext/);
  assert.match(script,/payload\.query_context=queryContext/);
  assert.match(script,/data\.query_context/);
  assert.match(script,/queryContext=''/);
});
