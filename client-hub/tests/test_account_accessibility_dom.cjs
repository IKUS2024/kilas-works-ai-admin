// Execute actual inline template scripts against isolated DOM, never real accounts.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require(process.env.JSDOM_PATH || 'jsdom');
const root = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(root, 'templates', name), 'utf8');
const translations = JSON.parse(fs.readFileSync(path.join(root, 'locales/ui.json'), 'utf8'));
function labels(source, lang) {
  return source.replace(/{{ ui_t\('([^']+)'\) }}/g, (_, key) => lang === 'id' ? key : translations[key]?.[lang] || key);
}
const script = source => [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
for (const lang of ['id','en']) test(`login password toggle localized ${lang}`, () => {
  const source = labels(read('login.html'), lang);
  const button = source.match(/<button class="password-toggle"[\s\S]*?<\/button>/)[0];
  const dom = new JSDOM(`<input id="auth-password" type="password" value="unchanged">${button}`, {runScripts:'outside-only'});
  dom.window.eval(script(source));
  const btn = dom.window.document.querySelector('button');
  btn.click();
  assert.equal(btn.getAttribute('aria-label'), translations['Sembunyikan password'][lang] || 'Sembunyikan password');
  assert.equal(btn.getAttribute('aria-pressed'), 'true');
  btn.click();
  assert.equal(btn.getAttribute('aria-label'), translations['Tampilkan password'][lang] || 'Tampilkan password');
  assert.equal(dom.window.document.querySelector('input').type,'password');
  assert.equal(dom.window.document.querySelector('input').value,'unchanged');
});
for (const workspace of [false,true]) test(`account keyboard and dialog names workspace=${workspace}`, () => {
  const source = labels(read('account.html'), 'en');
  const buttons = [...source.matchAll(/<button[^>]+data-account-tab="[^"]+"[^>]*>[\s\S]*?<\/button>/g)].map(m=>m[0]).join('');
  const panels = [...source.matchAll(/<section[^>]+data-account-panel="[^"]+"[^>]*>/g)].map(m=>m[0]+'</section>').join('');
  const dialogs = [...source.matchAll(/<dialog[^>]+>[\s\S]*?<h2[^>]*>[\s\S]*?<\/h2>/g)].map(m=>m[0]+'</div></dialog>').join('');
  const dom = new JSDOM(buttons+panels+dialogs,{url:'https://example.test/account#security',runScripts:'outside-only'});
  let js = script(source).replace(/{% if account_workspace\|default\(false\) %}([\s\S]*?){% endif %}/g, (_, body) => {
    const [yes,no=''] = body.split('{% else %}'); return workspace?yes:no;
  }).replace(/{{ 'true' if (?:password_open|pending_email_change) else 'false' }}/g, 'false');
  dom.window.eval(js);
  const doc=dom.window.document, tabs=[...doc.querySelectorAll('[role=tab]')];
  const check = name => {
    assert.equal(tabs.filter(t=>t.tabIndex===0).length,1);
    assert.equal(tabs.find(t=>t.tabIndex===0).dataset.accountTab,name);
    for(const t of tabs){ const panel=doc.getElementById(t.getAttribute('aria-controls')); assert.equal(panel.hidden,t.dataset.accountTab!==name);assert.equal(panel.getAttribute('aria-labelledby'),t.id); }
  };
  const key = value => doc.activeElement.dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true}));
  check('security'); tabs[2].focus();key('ArrowRight');check('personal');assert.equal(doc.activeElement,tabs[0]);
  key('ArrowLeft');check('security');key('Home');check('personal');key('End');check('security');
  key('a');check('security');tabs[1].click();check('business');
  if(workspace){dom.window.history.replaceState(null,'','#personal');dom.window.dispatchEvent(new dom.window.PopStateEvent('popstate'));check('personal');}
  for(const dialog of doc.querySelectorAll('dialog')) assert.ok(doc.getElementById(dialog.getAttribute('aria-labelledby'))?.textContent.trim());
  assert.equal(doc.querySelectorAll('dialog').length,2);
});
