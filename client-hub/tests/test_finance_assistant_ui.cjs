// Finance Assistant chat UX contract. Backend safety is covered by Python tests.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../static/finance_assistant.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../templates/finance_assistant.html'),'utf8');

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
  assert.match(script,/applyNaturalEdits/);
  assert.match(script,/ubah jadi 300 ribu/);
  assert.match(script,/token:same\.token,confirm:true/);
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
