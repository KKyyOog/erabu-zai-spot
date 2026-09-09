(() => {
  'use strict';
  const dirtyForms = new Set();
  const prefix = 'erabu-post-draft-v2:';
  let leaving = false;
  let fieldNumber = 0;
  const draftKey = (kind, owner) => `${prefix}${kind}:${owner}`;
  const fieldKey = field => {
    const panel = field.closest('[data-size-panel]')?.dataset.sizePanel;
    if (panel) return `size:${panel}:${field.dataset.sizeField || (field.hasAttribute('data-size-unit') ? 'unit' : field.name)}`;
    return field.name || field.id;
  };
  const draftFields = form => Array.from(form.querySelectorAll('input, select, textarea'))
    .filter(field => !['hidden', 'file', 'password', 'submit', 'button'].includes(field.type));

  try {
    const done = window.COMPLETED_DRAFT;
    if (done) sessionStorage.removeItem(draftKey(done.kind, done.owner));
    Object.keys(sessionStorage).filter(key => key.startsWith(prefix)).forEach(key => {
      const value = JSON.parse(sessionStorage.getItem(key));
      if (!value || Date.now() - value.savedAt > 86400000) sessionStorage.removeItem(key);
    });
  } catch (_) { /* Storage is optional. */ }

  function enhanceFields(root) {
    root.querySelectorAll('label:not([for])').forEach(label => {
      if (label.querySelector('input, select, textarea')) return;
      const field = label.nextElementSibling;
      if (!field?.matches('input:not([type=hidden]), select, textarea')) return;
      if (!field.id) field.id = `ui-field-${++fieldNumber}`;
      label.htmlFor = field.id;
    });
  }

  function clearError(field) {
    if (!field.dataset.errorId) return;
    document.getElementById(field.dataset.errorId)?.remove();
    const described = (field.getAttribute('aria-describedby') || '').split(' ').filter(id => id !== field.dataset.errorId);
    field.setAttribute('aria-describedby', described.join(' '));
    field.removeAttribute('aria-invalid');
    delete field.dataset.errorId;
  }

  document.addEventListener('invalid', event => {
    const field = event.target;
    clearError(field);
    field.closest('details')?.setAttribute('open', '');
    const error = document.createElement('p');
    error.id = `field-error-${++fieldNumber}`;
    error.className = 'field-error';
    error.textContent = field.validationMessage || '入力内容を確認してください。';
    field.insertAdjacentElement('afterend', error);
    field.dataset.errorId = error.id;
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', `${field.getAttribute('aria-describedby') || ''} ${error.id}`.trim());
  }, true);
  document.addEventListener('input', event => clearError(event.target));
  document.addEventListener('change', event => clearError(event.target));

  function attachDraft(form) {
    const owner = form.querySelector('[name=line_user_id]')?.value;
    if (form.dataset.draftReady || !owner || form.hidden) return;
    form.dataset.draftReady = 'true';
    const key = draftKey(form.dataset.draftKind, owner);
    const note = document.createElement('aside');
    note.className = 'draft-note';
    note.setAttribute('aria-live', 'polite');
    const text = document.createElement('p');
    text.textContent = '入力内容はこのタブに一時保存されます（24時間）。写真は再選択が必要です。';
    note.append(text);
    form.prepend(note);

    const save = () => {
      dirtyForms.add(form);
      try {
        const values = draftFields(form).map(field => ({name: fieldKey(field), value: field.value, checked: field.checked}));
        sessionStorage.setItem(key, JSON.stringify({savedAt: Date.now(), values}));
        text.textContent = '下書きを一時保存しました。写真は画面を開き直すと再選択が必要です。';
      } catch (_) {
        text.textContent = 'このブラウザーでは下書きを保存できません。入力中は画面を閉じないでください。';
      }
    };
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (saved && Date.now() - saved.savedAt <= 86400000 && Array.isArray(saved.values)) {
        text.textContent = '前回の下書きがあります。復元した後、写真を選び直してください。';
        const restore = document.createElement('button');
        restore.type = 'button';
        restore.textContent = '下書きを復元';
        restore.className = 'secondary-button';
        const discard = document.createElement('button');
        discard.type = 'button';
        discard.textContent = '下書きを削除';
        discard.className = 'secondary-button';
        restore.addEventListener('click', () => {
          const fields = draftFields(form);
          fields.forEach(field => {
            const value = saved.values.find(value => value.name === fieldKey(field)
              && (!['radio', 'checkbox'].includes(field.type) || value.value === field.value));
            if (!value) return;
            if (['radio', 'checkbox'].includes(field.type)) field.checked = Boolean(value.checked);
            else field.value = value.value;
          });
          // Recompute conditional location fields and the composed size.
          fields.forEach(field => field.dispatchEvent(new Event('change', {bubbles: true})));
          fields.forEach(field => field.dispatchEvent(new Event('input', {bubbles: true})));
          restore.remove(); discard.remove(); save();
        });
        discard.addEventListener('click', () => {
          try { sessionStorage.removeItem(key); } catch (_) {}
          restore.remove(); discard.remove();
          text.textContent = '下書きを削除しました。新しく入力できます。';
        });
        note.append(restore, discard);
      }
    } catch (_) { /* Ignore invalid saved drafts. */ }
    form.addEventListener('input', save);
    form.addEventListener('change', save);
  }

  function enhance() {
    enhanceFields(document);
    document.querySelectorAll('form[data-draft-kind]').forEach(attachDraft);
  }
  enhance();
  let scheduled = false;
  new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => { scheduled = false; enhance(); });
  }).observe(document.querySelector('main'), {childList: true, subtree: true, attributes: true, attributeFilter: ['hidden']});
  window.addEventListener('user-registration-confirmed', enhance);
  window.addEventListener('line-authenticated', enhance);
  document.addEventListener('input', event => {
    const form = event.target.closest('form[data-unsaved], form.material-edit-form');
    if (form) dirtyForms.add(form);
  });
  document.addEventListener('form-saved', event => dirtyForms.delete(event.target));

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || !dirtyForms.size || link.target === '_blank' || event.ctrlKey || event.metaKey) return;
    const target = new URL(link.href, location.href);
    if (target.pathname === location.pathname && target.search === location.search && target.hash) return;
    if (!window.confirm('未保存の入力があります。投稿の写真やプロフィールの変更は保持されません。ページを移動しますか？')) {
      event.preventDefault();
      window.hidePageTransitionSkeleton?.();
    } else leaving = true;
  }, true);
  document.addEventListener('submit', event => {
    queueMicrotask(() => { if (!event.defaultPrevented) leaving = true; });
  });
  window.addEventListener('pageshow', () => { leaving = false; });
  window.addEventListener('beforeunload', event => {
    if (!leaving && dirtyForms.size) { event.preventDefault(); event.returnValue = ''; }
  });
})();
