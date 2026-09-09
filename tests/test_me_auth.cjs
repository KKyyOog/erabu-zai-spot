const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const template = fs.readFileSync(path.join(__dirname, '../app/templates/users/me.html'), 'utf8');
function source(name) {
  const start = template.search(new RegExp(`^  (?:async )?function ${name}\\(`, 'm'));
  assert.ok(start >= 0, name);
  const end = template.indexOf('\n  }', start) + 4;
  return template.slice(start, end);
}

function setup({ token = 'expired', inClient = false, loggedIn = true, status = 200 } = {}) {
  const calls = [];
  const storage = new Map();
  const context = vm.createContext({
    performance, Date, console, URLSearchParams,
    LIFF_LOGIN_ATTEMPT_KEY: 'attempt', LIFF_LOGIN_RETRY_DELAY_MS: 60000,
    LIFF_TRACE_ID: 'test', currentIdToken: 'stale', currentAuthMode: '',
    window: {
      LINE_LOGIN_ENABLED: true,
      location: { origin: 'https://example.com', pathname: '/users/me' },
      sessionStorage: {
        getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value),
        removeItem: key => storage.delete(key),
      },
    },
    document: { getElementById: () => ({ value: '', textContent: '' }) },
    liff: {
      isLoggedIn: () => loggedIn, isInClient: () => inClient,
      getIDToken: () => token,
      getDecodedIDToken: () => ({ exp: Date.now() / 1000 + (token === 'fresh' ? 3600 : -1) }),
      logout: () => { calls.push('logout'); loggedIn = false; },
      login: options => calls.push(['login', options.redirectUri]),
    },
    logLiffDebug() {}, getLiffDebugContext: () => ({}),
    restoreCachedLineIdentity: async () => false, initializeLiffClient: async () => true,
    setSubmitEnabled: value => calls.push(['submit', value]), setLoading() {},
    showUnavailableState: message => calls.push(['unavailable', message]),
    getCurrentLineProfile: async () => ({ userId: 'Utest' }),
    fetch: async () => { calls.push('fetch'); return { ok: status === 200, status, headers: {get: () => '12'}, json: async () => ({}) }; },
    setIdentityReadiness() {}, syncFriendshipStatus: async () => {},
    loadMeProfile: async () => calls.push('profile'),
  });
  for (const name of ['clearLiffLoginAttempt', 'recentlyAttemptedLiffLogin', 'rememberLiffLoginAttempt',
    'liffLoginRedirectUrl', 'hasFreshIdToken', 'restartLineAuthentication', 'connectLineIdentity']) {
    vm.runInContext(source(name), context);
  }
  return { context, calls, storage };
}

for (const token of ['expired', '']) {
  test(`unavailable token (${token}) restarts login without sending stale credentials`, async () => {
    const { context, calls } = setup({ token });
    assert.equal(await context.connectLineIdentity(true), true);
    assert.deepEqual(calls, [['submit', false], 'logout', ['login', 'https://example.com/users/me']]);
    assert.equal(context.currentIdToken, '');
    await context.connectLineIdentity(true);
    assert.equal(calls.filter(call => Array.isArray(call) && call[0] === 'login').length, 1);
    assert.equal(calls.at(-1)[0], 'unavailable');
  });
}

test('LIFF browser shows reopen guidance without logout or redirect', async () => {
  const { context, calls } = setup({ inClient: true });
  assert.equal(await context.connectLineIdentity(true), true);
  assert.equal(calls.at(-1)[0], 'unavailable');
  assert.match(calls.at(-1)[1], /画面を閉じて/);
  assert.equal(calls.length, 2);
});

test('optional authentication does not redirect for an expired token', async () => {
  const { context, calls } = setup();
  assert.equal(await context.connectLineIdentity(false), false);
  assert.deepEqual(calls, []);
});

test('fresh token loads profile and clears retry guard', async () => {
  const { context, calls, storage } = setup({ token: 'fresh' });
  storage.set('attempt', String(Date.now()));
  assert.equal(await context.connectLineIdentity(true), true);
  assert.deepEqual(calls, ['fetch', 'profile']);
  assert.equal(storage.has('attempt'), false);
});

test('server rejection restarts authentication before loading profile', async () => {
  const { context, calls } = setup({ token: 'fresh', status: 401 });
  assert.equal(await context.connectLineIdentity(true), true);
  assert.deepEqual(calls, ['fetch', ['submit', false], 'logout', ['login', 'https://example.com/users/me']]);
});

test('server failure does not trigger repeated logins', async () => {
  const { context, calls } = setup({ token: 'fresh', status: 500 });
  await assert.rejects(context.connectLineIdentity(true), /LINE authentication failed/);
  assert.deepEqual(calls, ['fetch']);
});

test('rate limiting explains the waiting time without restarting login', async () => {
  const {context, calls} = setup({token: 'fresh', status: 429});
  assert.equal(await context.connectLineIdentity(true), true);
  assert.equal(calls[0], 'fetch');
  assert.equal(calls[1][0], 'unavailable');
  assert.match(calls[1][1], /12秒/);
  assert.equal(calls.length, 2);
});
