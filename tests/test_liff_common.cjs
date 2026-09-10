const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const common = fs.readFileSync(path.join(__dirname, '../app/static/js/line-auth-common.js'), 'utf8');
const diagnostics = fs.readFileSync(path.join(__dirname, '../app/static/js/liff-diagnostics.js'), 'utf8');

function setupDiagnostics(enabled = true) {
  const timers = [], requests = [], listeners = {};
  const context = vm.createContext({
    Date, Blob, navigator: {},
    window: {LIFF_DEBUG_LOGGING: enabled, LIFF_TRACE_ID: 'trace-test',
      LIFF_DIAGNOSTIC_SCHEMA: {events: ['auth.flow_started'], booleans: ['online'], numbers: ['durationMs'], enums: {errorCode: ['400']}},
      addEventListener: (name, callback) => { listeners[name] = callback; }},
    setTimeout: (callback, delay) => { timers.push({callback, delay}); return timers.length; },
    fetch: async (url, options) => { requests.push(JSON.parse(options.body)); return {ok: true}; },
  });
  vm.runInContext(diagnostics, context);
  return {context, timers, requests, listeners};
}
const settle = () => new Promise(resolve => setImmediate(resolve));

test('disabled diagnostics perform no network requests or scheduling', () => {
  const {context, timers, requests, listeners} = setupDiagnostics(false);
  context.window.sendClientDiagnostic('auth.flow_started', {errorMessage: 'secret'});
  listeners.pagehide();
  assert.equal(timers.length, 0);
  assert.equal(requests.length, 0);
});

test('diagnostics batch events and strip free text before transmission', async () => {
  const {context, timers, requests} = setupDiagnostics();
  for (let i = 0; i < 12; i++) context.window.sendClientDiagnostic('auth.flow_started', {
    online: true, durationMs: 4, errorMessage: 'private-token', errorCode: 'private-token', userId: 'private-token',
  });
  assert.equal(timers.length, 1);
  timers.shift().callback(); await settle();
  assert.equal(requests[0].events.length, 10);
  assert.equal(requests[0].events[0].details.online, true);
  assert.ok(!JSON.stringify(requests).includes('private-token'));
  timers.shift().callback(); await settle();
  assert.equal(requests[1].events.length, 2);
});

test('rate limits back off and report lost events on the next successful batch', async () => {
  const {context, timers, requests} = setupDiagnostics();
  let first = true;
  context.fetch = async (url, options) => {
    requests.push(JSON.parse(options.body));
    if (first) { first = false; return {ok: false, status: 429, headers: {get: () => '60'}}; }
    return {ok: true};
  };
  context.window.sendClientDiagnostic('auth.flow_started');
  timers.shift().callback(); await settle();
  context.window.sendClientDiagnostic('auth.flow_started');
  assert.ok(timers[0].delay > 59000);
  // Page exit sends the bounded final batch even while the ordinary timer is paused.
  context.window.addEventListener = () => {};
  const realNow = Date.now;
  try {
    context.Date = {now: () => realNow() + 61000};
    timers.shift().callback(); await settle();
  } finally { context.Date = Date; }
  assert.equal(requests[1].dropped, 1);
});

test('queue overflow is bounded and counted', async () => {
  const {context, timers, requests} = setupDiagnostics();
  for (let i = 0; i < 65; i++) context.window.sendClientDiagnostic('auth.flow_started');
  timers.shift().callback(); await settle();
  assert.equal(requests[0].dropped, 5);
});

test('shared SDK initialization coalesces callers and permits retry after failure', async () => {
  let calls = 0;
  const context = vm.createContext({window: {liff: {init: async () => {
    calls++;
    if (calls === 1) throw new Error('SDK unavailable');
  }}}});
  vm.runInContext(common, context);
  const first = context.window.LineAuth.initialize('id');
  assert.equal(context.window.LineAuth.initialize('id'), first);
  await assert.rejects(first);
  await context.window.LineAuth.initialize('id');
  await context.window.LineAuth.initialize('id');
  assert.equal(calls, 2);
});

test('future login timestamps do not block recovery and malformed token decoding is safe', () => {
  const context = vm.createContext({Date, window: {
    sessionStorage: {getItem: () => String(Date.now() + 600000)},
    liff: {getDecodedIDToken: () => { throw new Error('invalid'); }},
  }});
  vm.runInContext(common, context);
  assert.equal(context.window.LineAuth.recentlyAttempted(), false);
  assert.equal(context.window.LineAuth.hasFreshIdToken('token'), false);
});

test('posting form authentication recovers from 503 without redirect or losing its token', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../app/static/js/liff.js'), 'utf8');
  const start = source.indexOf('async function initializeLiff()');
  const end = source.indexOf('\n}', start) + 2;
  let status = 503, retry, initCount = 0;
  const states = [];
  const context = vm.createContext({
    Date, performance, LIFF_TRACE_ID: 'trace-test', console: {log() {}, warn() {}, error: (...args) => {throw args.at(-1);}},
    window: {LINE_LOGIN_ENABLED: true, LIFF_ID: 'id', dispatchEvent() {}},
    liff: {init: async () => {initCount++;}, isLoggedIn: () => true,
      getProfile: async () => ({userId: 'user'}), getIDToken: () => 'fresh',
      getDecodedIDToken: () => ({exp: Date.now() / 1000 + 3600})},
    document: {getElementById: () => null, querySelectorAll: () => []},
    fetch: async () => ({ok: status === 200, status}), Event: class {},
    getLiffDebugContext: () => ({}), logToServer() {}, installLineAuthSubmitGuard() {}, installImagePreviews() {},
    setLineAuthControls: enabled => states.push(enabled), restoreLineSession: async () => false,
    clearLegacyLiffReturnUrl() {}, clearLiffLoginAttempt() {}, syncLineFriendshipStatus: async () => {},
    confirmUserRegistration: async () => true,
  });
  context.window.liff = context.liff;
  vm.runInContext(common, context);
  context.window.LineAuth.clearRetry = () => {};
  context.window.LineAuth.showRetry = callback => { retry = callback; };
  context.hasFreshIdToken = token => context.window.LineAuth.hasFreshIdToken(token);
  vm.runInContext(source.slice(start, end), context);
  await context.initializeLiff();
  assert.equal(context.window.LINE_ID_TOKEN, 'fresh');
  assert.equal(states.at(-1), false);
  assert.equal(typeof retry, 'function');
  status = 200;
  await retry();
  assert.equal(states.at(-1), true);
  assert.equal(context.window.LINE_SESSION_AUTHENTICATED, true);
  assert.equal(initCount, 1);
});
