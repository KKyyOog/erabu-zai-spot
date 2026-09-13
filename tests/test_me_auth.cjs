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
    setUserPageSkeleton() {}, initMeFlow: async () => {},
    loadMeProfile: async () => calls.push('profile'),
  });
  context.window.liff = context.liff;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/line-auth-common.js'), 'utf8'), context);
  context.window.LineAuth.clearRetry = () => {};
  context.window.LineAuth.showRetry = () => calls.push('retry');
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
    storage.set('erabu_zai_spot_liff_login_attempted_at', String(Date.now()));
  assert.equal(await context.connectLineIdentity(true), true);
  assert.deepEqual(calls, ['fetch', 'profile']);
    assert.equal(storage.has('erabu_zai_spot_liff_login_attempted_at'), false);
});

test('profile starts while friendship confirmation is still pending', async () => {
  const { context, calls } = setup({ token: 'fresh' });
  let releaseFriendship;
  let profileStarted;
  const started = new Promise(resolve => { profileStarted = resolve; });
  context.syncFriendshipStatus = () => new Promise(resolve => { releaseFriendship = resolve; });
  context.loadMeProfile = async () => { calls.push('profile'); profileStarted(); };
  const connecting = context.connectLineIdentity(true);
  await started;
  assert.ok(releaseFriendship);
  assert.deepEqual(calls, ['fetch', 'profile']);
  releaseFriendship();
  assert.equal(await connecting, true);
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

test('temporary outage offers retry without logout or clearing credentials', async () => {
  const {context, calls} = setup({token: 'fresh', status: 503});
  assert.equal(await context.connectLineIdentity(true), true);
  assert.deepEqual(calls, ['fetch', 'retry']);
  assert.equal(context.currentIdToken, 'stale');
});

test('network outage offers retry without logout', async () => {
  const {context, calls} = setup({token: 'fresh'});
  context.fetch = async () => { throw new TypeError('network unavailable'); };
  assert.equal(await context.connectLineIdentity(true), true);
  assert.deepEqual(calls, ['retry']);
});

test('valid server session skips LIFF even after the profile cache expires', async () => {
  const {context, calls} = setup({token: 'expired'});
  context.fetch = async () => ({ok: true, json: async () => ({
    ok: true, auth_mode: 'line', line_user_id: 'Utest',
    cache_valid: false, session_valid: true, session_expires_in: 40000,
  })});
  context.setIdentityFields = () => {};
  context.loadCachedFriendshipStatus = async () => calls.push('saved friendship');
  context.initializeLiffClient = async () => { throw new Error('LIFF must not initialize'); };
  vm.runInContext(source('restoreCachedLineIdentity'), context);
  assert.equal(await context.connectLineIdentity(true), true);
  assert.deepEqual(calls, ['saved friendship', 'profile']);
  assert.equal(context.currentIdToken, '');
});

test('expired server session is not reused even with a valid profile cache', async () => {
  const {context, calls} = setup();
  context.fetch = async () => ({ok: true, json: async () => ({
    ok: true, auth_mode: 'line', line_user_id: 'Utest',
    cache_valid: true, session_valid: false,
  })});
  vm.runInContext(source('restoreCachedLineIdentity'), context);
  assert.equal(await context.restoreCachedLineIdentity(), false);
  assert.deepEqual(calls, []);
});

for (const search of ['?tab=profile', '?tab=materials', '?match=123', '?notification_required=1']) {
  test(`profile and requested tab display before delayed activity: ${search}`, async () => {
    const {context} = setup({token: 'fresh'});
    const events = [];
    let releaseActivity;
    context.window.location.search = search;
    context.userSelectedTab = false;
    context.pageTabIds = {profile: 'profile-panel', materials: 'materials-panel', matches: 'matches-panel'};
    context.setIdentityFields = () => {};
    context.fillUserForm = () => events.push('profile filled');
    context.fillContactCard = () => {};
    context.selectPageTab = name => events.push(name);
    context.setUserPageSkeleton = value => events.push(['skeleton', value]);
    context.fetch = async () => ({ok: true, status: 200,
      json: async () => ({ok: true, exists: true, user: {}, contact_card: {}})});
    const started = new Promise(resolve => {
      context.loadMeActivity = () => {
        events.push('activity started');
        resolve();
        return new Promise(finish => { releaseActivity = finish; });
      };
    });
    vm.runInContext(source('loadMeProfile'), context);
    const loading = context.loadMeProfile('Utest');
    await started;
    const expectedTab = search.includes('materials') ? 'materials' : search.includes('match=') ? 'matches' : 'profile';
    assert.deepEqual(events, ['profile filled', expectedTab, ['skeleton', false], 'activity started']);
    releaseActivity();
    await loading;
  });
}
