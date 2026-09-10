(() => {
  'use strict';
  const attemptKey = 'erabu_zai_spot_liff_login_attempted_at';
  let initPromise;
  const storage = (action, value) => {
    try { return window.sessionStorage[action](attemptKey, value); } catch (_) { return null; }
  };
  const recentlyAttempted = () => {
    const age = Date.now() - Number(storage('getItem') || 0);
    return age >= 0 && age < 60000;
  };
  const redirectUrl = () => {
    const incoming = new URLSearchParams(window.location.search || '');
    const safe = new URLSearchParams();
    for (const key of ['tab', 'match', 'refresh', 'notification_required', 'q', 'area', 'type', 'material_type', 'page']) {
      if (incoming.has(key)) safe.set(key, incoming.get(key).slice(0, 100));
    }
    return `${window.location.origin}${window.location.pathname}${safe.size ? `?${safe}` : ''}`;
  };
  window.LineAuth = {
    recentlyAttempted,
    rememberAttempt: () => storage('setItem', String(Date.now())),
    clearAttempt: () => storage('removeItem'),
    redirectUrl,
    hasFreshIdToken(token) {
      try { return Boolean(token) && Number(window.liff.getDecodedIDToken?.()?.exp || 0) * 1000 > Date.now() + 30000; }
      catch (_) { return false; }
    },
    initialize(liffId) {
      if (!initPromise) {
        initPromise = Promise.resolve().then(() => window.liff.init({liffId})).catch(error => {
          initPromise = null;
          throw error;
        });
      }
      return initPromise;
    },
    restart(onBlocked, onRedirect) {
      if (window.liff.isInClient?.()) { onBlocked('in_client'); return false; }
      if (recentlyAttempted()) { onBlocked('recent_attempt'); return false; }
      storage('setItem', String(Date.now()));
      onRedirect();
      if (window.liff.isLoggedIn()) window.liff.logout();
      window.liff.login({redirectUri: redirectUrl()});
      return true;
    },
    async verify(url, options) {
      // Only verification requests use this helper; never retry mutations.
      try { return await fetch(url, options); }
      catch (_) { return {ok: false, status: 503}; }
    },
    showRetry(retry) {
      let panel = document.getElementById('line-auth-retry');
      if (!panel) {
        panel = document.createElement('div');
        panel.id = 'line-auth-retry';
        panel.setAttribute('role', 'status');
        (document.querySelector('main') || document.body).prepend(panel);
      }
      panel.replaceChildren();
      const message = document.createElement('p');
      message.textContent = 'LINE認証に一時的につながりません。通信状況を確認し、少し待ってから再試行してください。';
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = '再試行';
      button.addEventListener('click', async () => {
        button.disabled = true;
        try { await retry(); } finally { button.disabled = false; }
      });
      panel.append(message, button);
    },
    clearRetry() { document.getElementById('line-auth-retry')?.remove(); },
  };
})();
