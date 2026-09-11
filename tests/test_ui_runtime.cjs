const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const template = fs.readFileSync(path.join(__dirname, '../app/templates/users/me.html'), 'utf8');
function source(name) {
  const start = template.indexOf(`  function ${name}(`);
  assert.ok(start >= 0);
  return template.slice(start, template.indexOf('\n  }', start) + 4);
}
function setup(userId = 'owner') {
  const nodes = new Map();
  const context = vm.createContext({
    currentIdToken: '', currentMaterials: [],
    matchStatusOptions: ['未対応', '連絡・調整中', '成立', '辞退'],
    getMaterialImageUrls: () => [], formatDateJp: value => value || '',
    document: { getElementById: id => {
      if (!nodes.has(id)) nodes.set(id, {value: userId, innerHTML: ''});
      return nodes.get(id);
    } },
  });
  for (const name of ['escapeHtml', 'renderOptions', 'renderMaterialCard', 'renderMaterials', 'renderMatchingHistory']) {
    vm.runInContext(source(name), context);
  }
  return {context, nodes};
}
test('material cards render without matching context and escape user text', () => {
  const {context, nodes} = setup();
  context.renderMaterials([{material_id: 'm1', title: '<script>bad()</script>', effective_status: 'active'}], 'owner');
  const html = nodes.get('materials-container').innerHTML;
  assert.ok(html.includes('/materials/m1/close'));
  assert.ok(!html.includes('<script>'));
});
test('only the post owner gets the completion choice and matching revisions are retained', () => {
  const match = {match_id: 'match1', match_type: 'request', provider_user_id: 'visitor', requester_user_id: 'owner',
    entry_owner_id: 'owner', status: '未対応', updated_at: '2026-09-09 09:00:00'};
  for (const [user, shouldClose] of [['owner', true], ['visitor', false]]) {
    const {context, nodes} = setup(user);
    context.renderMatchingHistory([match]);
    const html = nodes.get('matching-history-container').innerHTML;
    assert.equal(html.includes('name="completion_action"'), shouldClose);
    assert.ok(html.includes('id="match-match1"'));
    assert.ok(html.includes('name="expected_updated_at" value="2026-09-09 09:00:00"'));
  }
});
test('viewing requests never offer material post closure', () => {
  const {context, nodes} = setup();
  context.renderMatchingHistory([{match_id: 'visit1', match_type: 'viewing', provider_user_id: 'owner', entry_owner_id: 'owner'}]);
  assert.ok(!nodes.get('matching-history-container').innerHTML.includes('name="completion_action"'));
});

test('inquiries show separate sharing directions and never render unsafe contact links', () => {
  const {context, nodes} = setup();
  context.renderMatchingHistory([{match_id: 'm', provider_user_id: 'owner', status: '連絡・調整中',
    provider_contact_share_status: 'shared', other_display_name: '<script>bad</script>',
    received_contact: {contact_method: 'LINE', contact_value: 'javascript:alert(1)', message: '<img src=x>'}}]);
  const html = nodes.get('matching-history-container').innerHTML;
  assert.ok(html.includes('あなたの連絡先は送信済み'));
  assert.ok(html.includes('相手の連絡先が届いています'));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img src=x>'));
  assert.ok(!html.includes('<select name="status">'));
});

test('finished inquiries do not offer sharing or repeat completion', () => {
  const {context, nodes} = setup();
  context.renderMatchingHistory([{match_id: 'm', provider_user_id: 'owner', status: '成立'}]);
  const html = nodes.get('matching-history-container').innerHTML;
  assert.ok(html.includes('完了・見送り（1）'));
  assert.ok(!html.includes('/share-contact'));
  assert.ok(!html.includes('/status'));
});

test('login preserves matching link but removes authentication callback parameters', () => {
  const context = vm.createContext({URLSearchParams, window: { location: {
    origin: 'https://example.com', pathname: '/users/me',
    search: '?tab=matches&match=match1&refresh=1&code=secret&state=secret&redirect=https://other.example'
  }}});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/js/line-auth-common.js'), 'utf8'), context);
  vm.runInContext(source('liffLoginRedirectUrl'), context);
  assert.equal(context.liffLoginRedirectUrl(), 'https://example.com/users/me?tab=matches&match=match1&refresh=1');
});
