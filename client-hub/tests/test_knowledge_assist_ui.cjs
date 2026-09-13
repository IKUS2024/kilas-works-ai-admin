// Test-only dependency: jsdom. Run with a rendered Knowledge page as argv[2].
const fs = require('fs');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const source = fs.readFileSync('client-hub/static/knowledge_assist.js', 'utf8');
const html = fs.readFileSync(process.argv[2], 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(result = {draft_fields:{short_description:'Draft bisnis'},questions:[],warnings:[]}) {
  const dom = new JSDOM(html, {url:'https://example.test/business/1/memory',runScripts:'outside-only'});
  const {window:w} = dom; const calls = []; let submitted = 0;
  w.fetch = async (url, options) => {calls.push({url,options,payload:JSON.parse(options.body)});return {ok:true,json:async()=>result};};
  const form = w.document.querySelector('.knowledge-page form');
  form.addEventListener('submit', event=>{event.preventDefault();submitted++;});
  for (const script of w.document.querySelectorAll('script:not([src])')) w.eval(script.textContent);
  w.eval(source);
  return {dom,w,form,calls,submits:()=>submitted};
}
function clickText(w,text) {
  const b = [...w.document.querySelectorAll('button')].find(b=>b.textContent===text);
  assert.ok(b, 'Missing button: '+text);b.click();
}
let passed = 0;
async function test(name, fn) {await fn();passed++;console.log('PASS '+name);}
(async()=>{
  await test('load typing blur readiness and main submit do not call AI',async()=>{
    const s=setup();const input=s.form.elements.namedItem('short_description');
    input.value='Typed';input.dispatchEvent(new s.w.Event('input',{bubbles:true}));input.dispatchEvent(new s.w.Event('change',{bubbles:true}));input.dispatchEvent(new s.w.Event('blur'));
    s.form.dispatchEvent(new s.w.Event('submit',{bubbles:true,cancelable:true}));
    await tick();assert.equal(s.calls.length,0);assert.equal(s.submits(),1);s.dom.window.close();
  });
  await test('explicit click calls once and apply changes only browser form',async()=>{
    const s=setup();const before=s.form.elements.namedItem('short_description').value;
    clickText(s.w,'✨ Bantu Isi dengan AI');await tick();
    assert.equal(s.calls.length,1);assert.equal(s.form.elements.namedItem('short_description').value,before);
    assert.ok(s.w.document.querySelector('.knowledge-assist-panel').textContent.includes('belum tersimpan'));
    clickText(s.w,'Terapkan ke form');
    assert.equal(s.form.elements.namedItem('short_description').value,'Draft bisnis');assert.equal(s.calls.length,1);assert.equal(s.submits(),0);
    assert.ok(s.calls[0].options.headers['X-CSRF-Token']);s.dom.window.close();
  });
  await test('cancel leaves form unchanged',async()=>{
    const s=setup();const before=s.form.elements.namedItem('short_description').value;
    clickText(s.w,'✨ Bantu Isi dengan AI');await tick();clickText(s.w,'Batal');
    assert.equal(s.form.elements.namedItem('short_description').value,before);assert.equal(s.calls.length,1);assert.equal(s.submits(),0);s.dom.window.close();
  });
  await test('questions wait for explicit Bantu lagi',async()=>{
    const s=setup({draft_fields:{},questions:['Apa layananmu?'],warnings:[]});
    clickText(s.w,'✨ Bantu Isi dengan AI');await tick();
    const answer=s.w.document.querySelector('.knowledge-assist-panel textarea');answer.value='Konsultasi';answer.dispatchEvent(new s.w.Event('input',{bubbles:true}));
    await tick();assert.equal(s.calls.length,1);clickText(s.w,'Bantu lagi');await tick();
    assert.equal(s.calls.length,2);assert.ok(s.calls[1].payload.clarifications.includes('Konsultasi'));assert.equal(s.submits(),0);s.dom.window.close();
  });
  await test('new service card sends only its fields and applies only there',async()=>{
    const s=setup({draft_fields:{name:'Rapi'},questions:[],warnings:[]});
    s.w.document.querySelector('[data-add-knowledge="services"]').click();
    const cards=s.w.document.querySelectorAll('#knowledge-services fieldset');const card=cards[cards.length-1];
    card.querySelector('[name="services_name"]').value='Only this card';
    card.querySelector('[data-assist-scope]').click();await tick();
    assert.equal(s.calls[0].payload.scope,'services');assert.equal(s.calls[0].payload.fields.name,'Only this card');
    assert.ok(!JSON.stringify(s.calls[0].payload).includes('Catatan lama tanpa format'));
    clickText(s.w,'Terapkan ke form');assert.equal(card.querySelector('[name="services_name"]').value,'Rapi');assert.equal(s.submits(),0);s.dom.window.close();
  });
  await test('model text renders as text without HTML execution',async()=>{
    const attack='<img src=x onerror="window.pwned=true">';
    const s=setup({draft_fields:{short_description:attack},questions:[attack],warnings:[attack]});
    clickText(s.w,'✨ Bantu Isi dengan AI');await tick();
    const panel=s.w.document.querySelector('.knowledge-assist-panel');assert.equal(panel.querySelector('img'),null);assert.ok(panel.textContent.includes(attack));assert.equal(s.w.pwned,undefined);s.dom.window.close();
  });
  await test('editing during request prevents stale draft overwrite',async()=>{
    const s=setup();clickText(s.w,'✨ Bantu Isi dengan AI');await tick();
    s.form.elements.namedItem('short_description').value='New human edit';clickText(s.w,'Terapkan ke form');
    assert.equal(s.form.elements.namedItem('short_description').value,'New human edit');assert.equal(s.submits(),0);s.dom.window.close();
  });
  await test('API failure keeps form and offers close',async()=>{
    const s=setup();s.w.fetch=async()=>({ok:false,json:async()=>({error:'Coba lagi sebentar.'})});
    const before=s.form.elements.namedItem('short_description').value;
    clickText(s.w,'✨ Bantu Isi dengan AI');await tick();
    assert.ok(s.w.document.querySelector('.knowledge-assist-panel').textContent.includes('Coba lagi sebentar.'));
    assert.equal(s.form.elements.namedItem('short_description').value,before);assert.equal(s.submits(),0);clickText(s.w,'Tutup');s.dom.window.close();
  });
  console.log(`RESULT ${passed} passed, 0 failed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
