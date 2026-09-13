const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const read = name => fs.readFileSync(path.join(__dirname, '../app/static/js', name), 'utf8');

function ui() {
  const handlers = {}, errors = new Map(), jobs = [];
  const document = {
    querySelectorAll: () => [], querySelector: () => ({}),
    addEventListener: (name, fn) => {
      const previous = handlers[name];
      handlers[name] = event => { previous?.(event); fn(event); };
    },
    getElementById: id => errors.get(id),
    createElement: () => ({remove() { errors.delete(this.id); }}),
  };
  const context = vm.createContext({document, queueMicrotask: fn => jobs.push(fn),
    window: {addEventListener() {}}, sessionStorage: {},
    MutationObserver: class { observe() {} },
  });
  vm.runInContext(read('ui.js'), context);
  return {handlers, errors, jobs};
}

test('invalid fields open every disclosure and focus only the first error', () => {
  const {handlers, errors, jobs} = ui();
  const outer = {open: false}, inner = {open: false, parentElement: {closest: () => outer}};
  let focused = 0, scrolled = 0;
  const field = {dataset: {}, type: 'text', tagName: 'INPUT', validity: {valueMissing: true},
    attrs: {'aria-describedby': 'existing-hint'},
    closest: () => inner,
    insertAdjacentElement: (_, error) => errors.set(error.id, error),
    getAttribute(name) { return this.attrs[name]; },
    setAttribute(name, value) { this.attrs[name] = value; },
    removeAttribute(name) { delete this.attrs[name]; },
    focus() { focused++; }, scrollIntoView() { scrolled++; },
  };
  let prevented = 0;
  handlers.invalid({target: field, preventDefault() { prevented++; }});
  const second = {...field, dataset: {}, attrs: {}, focus() { throw new Error('second field stole focus'); }};
  handlers.invalid({target: second, preventDefault() { prevented++; }});
  assert.equal(prevented, 2);
  assert.equal(inner.open && outer.open, true);
  assert.equal(errors.get(field.dataset.errorId).textContent, 'この項目を入力してください。');
  jobs.forEach(fn => fn());
  assert.equal(focused, 1);
  assert.equal(scrolled, 1);
  handlers.input({target: field});
  assert.equal(field.attrs['aria-describedby'], 'existing-hint');
  assert.equal(field.attrs['aria-invalid'], undefined);
});

test('required photo and selection errors are actionable; custom errors stay intact', () => {
  const {handlers, errors} = ui();
  for (const [type, tagName, validity, expected] of [
    ['file', 'INPUT', {valueMissing: true}, '写真を1枚以上選んでください。'],
    ['', 'SELECT', {valueMissing: true}, '項目を選んでください。'],
    ['file', 'INPUT', {customError: true}, '写真は6枚までです。'],
  ]) {
    const field = {type, tagName, validity, dataset: {}, validationMessage: '写真は6枚までです。',
      closest: () => null, getAttribute: () => '', setAttribute() {},
      insertAdjacentElement: (_, error) => errors.set(error.id, error),
    };
    handlers.invalid({target: field, preventDefault() {}});
    assert.equal(errors.get(field.dataset.errorId).textContent, expected);
  }
});

function photoGallery(length) {
  const nodes = [], events = {};
  const node = tag => ({tag, children: [], handlers: {}, setAttribute() {},
    append(...items) { this.children.push(...items); },
    addEventListener(name, fn) { this.handlers[name] = fn; },
  });
  const gallery = {scrollLeft: 0,
    querySelectorAll: () => Array.from({length}, (_, i) => ({getBoundingClientRect: () => ({left: 20 + i * 310 - gallery.scrollLeft})})),
    getBoundingClientRect: () => ({left: 20}),
    scrollTo({left}) { this.scrollLeft = left; }, closest: () => null,
    addEventListener: (name, fn) => { events[name] = fn; },
    insertAdjacentElement() {},
  };
  vm.runInNewContext(read('photo_controls.js'), {window: {}, document: {
    querySelectorAll: () => [gallery], createElement: tag => { const item = node(tag); nodes.push(item); return item; },
  }});
  return {gallery, events, nodes};
}

test('photo buttons and count follow clicks, swipe position, and bounds', () => {
  const {gallery, events, nodes} = photoGallery(3);
  const [previous, next] = nodes.filter(n => n.tag === 'button');
  const count = nodes.find(n => n.tag === 'span');
  assert.equal(count.textContent, '1 / 3枚');
  assert.equal(previous.disabled, true);
  next.handlers.click();
  assert.equal(gallery.scrollLeft, 310);
  assert.equal(count.textContent, '2 / 3枚');
  next.handlers.click();
  assert.equal(next.disabled, true);
  next.handlers.click();
  assert.equal(gallery.scrollLeft, 620);
  gallery.scrollLeft = 0; events.scroll();
  assert.equal(count.textContent, '1 / 3枚');
  assert.equal(previous.disabled, true);
});

test('single photos do not add unnecessary navigation', () => {
  assert.equal(photoGallery(1).nodes.length, 0);
});
