const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '../app/static/js', name), 'utf8');

test('registration check delivers location in the same authenticated response', async () => {
  const text = read('liff.js');
  const start = text.indexOf('async function confirmUserRegistration(');
  const requests = [], events = [];
  const location = {area: '和泊町', address: '拠点'};
  const context = vm.createContext({
    window: {REQUIRE_USER_REGISTRATION: true, getCachedUserRegistration: () => true},
    document: {querySelector: () => ({})}, LIFF_TRACE_ID: 'test',
    setUserRegistrationState() {}, logToServer() {},
    notifyUserRegistrationConfirmed: (...args) => events.push(args),
    fetch: async (url, options) => {
      requests.push({url, options});
      return {ok: true, status: 200, json: async () => ({exists: true, profile_location: location})};
    },
  });
  vm.runInContext(text.slice(start, text.indexOf('\n}', start) + 2), context);
  assert.equal(await context.confirmUserRegistration('owner'), true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/users/check/owner?include=location');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.deepEqual(events, [['owner', location]]);
});

test('registration location event fills the form without another profile request', () => {
  const handlers = {}, locationInput = {}, customInput = {addEventListener() {}, value: ''}, label = {};
  const root = {dataset: {}, querySelectorAll: () => [], closest: () => null,
    querySelector: selector => ({
      'input[name="location"]': locationInput,
      '[data-custom-location-panel]': {}, '[data-custom-location]': customInput,
      '[data-profile-location-label]': label,
      'input[name="location_source"]:checked': {value: 'profile'},
    })[selector]};
  const context = vm.createContext({document: {querySelector: () => root},
    window: {addEventListener: (name, fn) => { handlers[name] = fn; }},
    fetch: () => { throw new Error('unexpected profile request'); },
  });
  vm.runInContext(read('material_registration.js'), context);
  handlers['user-registration-confirmed']({detail: {userId: 'owner', profileLocation: {area: '和泊町', address: '拠点'}}});
  assert.equal(locationInput.value, '和泊町 拠点');
  assert.equal(label.textContent, '和泊町 拠点');
});

test('confirmation waits for image preparation and prevents duplicate submission', async () => {
  const nodes = [];
  const node = tag => ({tag, handlers: {}, children: [], textContent: '',
    setAttribute() {}, append(...children) { this.children.push(...children); },
    addEventListener(name, handler) { this.handlers[name] = handler; },
    close() { this.handlers.close?.(); },
  });
  const submit = node('button'), form = node('form');
  let sent = 0, prepared = 0, release;
  const pending = new Promise(resolve => { release = resolve; });
  form.querySelector = () => submit;
  form.requestSubmit = () => {
    const event = {defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
    form.handlers.submit(event);
    if (!event.defaultPrevented) sent++;
  };
  const context = vm.createContext({
    window: {addEventListener() {}, preparePostImages: () => { prepared++; return pending; }},
    document: {querySelectorAll: () => [form], querySelector: () => node('main'),
      createElement: tag => { const result = node(tag); nodes.push(result); return result; }},
    URL: {revokeObjectURL() {}}, queueMicrotask,
  });
  vm.runInContext(read('post_preview.js'), context);
  const confirm = nodes.find(n => n.textContent === 'この内容で投稿する');
  const first = confirm.handlers.click();
  await confirm.handlers.click();
  assert.equal(prepared, 1);
  assert.equal(sent, 0);
  assert.equal(confirm.disabled, true);
  let cancelled = false;
  nodes.find(n => n.tag === 'dialog').handlers.cancel({preventDefault() { cancelled = true; }});
  assert.equal(cancelled, true);
  release(); await first;
  assert.equal(sent, 1);
  assert.equal(confirm.disabled, false);
});
