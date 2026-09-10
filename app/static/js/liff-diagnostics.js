(() => {
  'use strict';
  const schema = window.LIFF_DIAGNOSTIC_SCHEMA || {events: [], booleans: [], numbers: [], enums: {}};
  const allowedEvents = new Set(schema.events);
  let queue = [], dropped = 0, timer = null, sending = false, pausedUntil = 0;
  const sanitize = details => {
    const result = {};
    if (!details || typeof details !== 'object') return result;
    for (const key of schema.booleans) {
      if (typeof details[key] === 'boolean') result[key] = details[key];
    }
    for (const key of schema.numbers) {
      if (Number.isFinite(details[key]) && details[key] >= 0 && details[key] <= 86400000) result[key] = details[key];
    }
    for (const [key, values] of Object.entries(schema.enums)) {
      if (key in details) result[key] = values.includes(details[key]) ? details[key] : '[redacted]';
    }
    return result;
  };
  const schedule = () => {
    if (timer || sending || !queue.length) return;
    timer = setTimeout(() => { timer = null; flush(); }, Math.max(1000, pausedUntil - Date.now()));
  };
  const flush = async (leaving = false) => {
    if (window.LIFF_DEBUG_LOGGING !== true || sending || (!queue.length && !dropped)) return;
    if (!leaving && Date.now() < pausedUntil) { schedule(); return; }
    const events = queue.splice(0, 10), reportedDrops = dropped;
    dropped = 0;
    const payload = JSON.stringify({traceId: window.LIFF_TRACE_ID, events, dropped: reportedDrops});
    if (leaving) {
      try {
        if (navigator.sendBeacon?.('/link/liff-debug', new Blob([payload], {type: 'application/json'}))) return;
      } catch (_) { /* Continue with fetch. */ }
    }
    sending = true;
    try {
      const response = await fetch('/link/liff-debug', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: payload, keepalive: true,
      });
      if (!response.ok) {
        dropped += events.length + reportedDrops;
        const seconds = response.status === 429 ? Number(response.headers.get('Retry-After')) || 60 : 60;
        pausedUntil = Date.now() + Math.max(1, Math.min(3600, seconds)) * 1000;
      }
    } catch (_) {
      dropped += events.length + reportedDrops;
      pausedUntil = Date.now() + 60000;
    } finally { sending = false; schedule(); }
  };
  window.sendClientDiagnostic = (event, details = {}, level = 'info') => {
    if (window.LIFF_DEBUG_LOGGING !== true || !allowedEvents.has(event)) return;
    if (queue.length >= 60) { dropped++; return; }
    queue.push({event, details: sanitize(details), level: ['info', 'warning', 'error', 'debug'].includes(level) ? level : 'info'});
    schedule();
  };
  window.addEventListener('pagehide', () => {
    // Fit the final request into one bounded batch and expose local loss.
    if (queue.length > 10) { dropped += queue.length - 10; queue = queue.slice(0, 10); }
    flush(true);
  });
})();
