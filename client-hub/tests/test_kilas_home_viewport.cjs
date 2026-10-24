const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Run the actual layout controller without a browser, microphone or transport.
function layout({viewport = true, scrollTop = 1400} = {}) {
  const styles = new Map(), classes = new Map(), windowEvents = new Map(), viewportEvents = new Map();
  const timeline = {scrollHeight: 2000, scrollTop, clientHeight: 600};
  const form = {id: 'ai-composer', addEventListener() {}, querySelector() { return {}; }};
  const nodes = {'#ai-messages,#agent-conversation': timeline, '#ai-composer,#agent-chat-form': form, '#ai-input,#agent-message': {}, '#home-task-value': {}, '#ai-send': {}, '#ai-notice,#agent-chat-error': {}, '#ai-pending,#work-pending-files': {children: []}};
  const root = {querySelector: selector => nodes[selector] || null, querySelectorAll: () => [], dispatchEvent() {}, addEventListener() {}};
  const visual = viewport ? {height: 650, offsetTop: 0, addEventListener: (type, callback) => viewportEvents.set(type, callback)} : null;
  const window = {innerHeight: 650, visualViewport: visual, addEventListener: (type, callback) => windowEvents.set(type, callback)};
  const document = {querySelector: selector => selector==='.kilas-home-workspace'?root:null, documentElement: {style: {setProperty: (key, value) => styles.set(key, value)}}, body: {classList: {toggle: (key, value) => classes.set(key, value)}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/kilas_home.js'), 'utf8'), {window, document, innerHeight: 650, location: {search: ''}, URLSearchParams, Event});
  return {styles, classes, timeline, visual, window, document, windowEvents, viewportEvents};
}

test('keyboard viewport height and offset keep layout immediately above the keyboard', () => {
  const state = layout();
  state.visual.height = 350; state.visual.offsetTop = 70;
  state.viewportEvents.get('resize')();
  assert.equal(state.styles.get('--home-viewport-height'), '350px');
  assert.equal(state.styles.get('--home-viewport-top'), '70px');
  assert.equal(state.styles.get('--home-input-max-height'), '44px');
  assert.equal(state.classes.get('home-keyboard-open'), true);
  state.visual.height = 650; state.visual.offsetTop = 0;
  state.viewportEvents.get('resize')();
  assert.equal(state.styles.get('--home-viewport-height'), '650px');
  assert.equal(state.classes.get('home-keyboard-open'), false);
});

test('Android layout resize recognizes an open keyboard even with no visual/layout height gap', () => {
  const state = layout();
  state.document.activeElement = {matches: () => true};
  state.visual.height = 350; state.window.innerHeight = 350;
  state.windowEvents.get('resize')();
  assert.equal(state.classes.get('home-keyboard-open'), true);
  assert.equal(state.styles.get('--home-input-max-height'), '44px');
  state.visual.height = 650; state.window.innerHeight = 650;
  state.windowEvents.get('resize')();
  assert.equal(state.classes.get('home-keyboard-open'), false);
});

test('keyboard resize preserves an older transcript reading position', () => {
  const state = layout({scrollTop: 200});
  state.visual.height = 350; state.viewportEvents.get('resize')();
  assert.equal(state.timeline.scrollTop, 200);
});

test('following the latest message stays at the end after viewport resize', () => {
  const state = layout();
  state.timeline.scrollTop = 1400; state.timeline.scrollHeight = 2100; state.timeline.clientHeight = 700;
  state.viewportEvents.get('resize')();
  assert.equal(state.timeline.scrollTop, 2100);
});

test('layout falls back to window height when visualViewport is unavailable', () => {
  const state = layout({viewport: false});
  state.window.innerHeight = 500; state.windowEvents.get('resize')();
  assert.equal(state.styles.get('--home-viewport-height'), '500px');
  assert.equal(state.styles.get('--home-viewport-top'), '0px');
  assert.equal(state.classes.get('home-keyboard-open'), false);
});
