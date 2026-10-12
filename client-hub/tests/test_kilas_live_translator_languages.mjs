import test from 'node:test';
import assert from 'node:assert/strict';
import {syncLanguagePair, validLanguagePair} from '../static/kilas_live_translator_languages.mjs';

const select = (value, codes = ['id', 'en', 'ja', 'zh']) => ({value, options: codes.map(value => ({value, disabled: false}))});
const disabled = field => field.options.filter(option => option.disabled).map(option => option.value);

test('both dropdowns exclude the language selected opposite them', () => {
  const a = select('id'), b = select('en');
  assert.equal(syncLanguagePair(a, b), true);
  assert.deepEqual(disabled(a), ['en']);
  assert.deepEqual(disabled(b), ['id']);
});

for (const changed of ['primary', 'secondary']) {
  test(`changing ${changed} updates exclusions and releases the old option`, () => {
    const a = select('id'), b = select('en');
    syncLanguagePair(a, b);
    const field = changed === 'primary' ? a : b;
    field.value = 'ja';
    assert.equal(syncLanguagePair(a, b, field), true);
    assert.equal(field.value, 'ja');
    assert.deepEqual(disabled(a), [b.value]);
    assert.deepEqual(disabled(b), [a.value]);
  });

  test(`a restored duplicate retains the changed ${changed} and repairs its partner`, () => {
    const a = select('en'), b = select('en');
    const field = changed === 'primary' ? a : b;
    assert.equal(syncLanguagePair(a, b, field), true);
    assert.equal(field.value, 'en');
    assert.notEqual(a.value, b.value);
    assert.deepEqual(disabled(a), [b.value]);
    assert.deepEqual(disabled(b), [a.value]);
  });
}

test('saved empty, removed and unknown values are repaired from available options', () => {
  for (const [first, second] of [['', ''], ['old', 'en'], ['id', 'removed']]) {
    const a = select(first), b = select(second);
    assert.equal(syncLanguagePair(a, b), true);
    assert.equal(validLanguagePair(a, b), true);
  }
});

test('reset and page restoration synchronize previous disabled options', () => {
  const a = select('ja'), b = select('zh');
  syncLanguagePair(a, b);
  a.value = 'id'; b.value = 'en';
  syncLanguagePair(a, b);
  assert.deepEqual(disabled(a), ['en']);
  assert.deepEqual(disabled(b), ['id']);
});

test('missing, identical, unknown or single-choice pairs never pass admission', () => {
  for (const [first, second] of [['', 'en'], ['id', 'id'], ['removed', 'en']]) {
    assert.equal(validLanguagePair(select(first), select(second)), false);
  }
  const a = select('id', ['id']), b = select('id', ['id']);
  assert.equal(syncLanguagePair(a, b), false);
  assert.equal(b.value, '');
});

test('every supported pair remains valid and changing either side repairs a collision', () => {
  const codes = ['id','en','ja','ko','zh','es','fr','de','th','vi','ar','pt','it','hi','ms','nl','ru','tr'];
  for (const first of codes) for (const second of codes) {
    const a = select(first, codes), b = select(second, codes);
    assert.equal(syncLanguagePair(a, b), true);
    assert.equal(a.value, first);
    assert.notEqual(a.value, b.value);
    a.value = b.value;
    assert.equal(syncLanguagePair(a, b, a), true);
    b.value = a.value;
    assert.equal(syncLanguagePair(a, b, b), true);
  }
});

test('submit rejects a stale duplicate before audio context, microphone or network work', async () => {
  const listeners = new Map(), windows = new Map();
  const a = select('id'), b = select('en');
  let focused = false, audioCalls = 0, networkCalls = 0;
  a.addEventListener = b.addEventListener = () => {};
  b.focus = () => { focused = true; };
  const error = {hidden: true, textContent: ''};
  const start = {disabled: false};
  const form = {
    elements: {language_a: a, language_b: b}, reportValidity: () => true,
    querySelector: query => query === 'button' ? start : {value: 'synthetic-csrf'},
    addEventListener: (type, handler) => listeners.set(type, handler),
  };
  const active = {querySelector: () => ({})};
  const nodes = {'.kilas-live-translator': {dataset: {ready: 'true'}}, '#live-setup-form': form, '#live-setup': {}, '#live-active': active, '#live-error': error, '#live-end': {addEventListener() {}}, '#live-session-status': {}, '#live-recovery-retry': {addEventListener() {}}, '#live-recovery': {}, '#live-recovery-status': {}, '#live-recovery-end': {addEventListener() {}}, '#live-recovery-check': {addEventListener() {}}};
  const old = {document: globalThis.document, window: globalThis.window, fetch: globalThis.fetch};
  try {
    globalThis.document = {querySelector: query => nodes[query], addEventListener() {}};
    globalThis.window = {addEventListener: (type, handler) => windows.set(type, handler), AudioContext: class {constructor() { audioCalls++; }}};
    globalThis.fetch = async url => { networkCalls++; assert.equal(url, '/kilas-translator/live/sessions/active'); return {ok: true, json: async () => ({session: null})}; };
    await import('../static/kilas_live_translator.mjs?source-test');
    await new Promise(resolve => setImmediate(resolve));
    networkCalls = 0;
    a.value = b.value;
    listeners.get('submit')({preventDefault() {}});
    assert.equal(focused, true);
    assert.equal(error.hidden, false);
    assert.match(error.textContent, /dua bahasa yang berbeda/);
    assert.equal(audioCalls, 0);
    assert.equal(networkCalls, 0);
    windows.get('pageshow')();
    assert.equal(validLanguagePair(a, b), true);
    a.value = b.value;
    listeners.get('reset')();
    await new Promise(resolve => queueMicrotask(resolve));
    assert.equal(validLanguagePair(a, b), true);
  } finally {
    for (const [key, value] of Object.entries(old)) {
      if (value === undefined) delete globalThis[key]; else globalThis[key] = value;
    }
  }
});
